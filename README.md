# Lorekeeper

*Working name.* Turn the tabletop RPG books you own into a campaign vault, then use
it to prep: ask questions, build encounters, plan and log sessions. Works with any
game system.

Lorekeeper is a set of Claude skills plus a small Python CLI. Claude reads the book;
the scripts do the bookkeeping: chunking, page citations, merging, linking,
validation. There are no API keys and no server to run.

It grew out of [Tome](https://github.com/TimHinde/Tome-MCP). What changed and why is
in [DESIGN.md](DESIGN.md).

## What you get

A **vault**: a folder of markdown files, one per NPC, place, faction, creature,
item, scene, piece of lore or hook.

```
my-campaign/
├── INDEX.md          start here
├── _index/           one table per type, plus backlinks
├── sources/          one file per book: outline and chapter summaries
├── canon/            what the books say, every fact with its page
├── table/            what happened at your table: sessions, party, changes
└── ideas/            encounters and NPCs generated for your campaign
```

Every fact from a book carries its page, like `[salt-wake p.12]`, so you can check
it. Generated material lives apart from the books, so the vault never blurs the two.
The files are plain markdown with frontmatter and `[[links]]`, so they also open
nicely in Obsidian.

The format is specified in [spec/VAULT.md](spec/VAULT.md).

## Skills

| Skill | Use it to |
|---|---|
| `ingest-book` | Add a PDF to the vault. Resumable across conversations for long books. |
| `ask-the-vault` | Ask about your campaign: "who knows about the cult?", "what's behind the crypt door?" |
| `build-encounter` | Get encounter options built from the vault, and save the ones you like to `ideas/`. |
| `prep-session` | Get a one-page prep sheet for the next session. |
| `log-session` | Record what happened: session log, changed NPCs and places, what the party learned. |

## Install

**As a plugin** (Claude Code, and apps that support plugins):

```
/plugin marketplace add TimHinde/lorekeeper
/plugin install lorekeeper@lorekeeper
```

**As individual skills** (apps where you upload skills one by one): run
`python scripts/build_dist.py` and upload the zips from `dist/skills/`. Each one
carries its own copy of the scripts.

The scripts need Python 3.10+ with `PyMuPDF` and `PyYAML`
(`pip install -r requirements.txt`). Claude installs them if they are missing.

## Use

**Ingest a book.** Attach the PDF and ask Claude to ingest it. Claude probes the
book, shows you the chunk plan, works through it, and hands you back the vault as a
zip, or writes it to a folder you have connected. For your next book, attach the
vault zip and the new PDF together.

**Prep with skills.** Attach the vault zip (or connect its folder) and ask.

**Prep in a Claude Project.** Run `python scripts/lk.py digest --vault <dir>`,
upload the files it writes, and paste `PROJECT-INSTRUCTIONS.md` into the Project
instructions. After each session, re-upload `table.md`.

## The CLI

Every deterministic step is a subcommand of `scripts/lk.py`:

| Command | Does |
|---|---|
| `init <dir> --name …` | Create an empty vault |
| `probe <pdf>` | Register a book: outline, kind, chunk plan |
| `next` | Show the next chunk to read |
| `extract <pdf> --chunk N` | Write a chunk's text with page markers; render unreliable pages as images |
| `upsert <fragments…>` | Merge entity fragments into the vault |
| `merge <dup> <keep>` | Fold a duplicate into another entity |
| `find <words>` / `show <id>` | Search and print entities |
| `session` / `note <id>` | Start a session log / a table note |
| `validate` | Check the vault against the spec |
| `index` / `digest` | Rebuild indexes / bundle for a Claude Project |
| `pack` / `unpack` | Zip and unzip a vault |
| `status` | Progress and duplicates to review |

## Develop

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_dist.py
```

Tests build a small invented adventure PDF on the fly (`tests/make_fixture.py`), so
no copyrighted material is needed. `packs/` holds system material carried over from
Tome that has not been ported yet.

## Copyright

Vaults contain text from books you bought. They are for your own use: the repo's
`.gitignore` excludes them, and no part of Lorekeeper uploads them anywhere.
Lorekeeper ships tooling only, never book content.

> This work includes material from the System Reference Document 5.2 ("SRD 5.2") by
> Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2
> is licensed under the Creative Commons Attribution 4.0 International License.

## Licence

GPL-3.0, inherited from Tome.
