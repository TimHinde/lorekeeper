---
name: ingest-book
description: Turn a tabletop RPG book the user owns (adventure, setting, bestiary, rulebook, any system) into a lorekeeper campaign vault of cited, system-agnostic markdown entities. Use when the user attaches or points at a game PDF and wants it ingested, parsed, imported or added to their campaign vault, or wants to resume an ingest that stopped part way.
---

# Ingest a book into a lorekeeper vault

You read the book; the scripts do the bookkeeping. You never write vault files by
hand during ingestion: you write *fragments*, and `lk upsert` merges them, cites
them and links them. The format contract is `spec/VAULT.md` (in the plugin root,
or `references/VAULT.md` beside this file in a standalone install). Read it once
before the first chunk if you have not seen it this conversation.

## 0. Setup

Find the CLI. It is `scripts/lk.py` either inside this skill's folder (standalone
install) or two folders up from it (plugin install):

```bash
SKILL_DIR="<this skill's base directory>"
LK="python3 $(ls "$SKILL_DIR"/scripts/lk.py "$SKILL_DIR"/../../scripts/lk.py 2>/dev/null | head -1)"
$LK --help
```

If it reports a missing dependency: `pip install PyMuPDF PyYAML` (add
`--break-system-packages` if pip refuses).

Find or create the vault, in this order:

1. The user attached a vault zip: `$LK unpack <zip> --dest .` and use the folder it prints.
2. A folder you can reach (a connected folder, the working directory) has a `vault.yaml`: use it in place.
3. Otherwise create one: `$LK init ./<campaign-slug> --name "<Campaign name>" --system <system-id>`.

Every later command takes `--vault <dir>`.

## 1. Probe and agree the plan

```bash
$LK probe <book.pdf> --vault <dir> [--system <id>] [--kind adventure|setting|bestiary|rulebook|supplement|other]
```

This registers the book as a source, writes `sources/<id>.md` with its outline,
and plans chunks of about 15 pages along the table of contents. If the source is
already registered with the same file, it resumes the existing plan.

Tell the user in a few lines: title, the kind and system you will record, page
count, how many chunks, which ones are marked `skip` (front matter, credits,
index), and any warning (`scanned: true` means every page will be read as an
image: slow). Ask one question only if something is genuinely unclear, most often
the game system, which the PDF cannot tell you reliably. If nobody answers, go
ahead with the plan and say what you assumed.

To change the plan: `$LK mark --source <id> --chunk N --status skip|pending`, or
re-probe with `--max-pages` and `--replan`.

## 2. Work through the chunks

Repeat until `$LK next` says there is nothing pending:

```bash
$LK next --vault <dir>                                   # which chunk is next
$LK extract <book.pdf> --vault <dir> --source <id> --chunk N
```

`extract` writes the chunk's text to `.ingest/text/<id>/…md` and prints its path,
plus any **flagged pages**: pages whose text layer looks wrong (image-only,
garbled, three columns…). Read the text file. For each flagged page, read the PNG
it names and use what you see instead of the text. Text marked with `>` was inside
a box on the page: often read-aloud text or a sidebar.

Before writing, check what already exists so you extend entities rather than
duplicate them: read `_index/<type>.md` for the types this chunk touches, or run
`$LK find <name>` for each name you are about to write. Reuse existing IDs.

Then write **one fragment file for the chunk**, at
`<dir>/.ingest/fragments/<NNN>.md` (NNN = chunk number), and merge it:

```bash
$LK upsert <dir>/.ingest/fragments/<NNN>.md --vault <dir> --source <id> --chunk N
```

Read the output:

- `rejected`: fix those fragments and run upsert again on the same file (it is
  safe to re-run; unchanged content is not duplicated).
- `review`: possible duplicates, kept separate for now. Deal with them at the end.
- `unresolved`: IDs you referenced that do not exist yet. Fine mid-book; they are
  usually created by a later chunk. Resolve leftovers at the end.

After each chapter, add one or two lines to `## Chapter summaries` in
`sources/<id>.md`: `- Chapter 2: The Sunken Chapel (pp.4–5): …`. Edit that file
directly; it is the only vault file you edit by hand during ingestion.

**Long books.** A 300-page book is twenty-plus chunks and will not fit in one
conversation. The vault is the memory, not the conversation: do not re-read
earlier chunks. If the conversation is getting long, stop at a chunk boundary,
pack the vault (step 3), and tell the user to start a new conversation with the
zip and the PDF and say "resume ingesting". The manifest picks up where you left off.

## Fragment format

A fragment file is a run of entities, each opening with its own frontmatter.
Write only what this chunk supports; upsert merges it with what is already there.

````markdown
---
type: npc
name: Maren Holt
summary: Brinemouth's stern harbourmaster; her son was aboard the missing trawler.
tags: [brinemouth, quest-giver]
role: harbourmaster
location: location/brinemouth
---
## Description
- Stern; keeps a ledger of every boat in Brinemouth. [salt-wake p.2]

## Wants
- The missing trawler found: her son was aboard. [salt-wake p.2]

## In play
- Pays 20 silver to search the wreck of the [[item/gulls-promise|Gull's Promise]]. [salt-wake p.3]

---
type: creature
name: Silt Lurker
summary: Pale eel-like mud ambusher in the flooded chapel nave.
threat: low
system: any
---
## Behaviour
- Hides in the nave mud and strikes at ankles. [salt-wake p.4]

## Stat block
```statblock system=any source=salt-wake page=4
(the stat block exactly as printed)
```
````

Rules for fragments:

- **Required:** `type` and `name`; `summary` (one sentence, ≤160 characters) on
  anything new. Leave out `id`, `layer` and `sources`: upsert derives them.
- **Cite every bullet and paragraph** with `[<source-id> p.N]` or `[<source-id> pp.N–M]`,
  using the `<<page N>>` markers in the extracted text. An uncited fragment is rejected.
- **Paraphrase.** Short, punchy bullets a GM can use mid-session. Two things stay
  word for word: stat blocks and other rules text (in a `statblock` fence with
  `system`, `source` and `page`), and read-aloud text (in a callout:
  `> [!read-aloud] [<source-id> p.N]` then `> text`).
- **Never invent.** Nothing goes in canon that the page does not say. No guessed
  motives, no filled-in stats. If the book is vague, the entity is short.
- **Sections** per type are in the spec (§6). Skip empty ones. Odd material goes
  under `## Notes`.
- **References:** fields such as `location`, `faction`, `leader`, `participants`,
  `related` hold IDs: `<type>/<slug>`, slug lowercase-hyphenated, no leading
  "the". Link in the body with `[[type/slug]]` or `[[type/slug|shown text]]`. A
  plain `[[Name]]` also works when the entity exists; upsert rewrites it.
- **Do not use `---` as a horizontal rule** inside a fragment; it starts the next entity.

## What to capture

One entity per thing a GM would look up by name.

| The book has | Write |
|---|---|
| A named person | `npc`: description, wants, secrets, relationships, how to play them, stat block if printed |
| A place, from region down to a keyed room | `location`, with `kind` and `parent` (room → site → settlement → region) |
| A group, cult, guild, crew | `faction` |
| A kind of monster or a generic foe (bandits, guards) | `creature`, stat block verbatim |
| Treasure, a clue, a vehicle, a relic | `item` |
| An encounter, set piece, trap, puzzle, negotiation, event | `scene`, with `kind`, `location`, `participants`, `chapter`, `threat` if the book signals one |
| History, religion, culture, rules unique to the setting, random tables | `lore`, with `kind` |
| Player options (ancestries, classes, playbooks, spells, careers) | `lore` with `kind: player-option` and the tag `player-option`; rules text in a `statblock` fence |
| A rumour, job, lead, adventure hook | `hook`, with `leads_to` and `given_by` |

`threat` is `trivial`, `low`, `mid`, `high` or `boss`: your reading of how the
book presents it, not a rules calculation. Omit it when the book gives no sense of it.

By book kind:

- **Adventure:** scenes, locations and NPCs are the core; capture read-aloud text
  and what each scene's outcomes lead to.
- **Setting:** locations, factions, lore and hooks; NPCs where named.
- **Bestiary:** one `creature` per entry with its stat block; lore for ecology
  sections only if they are useful at the table.
- **Rulebook:** do not turn every rule into an entity. Capture what a GM would
  look up mid-session: conditions, key procedures, tables, as `lore` with the text
  verbatim in a `statblock` fence.

When the book contradicts something already in the vault, keep both. Upsert
records frontmatter disagreements itself; for facts in the body, add a callout
under `## Notes`:

```markdown
> [!conflict]
> - The abbey flooded forty years ago. [salt-wake p.3]
> - The abbey flooded last winter. [harrowick-gazetteer p.21]
```

## 3. Finish

```bash
$LK status --vault <dir>          # progress, duplicates to review
$LK validate --vault <dir>
```

- **Duplicates** (`review` in status, "possible duplicate" in validate): if two
  files are the same thing, `$LK merge <duplicate-id> <keep-id> --vault <dir>`.
  It folds the content together, keeps the old name as an alias and repoints
  every reference. If they are different things, leave them.
- **Errors:** fix every one. For a reference to an entity that never got a file,
  either write a short cited fragment for it (if the book says anything about
  it) or remove the reference.
- **Warnings** are judgement calls; unresolved `[[links]]` are worth fixing.

Then deliver:

- Working in a folder the user keeps (a connected folder): say where the vault is.
- Otherwise: `$LK pack --vault <dir>` and send the zip. Tell the user to keep it
  and attach it next time, together with the next book or to ask questions.

Report briefly: entities by type, chunks skipped, pages read from images, and
anything you could not read. Mention that `$LK digest` bundles the vault for a
Claude Project if they want to work that way.

## Privacy

The vault holds text from a book the user bought. It is for their own use. Do not
publish it, share it, or put it anywhere but where the user asked.
