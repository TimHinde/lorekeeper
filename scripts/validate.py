"""Check a vault against spec/VAULT.md section 10."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

import vaultlib as v


@dataclass
class Issue:
    level: str      # error | warning
    path: str
    message: str
    line: int | None = None

    def __str__(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.level.upper():7} {loc}  {self.message}"


def _rel(vault: v.Vault, p: Path) -> str:
    try:
        return str(Path(p).relative_to(vault.root))
    except ValueError:
        return str(p)


def _check_citations(vault, e, issues, rel, page_counts):
    """Every content block in a canon body must carry a citation."""
    sections = v.parse_sections(e.body)
    # body line numbers: count from the start of the body
    body_lines = e.body.split("\n")
    cursor = 0
    for s in sections:
        # locate the section's first line in the body to report useful line numbers
        if s.heading:
            for k in range(cursor, len(body_lines)):
                if body_lines[k].startswith("## ") and body_lines[k][3:].strip() == s.heading:
                    cursor = k + 1
                    break
        for b in v.iter_blocks(s.lines, offset=cursor + 1):
            if b.kind == "heading":
                continue
            if b.kind == "fence":
                attrs = v.fence_attrs(b.info)
                if attrs["lang"] == "statblock":
                    missing = [k for k in ("system", "source", "page") if k not in attrs]
                    if missing:
                        issues.append(Issue("error", rel, f"statblock fence lacks {', '.join(missing)}", b.start))
                continue
            if b.kind == "callout" and b.info == "conflict":
                for line in b.lines[1:]:
                    t = line.lstrip("> ").strip()
                    if t and not v.citations_in(t):
                        issues.append(Issue("error", rel, f"uncited line in conflict callout: {t[:60]!r}", b.start))
                continue
            if b.kind == "callout":
                if not v.citations_in(b.lines[0]) and not v.citations_in(b.text):
                    issues.append(Issue("error", rel, f"uncited {b.info or 'quote'} block", b.start))
                continue
            text = b.text
            if not v.citations_in(text):
                issues.append(Issue("error", rel, f"uncited fact: {text.strip()[:70]!r}", b.start))
    for src, a, b in v.body_citations(e.body):
        if src not in vault.sources:
            issues.append(Issue("error", rel, f"cites unknown source {src!r}"))
            continue
        n = page_counts.get(src)
        if n and (a < 1 or b > n or a > b):
            issues.append(Issue("error", rel, f"cites {src} page {a}{'–' + str(b) if b != a else ''}, "
                                              f"outside 1–{n}"))


def validate(root: Path) -> list[Issue]:
    vault = v.load_vault(root)
    issues: list[Issue] = []

    if vault.meta.get("format") != v.FORMAT_VERSION:
        issues.append(Issue("error", "vault.yaml", f"format must be {v.FORMAT_VERSION}"))

    for p, msg in vault.load_errors:
        issues.append(Issue("error", _rel(vault, p), msg))

    page_counts = {}
    for sid, s in vault.sources.items():
        rel = _rel(vault, s["_path"])
        if s["_path"].stem != sid:
            issues.append(Issue("error", rel, f"source id {sid!r} does not match file name"))
        if s.get("kind") not in v.SOURCE_KINDS:
            issues.append(Issue("warning", rel, f"source kind {s.get('kind')!r} not one of {v.SOURCE_KINDS}"))
        try:
            page_counts[sid] = int(s.get("pages") or 0)
        except (TypeError, ValueError):
            issues.append(Issue("error", rel, "pages must be a number"))

    canon = vault.by_id("canon")
    ideas = vault.by_id("ideas")
    seen: dict[tuple[str, str], Path] = {}

    for e in vault.entities:
        rel = _rel(vault, e.path)
        fm = e.fm
        for f in ("id", "type", "name", "layer", "summary"):
            if not fm.get(f):
                issues.append(Issue("error", rel, f"missing required field {f!r}"))
        if e.type and e.type not in v.TYPES:
            issues.append(Issue("error", rel, f"unknown type {e.type!r}"))
        if e.layer and e.layer not in v.ENTITY_LAYERS:
            issues.append(Issue("error", rel, f"layer {e.layer!r} not allowed for entities"))
        layer_dir = e.path.relative_to(vault.root).parts[0]
        if e.layer and e.layer != layer_dir:
            issues.append(Issue("error", rel, f"layer {e.layer!r} but file is under {layer_dir}/"))
        if e.id:
            m = v.ID_RE.match(e.id)
            if not m:
                issues.append(Issue("error", rel, f"malformed id {e.id!r} (want type/slug)"))
            else:
                if m.group("type") != e.type:
                    issues.append(Issue("error", rel, f"id prefix {m.group('type')!r} does not match type {e.type!r}"))
                expected = v.entity_path(vault.root, layer_dir, e.id)
                if expected.resolve() != e.path.resolve():
                    issues.append(Issue("error", rel, f"id {e.id!r} should live at {_rel(vault, expected)}"))
            key = (layer_dir, e.id)
            if key in seen:
                issues.append(Issue("error", rel, f"duplicate id {e.id!r} (also {_rel(vault, seen[key])})"))
            seen[key] = e.path

        summary = str(fm.get("summary") or "")
        if len(summary) > v.SUMMARY_MAX:
            issues.append(Issue("warning", rel, f"summary is {len(summary)} chars (max {v.SUMMARY_MAX})"))

        if fm.get("threat") and fm["threat"] not in v.THREATS:
            issues.append(Issue("error", rel, f"threat {fm['threat']!r} not one of {v.THREATS}"))
        if fm.get("visibility") and fm["visibility"] not in v.VISIBILITY:
            issues.append(Issue("error", rel, f"visibility {fm['visibility']!r} not one of {v.VISIBILITY}"))
        if e.type == "npc" and fm.get("status") and fm["status"] not in v.NPC_STATUSES:
            issues.append(Issue("error", rel, f"npc status {fm['status']!r} not one of {v.NPC_STATUSES}"))

        if e.layer == "canon":
            if not fm.get("sources"):
                issues.append(Issue("error", rel, "canon entity has no sources"))
            for s in v.as_list(fm.get("sources")):
                if not isinstance(s, dict) or s.get("source") not in vault.sources:
                    issues.append(Issue("error", rel, f"sources entry {s!r} names no known source"))
            _check_citations(vault, e, issues, rel, page_counts)
        elif e.layer == "ideas":
            if fm.get("sources"):
                issues.append(Issue("error", rel, "ideas entity must not have sources"))
            if fm.get("status") not in v.IDEA_STATUSES:
                issues.append(Issue("error", rel, f"ideas status must be one of {v.IDEA_STATUSES}"))
            if not fm.get("generated"):
                issues.append(Issue("error", rel, "ideas entity lacks generated date"))

        for field, target in e.refs():
            if target not in canon and target not in ideas:
                issues.append(Issue("error", rel, f"{field} -> {target!r} does not exist"))
            elif e.layer == "canon" and target not in canon:
                issues.append(Issue("error", rel, f"canon {field} -> {target!r} exists only in ideas/"))
        links = v.wikilinks_in(e.body)
        for target in links:
            if target not in canon and target not in ideas:
                issues.append(Issue("warning", rel, f"link [[{target}]] does not resolve"))

    for n in vault.notes:
        rel = _rel(vault, n.path)
        about = n.fm.get("about")
        if not about:
            issues.append(Issue("error", rel, "table note lacks 'about'"))
        elif about not in canon and about not in ideas:
            issues.append(Issue("error", rel, f"about -> {about!r} does not exist"))
    for s in vault.sessions:
        rel = _rel(vault, s.path)
        for f in ("date", "number"):
            if not s.fm.get(f):
                issues.append(Issue("error", rel, f"session lacks {f!r}"))
        for f in ("present", "changed"):
            for t in v.as_list(s.fm.get(f)):
                if t not in canon and t not in ideas:
                    issues.append(Issue("warning", rel, f"{f} -> {t!r} does not exist"))

    # isolation and near-duplicate warnings
    inbound: dict[str, int] = {}
    for e in vault.entities:
        for _, t in e.refs():
            inbound[t] = inbound.get(t, 0) + 1
        for t in v.wikilinks_in(e.body):
            inbound[t] = inbound.get(t, 0) + 1
    for e in vault.entities:
        outbound = e.refs() or v.wikilinks_in(e.body)
        if not outbound and not inbound.get(e.id):
            issues.append(Issue("warning", _rel(vault, e.path), "no links in or out"))

    for layer in v.ENTITY_LAYERS:
        by_type: dict[str, list[v.Entity]] = {}
        for e in vault.entities:
            if e.layer == layer:
                by_type.setdefault(e.type, []).append(e)
        for t, ents in by_type.items():
            names = [(v.norm_name(e.name), e) for e in ents]
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    a, b = names[i][0], names[j][0]
                    shorter, longer = sorted((a, b), key=len)
                    contained = len(shorter) >= 4 and re.search(rf"\b{re.escape(shorter)}\b", longer)
                    if a and b and (a == b or contained or difflib.SequenceMatcher(None, a, b).ratio() > 0.88):
                        issues.append(Issue("warning", _rel(vault, names[j][1].path),
                                            f"name close to {names[i][1].id!r}; possible duplicate"))
    return issues


def run(root: Path, strict: bool = False, quiet: bool = False) -> int:
    issues = validate(root)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if not quiet:
        for i in sorted(issues, key=lambda i: (i.level != "error", i.path, i.line or 0)):
            print(i)
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (strict and warnings):
        return 1
    return 0
