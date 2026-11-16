# CLAUDE.md

Guidance for working on this repository. (Guidance for *using* the vault lives in
the skills, not here.)

## What this is

Lorekeeper: Claude skills plus a Python CLI that turn TTRPG books into a cited,
system-agnostic markdown vault and support prep against it. Design: `DESIGN.md`.
Format contract: `spec/VAULT.md`.

## Rules

- **Scripts never call an LLM.** Everything in `scripts/` is deterministic. The
  model's work happens in the skills.
- **The spec is the contract.** Change `spec/VAULT.md` first, then `vaultlib.py`
  constants, then the scripts, then the skills. A breaking format change bumps
  `FORMAT_VERSION`.
- **Canon is never invented.** Nothing a tool writes to `canon/` may be created
  without a citation. Generated material goes to `ideas/`.
- **No book content in the repo.** Tests use `tests/make_fixture.py`, which builds
  an invented adventure. The SRD in `packs/` is CC BY 4.0.
- **System-agnostic core.** Nothing in `scripts/` or `skills/` may assume a game
  system. System-specific material belongs in `packs/`.
- Python 3.10+, dependencies limited to PyMuPDF and PyYAML. Skills run in sandboxes
  where installing more is friction.

## Layout

| Path | Purpose |
|---|---|
| `scripts/lk.py` | CLI entry point; every subcommand |
| `scripts/vaultlib.py` | Spec constants, parsing, writing, loading |
| `scripts/pdftools.py` | Probe, chunk planning, layout-aware extraction |
| `scripts/upsert_entity.py` | Fragment parsing, merge rules, duplicate merging |
| `scripts/validate.py` | Spec §10 checks |
| `scripts/build_index.py` / `build_digest.py` | Generated indexes; Project bundles |
| `scripts/build_dist.py` | Plugin zip and standalone skill zips |
| `skills/*/SKILL.md` | The five skills |
| `templates/` | Entity templates; Claude Project instructions |
| `packs/` | Unported system material from Tome |

## Commands

```bash
python -m unittest discover -s tests -v     # tests
python scripts/build_dist.py                # release zips into dist/
python scripts/lk.py --help                 # CLI
```

## Output style for skills

GM-facing text is punchy, bulleted and action-focused: what the GM needs right now.
