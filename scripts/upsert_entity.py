"""Merge entity fragments into a vault (spec section 7).

A fragment file holds one or more entities, each starting with its own
--- frontmatter --- block. Fragments may be partial: only the fields and
sections the chunk being read actually supports.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import vaultlib as v

STRUCTURAL = {"id", "type", "name", "layer", "summary", "summary_replace", "sources"}


# ── parsing fragment bundles ────────────────────────────────────────────────

def _try_frontmatter(lines: list[str], i: int):
    """If lines[i] opens an entity frontmatter block, return (fm, closing line index)."""
    for j in range(i + 1, min(len(lines), i + 200)):
        if lines[j].strip() == "---":
            try:
                fm = yaml.safe_load("\n".join(lines[i + 1:j]))
            except yaml.YAMLError:
                return None
            if isinstance(fm, dict) and ("type" in fm or "id" in fm):
                return v._yaml_scalar_safe(fm), j
            return None
    return None


def parse_fragments(text: str) -> list[tuple[dict, str]]:
    lines = text.split("\n")
    docs: list[tuple[dict, list[str]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            hit = _try_frontmatter(lines, i)
            if hit:
                docs.append((hit[0], []))
                i = hit[1] + 1
                continue
        if docs:
            docs[-1][1].append(line)
        elif line.strip():
            raise v.FormatError(f"text before the first fragment at line {i + 1}: {line[:60]!r}")
        i += 1
    return [(fm, "\n".join(body).strip("\n")) for fm, body in docs]


# ── merge machinery ─────────────────────────────────────────────────────────

def _heading_key(h: str) -> str:
    return v.slugify(h)


def _canonical_index(type_: str, heading: str) -> int:
    keys = [_heading_key(h) for h in v.SECTIONS.get(type_, [])]
    k = _heading_key(heading)
    if k in keys:
        return keys.index(k)
    if k == "notes":
        return 10_000
    return 5_000


def _block_key(b: v.Block) -> str:
    if b.kind == "fence":
        return "fence:" + re.sub(r"\s+", " ", b.text).strip().lower()
    return b.kind + ":" + v.norm_block(b.text)


def _append_blocks(section: v.Section, new_blocks: list[v.Block]) -> int:
    existing = {_block_key(b) for b in v.iter_blocks(section.lines)}
    added = 0
    last_kind = None
    ex_blocks = v.iter_blocks(section.lines)
    if ex_blocks:
        last_kind = ex_blocks[-1].kind
    for b in new_blocks:
        if b.kind == "heading":
            continue
        k = _block_key(b)
        if k in existing:
            continue
        existing.add(k)
        if section.lines and not (last_kind == "bullet" and b.kind == "bullet"):
            section.lines.append("")
        section.lines.extend(b.lines)
        last_kind = b.kind
        added += 1
    return added


def merge_body(type_: str, existing_body: str, new_body: str) -> tuple[str, int]:
    sections = v.parse_sections(existing_body)
    first = v.SECTIONS.get(type_, ["Notes"])[0]
    added = 0
    for ns in v.parse_sections(new_body):
        heading = ns.heading or first
        blocks = v.iter_blocks(ns.lines)
        if not blocks:
            continue
        target = next((s for s in sections if _heading_key(s.heading) == _heading_key(heading)), None)
        if target is None:
            target = v.Section(heading)
            idx = _canonical_index(type_, heading)
            pos = len(sections)
            for k, s in enumerate(sections):
                if s.heading and _canonical_index(type_, s.heading) > idx:
                    pos = k
                    break
            sections.insert(pos, target)
        added += _append_blocks(target, blocks)
    sections = [s for s in sections if s.lines or not s.heading]
    return v.render_sections(sections), added


def _union(a, b) -> list:
    out, seen = [], set()
    for x in v.as_list(a) + v.as_list(b):
        key = x.lower() if isinstance(x, str) else repr(x)
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


# ── matching ────────────────────────────────────────────────────────────────

@dataclass
class Index:
    by_id: dict[str, v.Entity] = field(default_factory=dict)
    by_name: dict[tuple[str, str, str], str] = field(default_factory=dict)   # (layer, type, norm) -> id

    @classmethod
    def build(cls, vault: v.Vault) -> "Index":
        idx = cls()
        for e in vault.entities:
            idx.add(e)
        return idx

    def add(self, e: v.Entity) -> None:
        self.by_id[(e.layer, e.id)] = e
        for nm in [e.name] + [str(a) for a in v.as_list(e.fm.get("aliases"))]:
            if nm:
                self.by_name.setdefault((e.layer, e.type, v.norm_name(nm)), e.id)

    def get(self, layer: str, id_: str):
        return self.by_id.get((layer, id_))

    def find(self, layer: str, type_: str, names: list[str]) -> str | None:
        for nm in names:
            hit = self.by_name.get((layer, type_, v.norm_name(nm)))
            if hit:
                return hit
        return None

    def near(self, layer: str, type_: str, name: str) -> list[str]:
        target = v.norm_name(name)
        out = []
        for (l, t, nm), id_ in self.by_name.items():
            if l != layer or t != type_ or not nm or not target:
                continue
            shorter, longer = sorted((nm, target), key=len)
            contained = len(shorter) >= 4 and re.search(rf"\b{re.escape(shorter)}\b", longer)
            if contained or difflib.SequenceMatcher(None, nm, target).ratio() > 0.85:
                if id_ not in out:
                    out.append(id_)
        return out


# ── upsert ──────────────────────────────────────────────────────────────────

@dataclass
class Result:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unresolved: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("created", "updated", "unchanged", "review", "rejected", "unresolved")}


def _resolve_name_links(body: str, idx: Index, layer: str) -> str:
    """Rewrite [[Vessa Thorn]] to [[npc/vessa-thorn|Vessa Thorn]] when the name is known."""
    def repl(m):
        inner = m.group(0)[2:-2]
        target, _, label = inner.partition("|")
        if "/" in target:
            return m.group(0)
        for lyr in (layer, "canon"):
            for t in v.TYPES:
                hit = idx.find(lyr, t, [target])
                if hit:
                    return f"[[{hit}|{label or target}]]"
        return m.group(0)
    return v.WIKILINK_RE.sub(repl, body)


def _fix_refs(e: v.Entity, idx: Index, known: set[str]) -> bool:
    """Second pass after a run: point name links and near-miss IDs at entities that now exist."""
    def resolve(target: str) -> str | None:
        if target in known:
            return None
        if "/" in target:
            t, _, slug = target.partition("/")
            if t in v.TYPES:
                for lyr in (e.layer, "canon"):
                    hit = idx.find(lyr, t, [slug.replace("-", " ")])
                    if hit and hit != target:
                        return hit
            return None
        for lyr in (e.layer, "canon"):
            for t in v.TYPES:
                hit = idx.find(lyr, t, [target])
                if hit:
                    return hit
        return None

    changed = False
    fm = e.fm
    for f in v.REF_FIELDS["*"] + v.REF_FIELDS.get(e.type, []):
        val = fm.get(f)
        if val is None:
            continue
        vals = v.as_list(val)
        new = [resolve(x) or x if isinstance(x, str) else x for x in vals]
        if new != vals:
            fm[f] = new if isinstance(val, list) else new[0]
            changed = True

    def repl(m):
        nonlocal changed
        inner = m.group(0)[2:-2]
        target, _, label = inner.partition("|")
        hit = resolve(target.strip())
        if not hit:
            return m.group(0)
        changed = True
        shown = label or (target if "/" not in target else "")
        return f"[[{hit}|{shown}]]" if shown else f"[[{hit}]]"
    body = v.WIKILINK_RE.sub(repl, e.body)
    if changed:
        e.body = body
        e.path.write_text(v.dump_document(fm, body), encoding="utf-8")
    return changed


def _first_citation(body: str, fm: dict) -> str:
    c = v.citations_in(body)
    if c:
        s, a, b = c[0]
        return f"[{s} p.{a}]" if a == b else f"[{s} pp.{a}–{b}]"
    for s in v.as_list(fm.get("sources")):
        if isinstance(s, dict) and s.get("pages"):
            return f"[{s['source']} p.{v.as_list(s['pages'])[0]}]"
    return ""


def upsert_one(root: Path, idx: Index, frag: dict, body: str, default_layer: str, res: Result) -> None:
    fm = dict(frag)
    type_ = str(fm.get("type", "")).strip()
    name = str(fm.get("name", "")).strip()
    layer = str(fm.get("layer") or default_layer)
    label = fm.get("id") or f"{type_}/{name}"
    if type_ not in v.TYPES:
        res.rejected.append(f"{label}: type {type_!r} not one of {v.TYPES}")
        return
    if not name:
        res.rejected.append(f"{label}: no name")
        return
    if layer not in v.ENTITY_LAYERS:
        res.rejected.append(f"{label}: layer must be canon or ideas (got {layer!r})")
        return

    body = _resolve_name_links(body, idx, layer)
    fm["type"], fm["name"], fm["layer"] = type_, name, layer

    if layer == "canon":
        cited = v.sources_from_citations(v.body_citations(body))
        fm["sources"] = v.merge_sources(fm.get("sources"), cited)
        if not fm["sources"]:
            res.rejected.append(f"{label}: canon fragment has no citations")
            return
    else:
        fm.pop("sources", None)
        fm.setdefault("status", "draft")
        fm.setdefault("generated", v.today())

    # match
    id_ = fm.get("id")
    if id_ and not v.ID_RE.match(str(id_)):
        res.rejected.append(f"{label}: malformed id {id_!r}")
        return
    if id_ and str(id_).split("/")[0] != type_:
        res.rejected.append(f"{label}: id prefix does not match type {type_!r}")
        return
    existing_id = None
    if id_ and idx.get(layer, id_):
        existing_id = id_
    if not existing_id:
        existing_id = idx.find(layer, type_, [name] + [str(a) for a in v.as_list(fm.get("aliases"))])
    if not existing_id and not id_:
        id_ = v.make_id(type_, name)
        if idx.get(layer, id_):
            existing_id = id_

    if existing_id:
        ex = idx.get(layer, existing_id)
        efm = dict(ex.fm)
        changed = False
        for k in ("aliases", "tags", "related", "based_on", "exits", "participants", "leads_to"):
            if k in fm:
                merged = _union(efm.get(k), fm.get(k))
                if merged != v.as_list(efm.get(k)):
                    efm[k] = merged
                    changed = True
        if name != ex.name and v.norm_name(name) not in {v.norm_name(str(a)) for a in v.as_list(efm.get("aliases"))}:
            efm["aliases"] = _union(efm.get("aliases"), [name])
            changed = True
        if layer == "canon":
            ms = v.merge_sources(efm.get("sources"), fm.get("sources"))
            if ms != efm.get("sources"):
                efm["sources"] = ms
                changed = True
        if fm.get("summary_replace") and fm.get("summary") and fm["summary"] != efm.get("summary"):
            efm["summary"] = fm["summary"]
            changed = True
        elif not efm.get("summary") and fm.get("summary"):
            efm["summary"] = fm["summary"]
            changed = True
        conflict_lines = []
        cite = _first_citation(body, fm) if layer == "canon" else ""
        for k, val in fm.items():
            if k in STRUCTURAL or k in v.LIST_FIELDS or val in (None, "", []):
                continue
            if k not in efm or efm[k] in (None, ""):
                efm[k] = val
                changed = True
            elif efm[k] != val:
                conflict_lines.append(f"- Sources disagree on `{k}`: kept `{efm[k]}`; this source gives `{val}`."
                                      + (f" {cite}" if cite else ""))
        new_body, added = merge_body(type_, ex.body, body)
        if conflict_lines:
            new_body, n2 = merge_body(type_, new_body, "## Notes\n" + "\n".join(conflict_lines))
            added += n2
        if changed or added:
            ex.path.write_text(v.dump_document(efm, new_body), encoding="utf-8")
            ex.fm, ex.body = efm, new_body
            idx.add(ex)
            res.updated.append(existing_id)
        else:
            res.unchanged.append(existing_id)
        return

    # create
    if not fm.get("summary"):
        res.rejected.append(f"{label}: new entity needs a summary")
        return
    near = idx.near(layer, type_, name)
    fm["id"] = id_
    fm.pop("summary_replace", None)
    path = v.entity_path(root, layer, id_)
    path.parent.mkdir(parents=True, exist_ok=True)
    body_out, _ = merge_body(type_, "", body)
    path.write_text(v.dump_document(fm, body_out), encoding="utf-8")
    ent = v.Entity(path, fm, body_out)
    idx.add(ent)
    res.created.append(id_)
    if near:
        res.review.append(f"{id_} may duplicate {', '.join(near)}")


def _unresolved(vault: v.Vault, ids: list[str]) -> dict[str, list[str]]:
    known = vault.all_ids()
    out: dict[str, list[str]] = {}
    by = {e.id: e for e in vault.entities}
    for id_ in ids:
        e = by.get(id_)
        if not e:
            continue
        for _, t in e.refs():
            if t not in known:
                out.setdefault(t, []).append(id_)
        for t in v.wikilinks_in(e.body):
            if t not in known:
                out.setdefault(t, []).append(id_)
    return {k: sorted(set(vs)) for k, vs in sorted(out.items())}


def upsert_files(root: Path, files: list[Path], default_layer: str = "canon") -> Result:
    vault = v.load_vault(root)
    idx = Index.build(vault)
    res = Result()
    for f in files:
        try:
            frags = parse_fragments(Path(f).read_text(encoding="utf-8"))
        except v.FormatError as e:
            res.rejected.append(f"{f}: {e}")
            continue
        if not frags:
            res.rejected.append(f"{f}: no fragments found (each needs --- frontmatter with type and name)")
        for fm, body in frags:
            upsert_one(Path(root), idx, fm, body, default_layer, res)
    res.created = list(dict.fromkeys(res.created))
    res.updated = [x for x in dict.fromkeys(res.updated) if x not in res.created]
    res.unchanged = [x for x in dict.fromkeys(res.unchanged) if x not in res.created and x not in res.updated]
    vault = v.load_vault(root)
    idx = Index.build(vault)
    known = vault.all_ids()
    touched = set(res.created + res.updated)
    for e in vault.entities:
        if e.id in touched:
            _fix_refs(e, idx, known)
    vault = v.load_vault(root)
    res.unresolved = _unresolved(vault, res.created + res.updated)
    review_log = Path(root) / ".ingest" / "review.md"
    if res.review:
        review_log.parent.mkdir(parents=True, exist_ok=True)
        with review_log.open("a", encoding="utf-8") as fh:
            for r in res.review:
                fh.write(f"- {r}\n")
    return res


def merge_duplicate(root: Path, src_id: str, dst_id: str, layer: str = "canon") -> dict:
    """Fold entity src into dst, delete src, and repoint every reference to it.

    The one sanctioned way for a tool to remove a canon file: undoing a duplicate
    that ingestion itself created.
    """
    vault = v.load_vault(root)
    by = vault.by_id(layer)
    if src_id not in by or dst_id not in by:
        raise ValueError(f"both ids must exist in {layer}/: {src_id!r}, {dst_id!r}")
    src, dst = by[src_id], by[dst_id]
    if src.type != dst.type:
        raise ValueError("can only merge entities of the same type")
    frag = {k: val for k, val in src.fm.items() if k not in ("id", "summary")}
    frag["id"] = dst_id
    frag["name"] = dst.name
    idx = Index.build(vault)
    res = Result()
    upsert_one(Path(root), idx, frag, src.body, layer, res)
    # keep the duplicate's name as an alias
    fm, body = v.read_doc(dst.path)
    if v.norm_name(src.name) != v.norm_name(dst.name):
        fm["aliases"] = _union(fm.get("aliases"), [src.name])
        dst.path.write_text(v.dump_document(fm, body), encoding="utf-8")
    src.path.unlink()

    repointed = []
    link_re = re.compile(r"\[\[" + re.escape(src_id) + r"(?=[\]|#])")
    for e in v.load_vault(root).entities + vault.notes + vault.sessions:
        if not e.path.exists():
            continue
        efm, ebody = v.read_doc(e.path)
        changed = False
        for f, val in list(efm.items()):
            if isinstance(val, str) and val == src_id:
                efm[f] = dst_id
                changed = True
            elif isinstance(val, list) and src_id in val:
                efm[f] = list(dict.fromkeys(dst_id if x == src_id else x for x in val))
                changed = True
        new_body = link_re.sub("[[" + dst_id, ebody)
        if changed or new_body != ebody:
            e.path.write_text(v.dump_document(efm, new_body), encoding="utf-8")
            repointed.append(str(e.path.relative_to(root)))
    review = Path(root) / ".ingest" / "review.md"
    if review.exists():
        keep = [l for l in review.read_text(encoding="utf-8").splitlines() if src_id not in l]
        review.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    return {"merged": src_id, "into": dst_id, "repointed": repointed}
