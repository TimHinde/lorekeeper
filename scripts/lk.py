#!/usr/bin/env python3
"""lorekeeper command line. One entry point for every deterministic step.

Run `python lk.py <command> --help` for details. Commands that take --vault
default to the nearest folder (upwards from the current one) with a vault.yaml.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import yaml  # noqa: F401
    import pymupdf  # noqa: F401
except ImportError as e:  # pragma: no cover
    sys.exit(f"Missing dependency: {e.name}. Install with: pip install PyMuPDF PyYAML "
             "(add --break-system-packages if pip refuses)")

import vaultlib as v


def _vault(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not v.is_vault(p):
            sys.exit(f"{p} is not a vault (no vault.yaml). Create one with: lk.py init {p} --name '...'")
        return p
    found = v.find_vault(Path.cwd())
    if not found:
        sys.exit("No vault found here or above. Pass --vault, or create one with: lk.py init <dir> --name '...'")
    return found


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _chunk_for(manifest: dict, source: str, chunk: str) -> tuple[int, dict]:
    entry = manifest["sources"].get(source)
    if not entry:
        sys.exit(f"Unknown source {source!r}. Run probe first. Known: {', '.join(manifest['sources']) or 'none'}")
    chunks = entry["chunks"]
    if chunk.isdigit():
        k = int(chunk)
        if not 1 <= k <= len(chunks):
            sys.exit(f"Chunk {k} out of range 1–{len(chunks)}")
        return k, chunks[k - 1]
    for k, c in enumerate(chunks, 1):
        if c["name"].lower() == chunk.lower():
            return k, c
    sys.exit(f"No chunk named {chunk!r} in {source}")


# ── commands ────────────────────────────────────────────────────────────────

def cmd_init(a):
    root = v.init_vault(Path(a.dir), a.name or Path(a.dir).name, a.system or [])
    import build_index
    build_index.build(root)
    print(f"Vault ready at {root}")


def cmd_probe(a):
    import pdftools
    root = _vault(a.vault)
    try:
        res = pdftools.probe(Path(a.pdf), root, a.id, a.kind, a.system, a.title, a.max_pages, a.replan)
    except ValueError as e:
        sys.exit(str(e))
    _print_json(res)


def cmd_extract(a):
    import pdftools
    root = _vault(a.vault)
    if a.pages:
        m = re.match(r"^(\d+)(?:-(\d+))?$", a.pages)
        if not m:
            sys.exit("--pages must look like 12 or 12-20")
        first, last = int(m.group(1)), int(m.group(2) or m.group(1))
        name = None
        if not a.source:
            sys.exit("--source is required with --pages")
        source = a.source
    else:
        manifest = v.read_manifest(root)
        source = a.source or (next(iter(manifest["sources"])) if len(manifest["sources"]) == 1 else None)
        if not source:
            sys.exit("Several sources in this vault; pass --source")
        k, c = _chunk_for(manifest, source, a.chunk)
        first, last = c["pages"]
        name = f"{k:03d}-{v.slugify(c['name'])[:40]}"
    res = pdftools.extract(Path(a.pdf), root, source, first, last, a.images, name, a.dpi)
    _print_json(res)


def cmd_next(a):
    root = _vault(a.vault)
    manifest = v.read_manifest(root)
    for sid, entry in manifest["sources"].items():
        if a.source and sid != a.source:
            continue
        for k, c in enumerate(entry["chunks"], 1):
            if c.get("status", "pending") in ("pending", "failed"):
                done = sum(1 for x in entry["chunks"] if x.get("status") == "done")
                todo = sum(1 for x in entry["chunks"] if x.get("status", "pending") in ("pending", "failed"))
                _print_json({"source": sid, "file": entry.get("file"), "chunk": k, **c,
                             "progress": f"{done} done, {todo} to do"})
                return
    print(json.dumps({"done": True, "message": "No pending chunks."}))


def cmd_mark(a):
    root = _vault(a.vault)
    manifest = v.read_manifest(root)
    k, c = _chunk_for(manifest, a.source, a.chunk)
    c["status"] = a.status
    v.write_manifest(root, manifest)
    print(f"Chunk {k} ({c['name']}) marked {a.status}")


def cmd_upsert(a):
    import upsert_entity
    root = _vault(a.vault)
    res = upsert_entity.upsert_files(root, [Path(f) for f in a.files], a.layer)
    out = res.as_dict()
    if a.source and a.chunk:
        manifest = v.read_manifest(root)
        k, c = _chunk_for(manifest, a.source, a.chunk)
        if res.rejected and not (res.created or res.updated or res.unchanged):
            c["status"] = "failed"
        else:
            c["status"] = "done"
            c["entities"] = len(res.created) + len(res.updated) + len(res.unchanged)
        v.write_manifest(root, manifest)
        out["chunk"] = {"index": k, "name": c["name"], "status": c["status"]}
    _print_json(out)
    if res.rejected:
        sys.exit(1)


def cmd_merge(a):
    import upsert_entity
    root = _vault(a.vault)
    try:
        _print_json(upsert_entity.merge_duplicate(root, a.duplicate, a.into, a.layer))
    except ValueError as e:
        sys.exit(str(e))


def cmd_validate(a):
    import validate
    sys.exit(validate.run(_vault(a.vault), a.strict, a.quiet))


def cmd_index(a):
    import build_index
    files = build_index.build(_vault(a.vault))
    print(f"Wrote {len(files)} index files")


def cmd_digest(a):
    import build_digest
    root = _vault(a.vault)
    out = Path(a.out) if a.out else root.parent / f"{root.name}-digest"
    _print_json(build_digest.build(root, out, a.max_kb))


def cmd_status(a):
    root = _vault(a.vault)
    vault = v.load_vault(root)
    manifest = v.read_manifest(root)
    counts = {}
    for e in vault.entities:
        counts.setdefault(e.layer, {}).setdefault(e.type, 0)
        counts[e.layer][e.type] += 1
    review = root / ".ingest" / "review.md"
    _print_json({
        "vault": str(root), "name": vault.meta.get("name"),
        "entities": counts,
        "sessions": len(vault.sessions), "table_notes": len(vault.notes),
        "sources": {sid: {"chunks": {s: sum(1 for c in e["chunks"] if c.get("status", "pending") == s)
                                    for s in ("done", "pending", "failed", "skip")},
                          "flagged_pages": len(e.get("flagged_pages", []))}
                    for sid, e in manifest["sources"].items()},
        "review": review.read_text(encoding="utf-8").splitlines() if review.exists() else [],
    })


def _score(e: v.Entity, terms: list[str], phrase: str) -> int:
    name = v.norm_name(e.name)
    aliases = [v.norm_name(str(x)) for x in v.as_list(e.fm.get("aliases"))]
    tags = " ".join(str(t).lower() for t in v.as_list(e.fm.get("tags")))
    summary = str(e.fm.get("summary", "")).lower()
    body = e.body.lower()
    s = 0
    if phrase and (phrase == name or phrase in aliases):
        s += 100
    elif phrase and (phrase in name or any(phrase in al for al in aliases)):
        s += 40
    for t in terms:
        if t in name.split() or any(t in al.split() for al in aliases):
            s += 25
        if t in tags:
            s += 15
        if t in summary:
            s += 10
        s += min(body.count(t), 8) * 2
    if terms and all(t in body or t in summary or t in name for t in terms):
        s += 10
    return s


def cmd_find(a):
    root = _vault(a.vault)
    vault = v.load_vault(root)
    phrase = v.norm_name(" ".join(a.query)) if a.query else ""
    terms = [t for t in re.findall(r"[a-z0-9]+", " ".join(a.query).lower()) if len(t) > 2 or t.isdigit()]
    rows = []
    for e in vault.entities:
        if a.type and e.type != a.type:
            continue
        if a.layer and e.layer != a.layer:
            continue
        if a.tag and a.tag.lower() not in [str(t).lower() for t in v.as_list(e.fm.get("tags"))]:
            continue
        sc = _score(e, terms, phrase) if terms else 1
        if sc > 0:
            rows.append((sc, e))
    if not a.type and not a.layer and not a.tag and terms:
        for doc in vault.notes + vault.sessions:
            text = doc.body.lower()
            sc = sum(min(text.count(t), 8) * 2 for t in terms)
            if sc:
                rows.append((sc, doc))
    rows.sort(key=lambda r: -r[0])
    for sc, e in rows[: a.limit]:
        if isinstance(e, v.Entity) and e.fm.get("type"):
            print(f"{e.id}\t{e.layer}\t{e.name}\t{e.fm.get('summary', '')}")
        else:
            rel = e.path.relative_to(root)
            print(f"{rel}\ttable\t{e.fm.get('title') or e.fm.get('about') or e.path.stem}\t")
    if not rows:
        print("No matches.")


def cmd_show(a):
    root = _vault(a.vault)
    vault = v.load_vault(root)
    notes = {}
    for n in vault.notes:
        notes.setdefault(n.fm.get("about"), []).append(n)
    for q in a.ids:
        hits = [e for e in vault.entities if e.id == q]
        if not hits:
            nq = v.norm_name(q)
            hits = [e for e in vault.entities
                    if nq == v.norm_name(e.name) or nq in [v.norm_name(str(x)) for x in v.as_list(e.fm.get("aliases"))]]
        if not hits:
            print(f"### {q}: not found\n")
            continue
        for e in sorted(hits, key=lambda e: e.layer != "canon"):
            print(f"### {e.layer}/{e.id}  ({e.path.relative_to(root)})\n")
            print(e.path.read_text(encoding="utf-8"))
            for n in notes.get(e.id, []):
                print(f"### TABLE NOTE — overrides canon where they differ ({n.path.relative_to(root)})\n")
                print(n.path.read_text(encoding="utf-8"))


def cmd_session(a):
    root = _vault(a.vault)
    vault = v.load_vault(root)
    number = max([int(s.fm.get("number") or 0) for s in vault.sessions] + [0]) + 1
    date = a.date or v.today()
    path = root / "table" / "sessions" / f"{date}-{number:03d}.md"
    fm = {"date": date, "number": number, "title": a.title or "", "present": [], "changed": []}
    body = "## What happened\n\n## Changes to the world\n\n## Open threads\n"
    path.write_text(v.dump_document(fm, body), encoding="utf-8")
    print(json.dumps({"session": str(path), "number": number}))


def cmd_note(a):
    root = _vault(a.vault)
    vault = v.load_vault(root)
    if a.id not in vault.all_ids():
        sys.exit(f"No entity {a.id!r}. Use find to get the id.")
    t, _, slug = a.id.partition("/")
    path = root / "table" / "notes" / f"{t}--{slug}.md"
    created = not path.exists()
    if created:
        fm = {"about": a.id, "updated": v.today()}
        body = "## Current state\n\n## Changes from canon\n\n## History at this table\n"
        path.write_text(v.dump_document(fm, body), encoding="utf-8")
    print(json.dumps({"note": str(path), "created": created}))


EXCLUDE_IN_PACK = (".ingest/pages/", ".ingest/text/")


def cmd_pack(a):
    root = _vault(a.vault)
    import build_index
    build_index.build(root)
    out = Path(a.out) if a.out else root.parent / f"{root.name}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if not a.full and rel.startswith(EXCLUDE_IN_PACK):
                continue
            z.write(p, f"{root.name}/{rel}")
            n += 1
    print(json.dumps({"zip": str(out), "files": n, "kb": round(out.stat().st_size / 1024, 1)}))


def cmd_unpack(a):
    dest = Path(a.dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(a.zip) as z:
        for m in z.namelist():
            target = (dest / m).resolve()
            if not str(target).startswith(str(dest.resolve())):
                sys.exit(f"Refusing unsafe path in zip: {m}")
        z.extractall(dest)
    roots = [p.parent for p in dest.rglob("vault.yaml")]
    if not roots:
        sys.exit("No vault.yaml in that zip")
    print(json.dumps({"vault": str(sorted(roots, key=lambda p: len(p.parts))[0])}))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lk.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        if name not in ("init", "unpack"):
            p.add_argument("--vault", help="vault folder (default: nearest with vault.yaml)")
        return p

    p = add("init", cmd_init, "Create an empty vault")
    p.add_argument("dir")
    p.add_argument("--name")
    p.add_argument("--system", action="append", help="game system id, repeatable (e.g. dnd5e, mothership)")

    p = add("probe", cmd_probe, "Register a PDF as a source: outline, kind guess, chunk plan")
    p.add_argument("pdf")
    p.add_argument("--id", help="source id (default: slug of the title)")
    p.add_argument("--kind", choices=v.SOURCE_KINDS)
    p.add_argument("--system")
    p.add_argument("--title")
    p.add_argument("--max-pages", type=int, default=15, help="page budget per chunk (default 15)")
    p.add_argument("--replan", action="store_true", help="discard the existing chunk plan")

    p = add("extract", cmd_extract, "Extract a chunk's text (and images of unreliable pages)")
    p.add_argument("pdf")
    p.add_argument("--source")
    p.add_argument("--chunk", default="1", help="chunk number or name from the plan")
    p.add_argument("--pages", help="explicit range instead of a chunk, e.g. 12-20")
    p.add_argument("--images", choices=["flagged", "all", "none"], default="flagged")
    p.add_argument("--dpi", type=int, default=110)

    p = add("next", cmd_next, "Show the next pending chunk")
    p.add_argument("--source")

    p = add("mark", cmd_mark, "Set a chunk's status")
    p.add_argument("--source", required=True)
    p.add_argument("--chunk", required=True)
    p.add_argument("--status", required=True, choices=["pending", "skip", "done", "failed"])

    p = add("upsert", cmd_upsert, "Merge fragment files into the vault")
    p.add_argument("files", nargs="+")
    p.add_argument("--layer", default="canon", choices=v.ENTITY_LAYERS)
    p.add_argument("--source", help="with --chunk: mark that chunk done")
    p.add_argument("--chunk")

    p = add("merge", cmd_merge, "Fold a duplicate entity into another and repoint references")
    p.add_argument("duplicate", help="id of the entity to remove")
    p.add_argument("into", help="id of the entity to keep")
    p.add_argument("--layer", default="canon", choices=v.ENTITY_LAYERS)

    p = add("validate", cmd_validate, "Check the vault against the spec")
    p.add_argument("--strict", action="store_true", help="fail on warnings too")
    p.add_argument("--quiet", action="store_true", help="only print the totals")

    add("index", cmd_index, "Rebuild INDEX.md and _index/")

    p = add("digest", cmd_digest, "Bundle the vault for a Claude Project")
    p.add_argument("--out")
    p.add_argument("--max-kb", type=int, default=300, help="split bundles larger than this")

    add("status", cmd_status, "Counts, ingest progress, duplicates to review")

    p = add("find", cmd_find, "Search entities by name, alias, tag, summary and text")
    p.add_argument("query", nargs="*")
    p.add_argument("--type", choices=v.TYPES)
    p.add_argument("--layer", choices=v.ENTITY_LAYERS)
    p.add_argument("--tag")
    p.add_argument("--limit", type=int, default=15)

    p = add("show", cmd_show, "Print entities by id or name, with any table notes")
    p.add_argument("ids", nargs="+")

    p = add("session", cmd_session, "Start the next session log in table/sessions/")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.add_argument("--title")

    p = add("note", cmd_note, "Create (or locate) the table note for an entity")
    p.add_argument("id")

    p = add("pack", cmd_pack, "Zip the vault for download")
    p.add_argument("--out")
    p.add_argument("--full", action="store_true", help="include extracted text and page images")

    p = sub.add_parser("unpack", help="Unzip a vault")
    p.set_defaults(fn=cmd_unpack)
    p.add_argument("zip")
    p.add_argument("--dest", default=".")

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
