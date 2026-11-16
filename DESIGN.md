# Lorekeeper — design

*Placeholder name. Successor to Tome-MCP. Status: phases 0–3 built, untested on real books, 2026-11-16.*

## What it is

A toolkit that lets a GM turn rulebooks, settings and adventures they own into a
system-agnostic markdown vault, then ask questions and ideate against it in Claude.

Tome stopped at "PDF in, vault out". Lorekeeper treats the vault as the middle of
the pipeline: the point is the prep that happens afterwards.

## Decisions already made

| Question | Answer | Consequence |
|---|---|---|
| Primary clients | Claude desktop app and web | Skills first. The vault must travel as a zip, because a web session has no folder that persists. |
| Obsidian | Nice-to-have | Keep frontmatter and `[[links]]` because they cost nothing. Drop Dataview and anything Obsidian-only. |
| Tome-App | Unrelated (Nimble character sheets) | Out of scope. |
| Who extracts | The calling Claude, guided by a skill | No API keys, no provider SDKs, no LLM calls inside tools. |
| MCP | Later, read-only, only if needed | Not on the critical path. |

## Goals

1. A GM uploads a PDF and gets a vault where every fact carries a source page.
2. Works for any system. A Mothership module and a 5e adventure use the same schema.
3. The GM can ask "who knows about the cult?" and "give me three encounters for the
   swamp", and can always tell published text from generated ideas.
4. No API keys, no config files, no local server for the basic path.

## Non-goals

- Generating rules-legal stat blocks for a given system.
- VTT export, character sheets, hosting.
- Shipping any book content. The repo holds tooling only.

## Architecture

```
            deterministic scripts                Claude + skill
PDF ──► pdf_probe ──► pdf_extract ──► chunk text ──► ingest-book ──► entity fragments
        (TOC, type,   (layout-aware    + page                            │
         chunk plan)   text, flags      images                           ▼
                       bad pages)                                  upsert_entity
                                                                   (merge, cite, validate)
                                                                         │
                                                                         ▼
                                              VAULT  canon/  table/  ideas/  _index/
                                                                         │
                 ┌───────────────────────────┬───────────────────────────┤
                 ▼                           ▼                           ▼
           prep skills                 build_digest                read-only MCP
     ask · encounter · session    bundle for a Claude Project        (phase 4)
```

Three rules hold the design together:

- **Scripts never call an LLM.** They do TOC parsing, text extraction, merging,
  validation and indexing.
- **Claude never does bookkeeping.** It reads a chunk and writes small entity
  fragments. A script merges them.
- **The vault format is the contract.** Ingestion and every consumer depend only on
  `spec/VAULT.md`.

## How a GM uses it

**Ingest (desktop or web).** Install the plugin, attach a PDF, say "ingest this".
The skill probes the book, shows the chunk plan, and works through it. At the end
the GM gets `vault.zip`. On desktop with a connected folder, the vault is written
there instead.

**Add a second book.** Attach the existing `vault.zip` and the new PDF. The manifest
inside the vault tells the skill what is already done, so the same flow also resumes
an interrupted ingest.

**Prep, option A: skills.** Attach the vault (or point at the folder) and ask. The
skills read the indexes first and open only the entities they need.

**Prep, option B: a Claude Project.** Run `build_digest`, upload the handful of
bundle files it produces, paste in the instructions template. No plugin needed
after that.

## Repo layout

```
lorekeeper/
├── DESIGN.md
├── .claude-plugin/           plugin and marketplace manifests
├── spec/VAULT.md              format contract, versioned
├── scripts/
│   ├── pdftools.py            probe (TOC, kind, chunk plan) and layout-aware extraction
│   ├── upsert_entity.py       merge a fragment into the vault
│   ├── validate.py            check a vault against the spec
│   ├── lk.py                  single CLI entry point for everything below
│   ├── vaultlib.py            shared spec constants and parsing
│   ├── build_index.py         regenerate _index/ and INDEX.md
│   ├── build_digest.py        bundle a vault for Project upload
│   └── build_dist.py          plugin zip and standalone skill zips
├── skills/
│   ├── ingest-book/
│   ├── ask-the-vault/
│   ├── build-encounter/
│   ├── prep-session/
│   └── log-session/
├── templates/                 entity templates, Project instructions
├── packs/                     optional system packs (5e SRD, Nimble)
├── mcp/                       phase 4
└── tests/fixtures/            small CC-licensed sample PDFs only
```

## What happens to Tome's code

| Tome | Fate |
|---|---|
| `pdf_tools.py` | Keep. Upgrade to block-level extraction with reading order, chunk below top-level TOC entries, add a no-TOC fallback that chunks by page count. |
| Page provenance | Keep, and make it mandatory per fact rather than per entity. |
| Frontmatter and link writing in `obsidian_tools.py` | Keep the useful parts inside `upsert_entity.py`. |
| Tests, CI | Keep and extend. |
| `reference_tools.py`, SRD submodule, Nimble tools | Move to `packs/`. Not in the core. |
| `extract_entities_llm`, provider SDKs, `.env` keys | Delete. |
| Races / classes / spells / feats / deities arrays | Delete. Replaced by eight generic types plus tags. |
| First-write-wins merge | Delete. Replaced by append-with-citation. |
| "Never invent content" rule | Narrowed to "never invent inside `canon/`". |
| `_Home.md` with Dataview blocks | Replaced by static `INDEX.md`. |
| FastMCP server | Removed from the core. A new read-only one may return in phase 4. |

## Trade-offs

- **Skill instead of server for ingestion.** Removes keys and double billing, and
  works on web. The cost is that ingestion quality depends on the model following a
  skill across a long job, so the manifest and the validator matter a lot.
- **Fragments instead of one JSON blob per chunk.** A truncated reply loses one
  entity, not a chapter. The cost is a merge script that has to be right.
- **Verbatim stat blocks.** Works for every system on day one. The cost is no
  structured queries over stats unless a system pack parses them.
- **Zip round-trip on web.** Simple and portable. The cost is friction: the GM
  re-attaches the vault each session unless they use a Project or a connected folder.
- **Three layers.** Protects the published text from drift. The cost is that a
  reader has to combine canon with table notes to get "the truth at this table".

## Phases

| # | Deliverable | Done when |
|---|---|---|
| 0 | New repo with Tome's history, stripped down. Licence decided. | CI green on what remains. |
| 1 | `spec/VAULT.md`, templates, `validate.py`, `build_index.py` | Ten hand-written entities from a real book pass validation and read well. |
| 2 | `pdf_probe`, `pdf_extract`, `upsert_entity`, `ingest-book` skill | One 5e adventure and one non-D&D book ingested. A hand check of 20 random facts per book finds the cited page correct. |
| 3 | Prep skills, `build_digest`, Project template, plugin packaging | A real session prepped from the vault, on desktop and in a web Project. |
| 4 | Read-only MCP: `search`, `get_entity`, `related`, `list_by_type` | Only built if phase 3 shows retrieval failing on large vaults. |
| 5 | System packs | On demand. |

Phase 2's non-D&D book is the real gate. If the schema strains there, it changes
before anything else is built.

## Risks

- **Layout garbling.** Two-column pages, sidebars and stat blocks. Mitigation: the
  extractor scores each page and flags suspicious ones so the skill reads the page
  image instead.
- **Scanned PDFs.** No text layer. Mitigation: image-only path, slower. OCR is out
  of scope for the first version.
- **Entity duplicates.** "Vessa", "Vessa Thorn" and "the Grey Widow" as three files.
  Mitigation: alias matching in upsert, plus a review pass at the end of ingestion
  that lists likely duplicates.
- **Long ingests stalling.** Mitigation: manifest with per-chunk status; every run
  is a resume.
- **Copyright.** Vaults contain text from commercial books. Mitigation: paraphrase
  by default, verbatim only for stat blocks and read-aloud text, vaults are
  git-ignored and documented as private.

## To verify before phase 2

These are product limits I have not checked, and they shape the ingest flow:

- Maximum PDF size and page count for an upload in the Claude app.
- How much a Claude Project can hold, which sets the digest size budget.
- How a GM installs a plugin or skill on web versus desktop.

## Revisit as it grows

- A structured stat layer per system, if GMs want "threat under X" queries.
- The MCP, if vaults pass a few hundred entities.
- OCR for scanned books.
- Shared vaults for co-GMs, which raises the copyright question again.
