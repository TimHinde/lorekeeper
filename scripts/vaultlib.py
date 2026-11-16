"""Shared vault model: constants from spec/VAULT.md, parsing, writing and loading.

Everything here is deterministic. Nothing calls an LLM.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FORMAT_VERSION = 1

TYPES = ["npc", "location", "faction", "creature", "item", "scene", "lore", "hook"]
ENTITY_LAYERS = ["canon", "ideas"]
LAYERS = ["canon", "table", "ideas"]
THREATS = ["trivial", "low", "mid", "high", "boss"]
IDEA_STATUSES = ["draft", "used", "discarded"]
NPC_STATUSES = ["alive", "dead", "missing", "unknown"]
VISIBILITY = ["gm", "player-safe"]
SOURCE_KINDS = ["adventure", "setting", "bestiary", "rulebook", "supplement", "other"]

SECTIONS = {
    "npc": ["Description", "Wants", "Secrets", "Relationships", "In play", "Stat block"],
    "location": ["Description", "Features", "Occupants", "Secrets", "Exits", "Read-aloud"],
    "faction": ["Description", "Goals", "Members", "Resources", "Secrets"],
    "creature": ["Description", "Behaviour", "Tactics", "Stat block"],
    "item": ["Description", "Properties", "History", "Stat block"],
    "scene": ["Setup", "Read-aloud", "What happens", "Outcomes", "Mechanics"],
    "lore": ["Summary", "Detail"],
    "hook": ["The hook", "Truth behind it", "Where it leads"],
}

# Frontmatter fields that hold entity IDs, per type. "*" applies to every type.
REF_FIELDS = {
    "*": ["related", "based_on"],
    "npc": ["location", "faction"],
    "location": ["parent", "exits"],
    "faction": ["base", "leader"],
    "item": ["holder", "location"],
    "scene": ["location", "participants"],
    "hook": ["leads_to", "given_by"],
}

LIST_FIELDS = {"aliases", "tags", "related", "based_on", "exits", "participants", "leads_to", "sources"}

# Canonical key order for written frontmatter. Unknown keys go after these.
KEY_ORDER = [
    "id", "type", "name", "layer", "summary", "aliases", "tags", "system",
    "role", "kind", "location", "parent", "faction", "base", "leader", "holder",
    "status", "threat", "chapter", "participants", "exits", "leads_to", "given_by",
    "visibility", "related", "based_on", "generated", "sources",
]

SUMMARY_MAX = 160

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ID_RE = re.compile(r"^(?P<type>[a-z]+)/(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$")
# [drowned-abbey p.47] or [drowned-abbey pp.12–14] (en dash or hyphen)
CITATION_RE = re.compile(r"\[(?P<src>[a-z0-9]+(?:-[a-z0-9]+)*) (?:p\.(?P<p>\d+)|pp\.(?P<a>\d+)[–-](?P<b>\d+))\]")
WIKILINK_RE = re.compile(r"\[\[(?P<target>[^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE_RE = re.compile(r"^(```+|~~~+)(.*)$")


# ── identity ────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text) or "untitled"


def make_id(type_: str, name: str) -> str:
    """IDs drop a leading article: "The Brine Choir" -> faction/brine-choir."""
    slug = re.sub(r"^(the|a|an)-(?=.)", "", slugify(name))
    return f"{type_}/{slug}"


def norm_name(text: str) -> str:
    """Name form used for matching: lowercase, no articles or punctuation."""
    s = slugify(text).replace("-", " ")
    s = re.sub(r"^(the|a|an) ", "", s)
    return s.strip()


def today() -> str:
    return _dt.date.today().isoformat()


# ── documents ───────────────────────────────────────────────────────────────

class FormatError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise FormatError("missing frontmatter (file must start with ---)")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise FormatError("first line must be exactly ---")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw = "\n".join(lines[1:i])
            try:
                fm = yaml.safe_load(raw) or {}
            except yaml.YAMLError as e:
                raise FormatError(f"frontmatter is not valid YAML: {e}") from e
            if not isinstance(fm, dict):
                raise FormatError("frontmatter must be a mapping")
            body = "\n".join(lines[i + 1:])
            return fm, body.lstrip("\n")
    raise FormatError("frontmatter is not closed with ---")


def _yaml_scalar_safe(fm: dict) -> dict:
    """Dates from YAML come back as date objects; keep them as ISO strings."""
    out = {}
    for k, v in fm.items():
        if isinstance(v, (_dt.date, _dt.datetime)):
            v = v.isoformat()
        out[k] = v
    return out


class _Dumper(yaml.SafeDumper):
    pass


def _str_rep(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_Dumper.add_representer(str, _str_rep)


def dump_frontmatter(fm: dict) -> str:
    ordered = {k: fm[k] for k in KEY_ORDER if k in fm and fm[k] not in (None, [], "")}
    for k, v in fm.items():
        if k not in ordered and v not in (None, [], ""):
            ordered[k] = v
    text = yaml.dump(ordered, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=None, width=100)
    return f"---\n{text}---\n"


def dump_document(fm: dict, body: str) -> str:
    body = body.strip("\n")
    return dump_frontmatter(fm) + ("\n" + body + "\n" if body else "")


# ── body sections ───────────────────────────────────────────────────────────

@dataclass
class Section:
    heading: str            # "" for text before the first ## heading
    lines: list[str] = field(default_factory=list)


def parse_sections(body: str) -> list[Section]:
    sections = [Section("")]
    in_fence = None
    for line in body.split("\n"):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)[:3]
            if in_fence is None:
                in_fence = marker
            elif line.strip().startswith(in_fence) and line.strip().strip(in_fence[0]) == "":
                in_fence = None
        if in_fence is None and line.startswith("## ") and not m:
            sections.append(Section(line[3:].strip()))
        else:
            sections[-1].lines.append(line)
    for s in sections:
        while s.lines and not s.lines[-1].strip():
            s.lines.pop()
        while s.lines and not s.lines[0].strip():
            s.lines.pop(0)
    if not sections[0].lines:
        sections.pop(0)
    return sections


def render_sections(sections: list[Section]) -> str:
    parts = []
    for s in sections:
        chunk = "\n".join(s.lines).strip("\n")
        if s.heading:
            parts.append(f"## {s.heading}\n" + (chunk + "\n" if chunk else ""))
        elif chunk:
            parts.append(chunk + "\n")
    return "\n".join(parts).rstrip("\n") + "\n" if parts else ""


@dataclass
class Block:
    kind: str               # bullet | para | fence | callout | table | heading
    lines: list[str]
    start: int              # 1-based line number within the body
    info: str = ""          # fence info string, or callout type

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


_BULLET_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
_CALLOUT_RE = re.compile(r"^>\s*\[!(?P<kind>[a-z-]+)\]", re.I)


def iter_blocks(lines: list[str], offset: int = 1) -> list[Block]:
    """Split section lines into content blocks. A nested bullet is its own block."""
    blocks: list[Block] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = FENCE_RE.match(line.strip())
        if m:
            marker = m.group(1)
            j = i + 1
            while j < n and not lines[j].strip().startswith(marker[:3]):
                j += 1
            blocks.append(Block("fence", lines[i:j + 1], offset + i, m.group(2).strip()))
            i = j + 1
            continue
        if line.startswith(">"):
            j = i
            while j < n and lines[j].startswith(">"):
                j += 1
            cm = _CALLOUT_RE.match(line)
            blocks.append(Block("callout", lines[i:j], offset + i, cm.group("kind").lower() if cm else ""))
            i = j
            continue
        if line.lstrip().startswith("|"):
            j = i
            while j < n and lines[j].lstrip().startswith("|"):
                j += 1
            blocks.append(Block("table", lines[i:j], offset + i))
            i = j
            continue
        if line.startswith("#"):
            blocks.append(Block("heading", [line], offset + i))
            i += 1
            continue
        bm = _BULLET_RE.match(line)
        if bm:
            indent = len(bm.group(1))
            j = i + 1
            # continuation lines: indented deeper than the marker and not a new bullet
            while j < n and lines[j].strip() and not _BULLET_RE.match(lines[j]) \
                    and (len(lines[j]) - len(lines[j].lstrip())) > indent:
                j += 1
            blocks.append(Block("bullet", lines[i:j], offset + i))
            i = j
            continue
        j = i + 1
        while j < n and lines[j].strip() and not _BULLET_RE.match(lines[j]) \
                and not lines[j].startswith((">", "#", "|")) and not FENCE_RE.match(lines[j].strip()):
            j += 1
        blocks.append(Block("para", lines[i:j], offset + i))
        i = j
    return blocks


def norm_block(text: str) -> str:
    """Normalised block text for duplicate detection."""
    t = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", text)
    t = CITATION_RE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t.rstrip(".")


def fence_attrs(info: str) -> dict:
    """```statblock system=dnd5e source=x page=62  →  {lang: statblock, system: dnd5e, ...}"""
    parts = info.split()
    out = {"lang": parts[0] if parts else ""}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k] = v
    return out


def citations_in(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITATION_RE.finditer(text):
        if m.group("p"):
            p = int(m.group("p"))
            out.append((m.group("src"), p, p))
        else:
            out.append((m.group("src"), int(m.group("a")), int(m.group("b"))))
    return out


def wikilinks_in(text: str) -> list[str]:
    return [m.group("target").strip() for m in WIKILINK_RE.finditer(text)]


def body_citations(body: str) -> list[tuple[str, int, int]]:
    """All citations in a body, including statblock fence attributes."""
    cites = citations_in(body)
    for line in body.split("\n"):
        m = FENCE_RE.match(line.strip())
        if m and m.group(2).strip():
            a = fence_attrs(m.group(2))
            if "source" in a and a.get("page", "").isdigit():
                p = int(a["page"])
                cites.append((a["source"], p, p))
    return cites


def sources_from_citations(cites) -> list[dict]:
    pages: dict[str, set[int]] = {}
    for src, a, b in cites:
        rng = range(a, b + 1) if b - a <= 20 else (a, b)
        pages.setdefault(src, set()).update(rng)
    return [{"source": s, "pages": sorted(p)} for s, p in sorted(pages.items())]


def merge_sources(a: list | None, b: list | None) -> list[dict]:
    pages: dict[str, set[int]] = {}
    for lst in (a or [], b or []):
        for entry in lst:
            if isinstance(entry, dict) and entry.get("source"):
                ps = entry.get("pages") or []
                if isinstance(ps, int):
                    ps = [ps]
                pages.setdefault(str(entry["source"]), set()).update(int(p) for p in ps)
    return [{"source": s, "pages": sorted(p)} for s, p in sorted(pages.items())]


def as_list(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return v
    return [v]


# ── vault on disk ───────────────────────────────────────────────────────────

@dataclass
class Entity:
    path: Path
    fm: dict
    body: str

    @property
    def id(self) -> str:
        return str(self.fm.get("id", ""))

    @property
    def type(self) -> str:
        return str(self.fm.get("type", ""))

    @property
    def layer(self) -> str:
        return str(self.fm.get("layer", ""))

    @property
    def name(self) -> str:
        return str(self.fm.get("name", ""))

    def refs(self) -> list[tuple[str, str]]:
        """(field, target id) for every frontmatter reference."""
        out = []
        for f in REF_FIELDS["*"] + REF_FIELDS.get(self.type, []):
            for v in as_list(self.fm.get(f)):
                if isinstance(v, str):
                    out.append((f, v))
        return out


@dataclass
class Vault:
    root: Path
    meta: dict
    entities: list[Entity]
    sources: dict[str, dict]
    sessions: list[Entity]
    notes: list[Entity]
    load_errors: list[tuple[Path, str]]

    def by_id(self, layer: str | None = None) -> dict[str, Entity]:
        return {e.id: e for e in self.entities if layer is None or e.layer == layer}

    def all_ids(self) -> set[str]:
        return {e.id for e in self.entities}


def is_vault(path: Path) -> bool:
    return (path / "vault.yaml").exists()


def find_vault(start: Path) -> Path | None:
    start = start.resolve()
    for p in [start, *start.parents]:
        if is_vault(p):
            return p
    return None


def read_doc(path: Path) -> tuple[dict, str]:
    fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    return _yaml_scalar_safe(fm), body


def load_vault(root: Path) -> Vault:
    root = Path(root)
    meta = yaml.safe_load((root / "vault.yaml").read_text(encoding="utf-8")) or {}
    entities, sessions, notes, errors = [], [], [], []
    sources: dict[str, dict] = {}

    for layer in ENTITY_LAYERS:
        base = root / layer
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.md")):
            try:
                fm, body = read_doc(p)
            except (FormatError, UnicodeDecodeError) as e:
                errors.append((p, str(e)))
                continue
            entities.append(Entity(p, fm, body))

    for p in sorted((root / "sources").glob("*.md")) if (root / "sources").exists() else []:
        try:
            fm, body = read_doc(p)
        except FormatError as e:
            errors.append((p, str(e)))
            continue
        fm["_path"] = p
        fm["_body"] = body
        sources[str(fm.get("id", p.stem))] = fm

    for sub, bucket in (("sessions", sessions), ("notes", notes)):
        d = root / "table" / sub
        for p in sorted(d.glob("*.md")) if d.exists() else []:
            try:
                fm, body = read_doc(p)
            except FormatError as e:
                errors.append((p, str(e)))
                continue
            bucket.append(Entity(p, fm, body))

    return Vault(root, meta, entities, sources, sessions, notes, errors)


def entity_path(root: Path, layer: str, id_: str) -> Path:
    m = ID_RE.match(id_)
    if not m:
        raise FormatError(f"bad id {id_!r}")
    return root / layer / m.group("type") / f"{m.group('slug')}.md"


def init_vault(root: Path, name: str, systems: list[str] | None = None) -> Path:
    root = Path(root)
    if is_vault(root):
        return root
    root.mkdir(parents=True, exist_ok=True)
    meta = {"format": FORMAT_VERSION, "name": name, "systems": systems or [], "created": today()}
    (root / "vault.yaml").write_text(yaml.dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    for layer in ENTITY_LAYERS:
        for t in TYPES:
            (root / layer / t).mkdir(parents=True, exist_ok=True)
    for d in ("sources", "table/sessions", "table/notes", "_index", ".ingest"):
        (root / d).mkdir(parents=True, exist_ok=True)
    party = root / "table" / "party.md"
    if not party.exists():
        party.write_text("# Party\n\n## Characters\n\n## What they know\n\n## What they carry\n\n## Who they have met\n",
                         encoding="utf-8")
    return root


# ── ingest manifest ─────────────────────────────────────────────────────────

def manifest_path(root: Path) -> Path:
    return Path(root) / ".ingest" / "manifest.json"


def read_manifest(root: Path) -> dict:
    p = manifest_path(root)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"sources": {}}


def write_manifest(root: Path, data: dict) -> None:
    p = manifest_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
