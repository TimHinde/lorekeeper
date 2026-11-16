"""PDF probing and layout-aware text extraction. No LLM calls.

Grew out of Tome's pdf_tools.py: same PyMuPDF base, plus reading order for
multi-column pages, boxed-text detection, per-page quality flags, page images
for pages whose text layer cannot be trusted, and chunk plans that respect a
page budget.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

import vaultlib as v

DEFAULT_MAX_PAGES = 15
SOFT = "\u00ad"
_SOFT_WORD = re.compile(r"(\w+)\u00ad(\w+)")


def _resolve_hyphens(text: str) -> str:
    """Undo line-break hyphenation. Keep the hyphen only when the chunk itself spells
    the word with one elsewhere (tide-worshippers) and never without (sur-rounded)."""
    lower = text.lower()

    def repl(m):
        a, b = m.group(1), m.group(2)
        joined, hyph = (a + b).lower(), f"{a}-{b}".lower()
        if hyph in lower and joined not in lower:
            return f"{a}-{b}"
        return a + b
    return _SOFT_WORD.sub(repl, text)
SKIP_TITLES = re.compile(
    r"\b(credits|table of contents|contents|index|legal|licen[cs]e|open game|ogl|"
    r"back cover|front cover|cover|advert\w*|acknowledg\w*|playtest\w*|kickstarter|backers?)\b", re.I)

KIND_KEYWORDS = {
    "adventure": ["adventure", "encounter", "scene", "act ", "part ", "hook", "quest", "dungeon", "mission",
                  "scenario", "module", "run the", "running the", "conclusion", "aftermath"],
    "setting": ["gazetteer", "region", "world", "histor", "religion", "faction", "culture", "setting",
                "atlas", "nations", "geography", "cosmology", "pantheon", "cities", "people"],
    "bestiary": ["monster", "bestiary", "creature", "beast", "adversar", "foes", "enemies", "threats",
                 "denizens", "npcs and"],
    "rulebook": ["rules", "combat", "character creation", "skills", "equipment", "conditions", "magic",
                 "advancement", "playing the game", "core mechanic"],
    "supplement": ["options", "class", "playbook", "spells", "feats", "backgrounds", "ancestr", "subclass",
                   "archetype", "careers"],
}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


# ── probe ───────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    name: str
    pages: list[int]                 # [first, last], 1-based inclusive
    status: str = "pending"          # pending | skip | done | failed
    entities: int | None = None

    def as_dict(self) -> dict:
        d = {"name": self.name, "pages": self.pages, "status": self.status}
        if self.entities is not None:
            d["entities"] = self.entities
        return d


def guess_kind(toc_titles: list[str], first_pages_text: str) -> str:
    blob = (" ".join(toc_titles) + " " + first_pages_text[:6000]).lower()
    scores = {k: sum(blob.count(w) for w in words) for k, words in KIND_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def _split_even(name: str, a: int, b: int, max_pages: int) -> list[Chunk]:
    total = b - a + 1
    parts = math.ceil(total / max_pages)
    size = math.ceil(total / parts)
    out = []
    for k in range(parts):
        s = a + k * size
        e = min(b, s + size - 1)
        out.append(Chunk(f"{name} ({k + 1}/{parts})", [s, e]))
    return out


def _plan_range(toc: list[tuple[int, str, int]], level: int, a: int, b: int, max_pages: int,
                name: str) -> list[Chunk]:
    """Chunk pages a..b, using TOC entries deeper than `level` that fall inside the range."""
    if b - a + 1 <= max_pages:
        return [Chunk(name, [a, b])]
    children = [(lv, t, p) for lv, t, p in toc if lv == level + 1 and a <= p <= b]
    if not children:
        deeper = [(lv, t, p) for lv, t, p in toc if lv > level + 1 and a <= p <= b]
        if deeper:
            min_lv = min(lv for lv, _, _ in deeper)
            children = [(lv, t, p) for lv, t, p in deeper if lv == min_lv]
            level = min_lv - 1
    if not children:
        return _split_even(name, a, b, max_pages)
    out: list[Chunk] = []
    if children[0][2] > a:
        out += _plan_range(toc, level + 1, a, children[0][2] - 1, max_pages, f"{name}: opening")
    for k, (lv, title, p) in enumerate(children):
        end = children[k + 1][2] - 1 if k + 1 < len(children) else b
        end = max(p, end)
        out += _plan_range(toc, lv, p, end, max_pages, f"{name}: {title.strip()}")
    return out


def _merge_small(chunks: list[Chunk], max_pages: int, min_pages: int = 3) -> list[Chunk]:
    """Fold chunks shorter than min_pages into a neighbour while the result fits the budget."""
    out: list[Chunk] = []
    names: list[list[str]] = []
    for c in chunks:
        if out and c.status == out[-1].status == "pending":
            prev = out[-1]
            prev_len = prev.pages[1] - prev.pages[0] + 1
            cur_len = c.pages[1] - c.pages[0] + 1
            if (prev_len < min_pages or cur_len < min_pages) and \
                    c.pages[1] - prev.pages[0] + 1 <= max_pages and prev.pages[1] + 1 >= c.pages[0]:
                prev.pages = [prev.pages[0], c.pages[1]]
                names[-1].append(c.name)
                continue
        out.append(c)
        names.append([c.name])
    for c, ns in zip(out, names):
        if len(ns) == 2:
            c.name = f"{ns[0]} + {ns[1]}"
        elif len(ns) > 2:
            c.name = f"{ns[0]} … {ns[-1]}"
    return out


def plan_chunks(doc: pymupdf.Document, max_pages: int = DEFAULT_MAX_PAGES) -> list[Chunk]:
    n = doc.page_count
    toc = [(lv, t, p) for lv, t, p in doc.get_toc(simple=True) if 1 <= p <= n]
    if not toc:
        return _split_even("Pages", 1, n, max_pages) if n > max_pages else [Chunk("All pages", [1, n])]
    top_level = min(lv for lv, _, _ in toc)
    tops = [(lv, t, p) for lv, t, p in toc if lv == top_level]
    # a lone root entry (the book's own title) says nothing; plan from its children
    while len(tops) == 1 and any(lv > top_level for lv, _, _ in toc):
        top_level = min(lv for lv, _, _ in toc if lv > top_level)
        tops = [(lv, t, p) for lv, t, p in toc if lv == top_level]
    # collapse entries that share a start page (keep the first title)
    dedup = []
    for e in tops:
        if dedup and dedup[-1][2] == e[2]:
            continue
        dedup.append(e)
    tops = dedup
    chunks: list[Chunk] = []
    if tops[0][2] > 1:
        chunks.append(Chunk("Front matter", [1, tops[0][2] - 1]))
    for k, (lv, title, p) in enumerate(tops):
        end = tops[k + 1][2] - 1 if k + 1 < len(tops) else n
        end = max(p, end)
        chunks += _plan_range(toc, lv, p, end, max_pages, title.strip())
    for c in chunks:
        if SKIP_TITLES.search(c.name.split(":")[0]) or c.name == "Front matter":
            c.status = "skip"
    return _merge_small(chunks, max_pages)


def text_layer_stats(doc: pymupdf.Document) -> dict:
    empty, image_only = [], []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        chars = len(page.get_text("text").strip())
        if chars < 30:
            empty.append(i + 1)
            if page.get_images(full=False):
                image_only.append(i + 1)
    return {"empty_pages": empty, "image_only_pages": image_only,
            "scanned": doc.page_count > 0 and len(image_only) / doc.page_count > 0.5}


def outline_markdown(doc: pymupdf.Document, chunks: list[Chunk]) -> str:
    toc = doc.get_toc(simple=True)
    lines = ["## Outline", ""]
    if toc:
        for lv, title, p in toc:
            lines.append(f"{'  ' * (lv - 1)}- {title.strip()} (p.{p})")
    else:
        lines.append("No table of contents in the PDF.")
    lines += ["", "## Chunk plan", ""]
    for k, c in enumerate(chunks, 1):
        lines.append(f"{k}. {c.name} — pp.{c.pages[0]}–{c.pages[1]}" + (" (skip)" if c.status == "skip" else ""))
    lines += ["", "## Chapter summaries", "", "<!-- Filled in during ingestion: one or two lines per chapter. -->", ""]
    return "\n".join(lines)


def probe(pdf_path: Path, vault_root: Path, source_id: str | None = None, kind: str | None = None,
          system: str | None = None, title: str | None = None, max_pages: int = DEFAULT_MAX_PAGES,
          replan: bool = False) -> dict:
    pdf_path = Path(pdf_path)
    doc = pymupdf.open(pdf_path)
    meta_title = (doc.metadata or {}).get("title") or ""
    title = title or meta_title.strip() or pdf_path.stem.replace("_", " ").replace("-", " ").strip()
    sid = source_id or v.slugify(title)[:48].strip("-")
    fhash = file_hash(pdf_path)
    toc_titles = [t for _, t, _ in doc.get_toc(simple=True)]
    first_text = "".join(doc.load_page(i).get_text("text") for i in range(min(6, doc.page_count)))
    kind = kind or guess_kind(toc_titles, first_text)
    stats = text_layer_stats(doc)

    manifest = v.read_manifest(vault_root)
    existing = manifest["sources"].get(sid)
    resumed = bool(existing and existing.get("file_hash") == fhash and not replan)
    if existing and existing.get("file_hash") != fhash:
        raise ValueError(f"source id {sid!r} already used for a different PDF; pass --id to choose another")
    if resumed:
        chunks = [Chunk(c["name"], c["pages"], c.get("status", "pending"), c.get("entities"))
                  for c in existing["chunks"]]
    else:
        chunks = plan_chunks(doc, max_pages)

    src_path = Path(vault_root) / "sources" / f"{sid}.md"
    src_path.parent.mkdir(parents=True, exist_ok=True)
    if src_path.exists():
        fm, body = v.read_doc(src_path)
    else:
        fm, body = {}, outline_markdown(doc, chunks)
    fm.update({"id": sid, "title": fm.get("title") or title, "kind": fm.get("kind") or kind,
               "pages": doc.page_count, "file_hash": fhash})
    if system or "system" not in fm:
        fm["system"] = system or fm.get("system") or "unknown"
    fm.setdefault("ingested", v.today())
    src_path.write_text(v.dump_document(fm, body), encoding="utf-8")

    entry = existing if resumed else {}
    entry.update({"file": pdf_path.name, "file_hash": fhash, "pages": doc.page_count,
                  "max_pages": max_pages, "chunks": [c.as_dict() for c in chunks]})
    entry.setdefault("flagged_pages", [])
    manifest["sources"][sid] = entry
    v.write_manifest(vault_root, manifest)

    return {
        "source": sid, "title": fm["title"], "kind": fm["kind"], "system": fm["system"],
        "pages": doc.page_count, "has_toc": bool(toc_titles), "resumed": resumed,
        "scanned": stats["scanned"], "image_only_pages": stats["image_only_pages"][:40],
        "chunks": [dict(index=k, **c.as_dict()) for k, c in enumerate(chunks, 1)],
        "source_file": str(src_path),
    }


# ── extraction ──────────────────────────────────────────────────────────────

@dataclass
class PageResult:
    page: int
    text: str
    flags: list[str] = field(default_factory=list)
    image: str | None = None


def _span_text(spans: list[dict]) -> str:
    """Join spans, wrapping a leading bold run in ** (catches 'Name. Description' entries)."""
    parts = [s["text"] for s in spans]
    text = "".join(parts)
    if not text.strip():
        return ""
    bold = [bool(s["flags"] & 16) or "bold" in s.get("font", "").lower() for s in spans]
    if bold[0] and not all(bold):
        k = 0
        while k < len(spans) and bold[k]:
            k += 1
        lead = "".join(parts[:k]).strip()
        rest = "".join(parts[k:])
        if lead and rest.strip():
            return f"**{lead}** {rest.strip()}"
    return text.strip()


def _join_lines(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():
            # mark the join; _resolve_hyphens decides later with the whole chunk in view
            out = out[:-1] + SOFT + ln
        elif out:
            out += " " + ln
        else:
            out = ln
    return out


def _body_size(pages_dicts: list[dict]) -> float:
    sizes = Counter()
    for d in pages_dicts:
        for b in d["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    sizes[round(s["size"], 1)] += len(s["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 10.0


def _boxes(page: pymupdf.Page) -> list[pymupdf.Rect]:
    area = page.rect.width * page.rect.height
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    if len(drawings) > 600:
        return []
    out = []
    for d in drawings:
        r = d.get("rect")
        if r is None:
            continue
        ra = r.width * r.height
        if 0.02 * area < ra < 0.7 * area and r.width > 60 and r.height > 30:
            out.append(pymupdf.Rect(r))
    return out


def _page_quality(text: str, has_images: bool, n_columns: int) -> list[str]:
    flags = []
    stripped = re.sub(r"<<[^>]*>>", "", text)
    body = re.sub(r"\s+", "", stripped)
    if len(body) < 40:
        flags.append("image-only page" if has_images else "almost no text")
        return flags
    if stripped.count("�") / max(1, len(body)) > 0.01:
        flags.append("unknown glyphs")
    letters = sum(c.isalpha() for c in body)
    if letters / len(body) < 0.55:
        flags.append("low letter ratio")
    words = stripped.split()
    if words and sum(len(w) > 25 for w in words) / len(words) > 0.03:
        flags.append("words run together")
    lines = [l for l in stripped.split("\n") if l.strip()]
    if lines and sum(len(l.strip()) <= 3 for l in lines) / len(lines) > 0.3:
        flags.append("fragmented lines")
    if n_columns >= 3:
        flags.append(f"{n_columns}-column layout")
    return flags


def extract_page(page: pymupdf.Page, body_size: float) -> tuple[str, int]:
    W, H = page.rect.width, page.rect.height
    d = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
    boxes = _boxes(page)
    items = []
    xs = []
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        x0, y0, x1, y1 = b["bbox"]
        line_texts, max_size = [], 0.0
        for l in b["lines"]:
            t = _span_text(l["spans"])
            if t:
                line_texts.append(t)
                max_size = max([max_size] + [s["size"] for s in l["spans"] if s["text"].strip()])
        if not line_texts:
            continue
        text = _join_lines(line_texts) if max_size < body_size * 1.2 else " ".join(line_texts)
        # running heads and page numbers in the margins
        if (y1 < H * 0.06 or y0 > H * 0.94) and (len(text) < 60 or text.strip().isdigit()):
            continue
        if max_size >= body_size * 1.6 and len(text) < 100:
            text = "# " + text
        elif max_size >= body_size * 1.2 and len(text) < 100:
            text = "## " + text
        rect = pymupdf.Rect(b["bbox"])
        boxed = any(bx.contains(rect) or (bx & rect).get_area() > 0.9 * rect.get_area() for bx in boxes)
        if boxed:
            text = "> " + text.replace("\n", "\n> ")
        width = x1 - x0
        if width > 0.6 * W:
            col = "full"
        else:
            col = "left" if (x0 + x1) / 2 < W / 2 else "right"
            xs.append(round(x0 / (W / 12)))
        items.append((y0, x0, col, text, boxed))

    items.sort(key=lambda it: (it[0], it[1]))
    ordered: list[str] = []
    left: list[tuple] = []
    right: list[tuple] = []

    def flush():
        for group in (left, right):
            group.sort(key=lambda it: it[0])
            ordered.extend(it[3] for it in group)
            group.clear()

    for it in items:
        if it[2] == "full":
            flush()
            ordered.append(it[3])
        elif it[2] == "left":
            left.append(it)
        else:
            right.append(it)
    flush()

    # merge consecutive boxed paragraphs into one quote block
    out_lines: list[str] = []
    for t in ordered:
        if out_lines and t.startswith("> ") and out_lines[-1].startswith("> "):
            out_lines.append(">")
            out_lines.append(t)
        else:
            if out_lines:
                out_lines.append("")
            out_lines.append(t)
    n_cols = len({x for x in xs if Counter(xs)[x] >= 2})
    n_cols = min(n_cols, 4) if n_cols > 2 else (2 if any(i[2] == "right" for i in items) else 1)
    return "\n".join(out_lines), n_cols


def extract(pdf_path: Path, vault_root: Path, source_id: str, first: int, last: int,
            images: str = "flagged", out_name: str | None = None, dpi: int = 110) -> dict:
    doc = pymupdf.open(pdf_path)
    first = max(1, first)
    last = min(doc.page_count, last)
    if first > last:
        raise ValueError(f"bad page range {first}–{last}")
    page_dicts = [doc.load_page(i).get_text("dict") for i in range(first - 1, last)]
    body = _body_size(page_dicts)
    root = Path(vault_root)
    img_dir = root / ".ingest" / "pages" / source_id
    text_dir = root / ".ingest" / "text" / source_id
    text_dir.mkdir(parents=True, exist_ok=True)

    results: list[PageResult] = []
    for pno in range(first, last + 1):
        page = doc.load_page(pno - 1)
        text, ncols = extract_page(page, body)
        flags = _page_quality(text, bool(page.get_images(full=False)), ncols)
        pr = PageResult(pno, text, flags)
        if images == "all" or (images == "flagged" and flags):
            img_dir.mkdir(parents=True, exist_ok=True)
            p = img_dir / f"p{pno:04d}.png"
            page.get_pixmap(dpi=dpi).save(p)
            pr.image = str(p)
        results.append(pr)

    name = out_name or f"pp{first:04d}-{last:04d}"
    out = text_dir / f"{name}.md"
    parts = [f"<!-- source: {source_id}  pages {first}–{last}. Cite as [{source_id} p.N] "
             f"using the page markers below. -->"]
    for r in results:
        head = f"<<page {r.page}>>"
        if r.flags:
            head = f"<<page {r.page} | text unreliable: {', '.join(r.flags)} | read the image: {r.image}>>"
        parts.append(head + "\n" + r.text)
    content = _resolve_hyphens("\n\n".join(parts) + "\n")
    out.write_text(content, encoding="utf-8")

    flagged = [r.page for r in results if r.flags]
    manifest = v.read_manifest(root)
    entry = manifest["sources"].setdefault(source_id, {"chunks": [], "flagged_pages": []})
    entry["flagged_pages"] = sorted(set(entry.get("flagged_pages", [])) | set(flagged))
    v.write_manifest(root, manifest)

    return {
        "source": source_id, "pages": [first, last], "text_file": str(out),
        "chars": len(content), "approx_tokens": len(content) // 4,
        "flagged": [{"page": r.page, "flags": r.flags, "image": r.image} for r in results if r.flags],
        "images": [r.image for r in results if r.image and not r.flags],
    }
