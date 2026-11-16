# Vault format — version 1 (draft)

A vault is a folder of markdown files describing one campaign's source material,
what has happened at the table, and ideas generated for it. This document is the
contract between ingestion and everything that reads a vault.

Design aims, in priority order:

1. A model can find the right file from an index without opening everything.
2. Every fact from a book can be traced to a page.
3. Nothing in the format assumes a particular game system.
4. A human can read and edit it in any text editor. Obsidian works but is not required.

## 1. Layout

```
my-campaign/
├── vault.yaml               vault metadata
├── INDEX.md                 generated: entry point, counts, links to type indexes
├── _index/                  generated: one file per type, one line per entity
│   ├── npc.md
│   └── …
├── sources/                 one file per ingested book
│   └── drowned-abbey.md
├── canon/                   what the books say
│   ├── npc/
│   ├── location/
│   ├── faction/
│   ├── creature/
│   ├── item/
│   ├── scene/
│   ├── lore/
│   └── hook/
├── table/                   what happened at this table
│   ├── party.md
│   ├── sessions/
│   ├── notes/
│   └── prep/                prep sheets (free-form, not validated)
├── ideas/                   generated material, same type folders as canon/
└── .ingest/
    └── manifest.json        ingestion progress
```

Files marked *generated* are rebuilt by `build_index.py` and never edited by hand.

## 2. The three layers

| Layer | Contains | Written by | Rule |
|---|---|---|---|
| `canon/` | Content from ingested books | `ingest-book` only | Nothing invented. Every fact cited. |
| `table/` | Session logs, party, changes the GM has made | `log-session`, or the GM | Overrides canon where they disagree. |
| `ideas/` | Generated encounters, NPCs, hooks | Prep skills | Always marked as generated. Never cited as a source. |

Reading order for "what is true at this table": table note, then canon, then ideas
only if `status: used`.

Nothing moves between layers. When an idea is used in play, the session log records
it and the idea's status becomes `used`. It does not become canon.

## 3. Entity types

Eight types. They describe narrative roles, not rules objects.

| Type | Use for |
|---|---|
| `npc` | A named individual with motives. |
| `location` | A place at any scale: a region, a town, a room. |
| `faction` | A group with shared goals: a guild, a cult, a crew, a corporation. |
| `creature` | A kind of adversary or being, as opposed to a named individual. |
| `item` | An object that matters: treasure, a clue, a ship, a relic. |
| `scene` | A situation written to be played: an encounter, a set piece, a puzzle, a negotiation. |
| `lore` | Background: history, religion, culture, setting-specific rules, random tables. |
| `hook` | A reason to go somewhere or do something: a rumour, a job, a lead. |

Anything that does not fit goes in `lore` with tags. Player options such as
ancestries, classes or playbooks are `lore` tagged `player-option`. New types need a
format version bump.

## 4. Identity and files

- An entity's ID is `<type>/<slug>`, for example `npc/vessa-thorn`.
- The slug is lowercase ASCII, words joined by hyphens, with a leading "the", "a" or
  "an" dropped: "The Brine Choir" is `faction/brine-choir`.
- The file lives at `<layer>/<type>/<slug>.md`.
- IDs are unique within a layer. An idea may reuse a canon ID only when it is a
  variant of that entity, and must say so in `based_on`.
- If two different entities would get the same slug, add a qualifier:
  `location/old-mill-harrowick`.

## 5. Frontmatter

### Required on every entity

```yaml
id: npc/vessa-thorn
type: npc
name: Vessa Thorn
layer: canon
summary: Innkeeper at the Gilded Eel who launders money for the Tide Court.
sources:
  - {source: drowned-abbey, pages: [12, 47]}
```

`summary` is one sentence, at most 160 characters. It is what the indexes show, so
it should let a reader decide whether to open the file.

`sources` is required in `canon/` and forbidden in `ideas/`.

### Optional on every entity

```yaml
aliases: [The Grey Widow]
tags: [innkeeper, tide-court, harrowick]
system: dnd5e            # free string. Omit when the entity has no rules content.
related: [faction/tide-court, location/gilded-eel]
visibility: gm           # gm (default) | player-safe
```

`related` lists IDs. Links are one-directional in the file; `build_index.py` works
out the reverse links.

### Optional by type

| Type | Fields |
|---|---|
| `npc` | `role`, `location`, `faction`, `status` (alive, dead, missing, unknown) |
| `location` | `kind` (region, settlement, site, room…), `parent`, `exits` |
| `faction` | `base`, `leader` |
| `creature` | `threat` |
| `item` | `holder`, `location` |
| `scene` | `kind` (combat, social, exploration, puzzle, chase…), `location`, `participants`, `threat`, `chapter` |
| `lore` | `kind` (history, religion, rule, table, player-option…) |
| `hook` | `leads_to`, `given_by` |

Fields that point at other entities hold IDs.

`threat` is one of `trivial`, `low`, `mid`, `high`, `boss`. It is a rough reading of
how the book presents the thing, not a rules calculation. Leave it out when the book
gives no sense of it.

### Extra fields in `ideas/`

```yaml
layer: ideas
status: draft            # draft | used | discarded
generated: 2026-11-16
based_on: [location/sunken-crypt, faction/tide-court]
```

## 6. Body

### Sections

Use these headings where the content exists. Skip empty ones. Do not add others
without good reason; put odd material under `## Notes`.

| Type | Sections |
|---|---|
| `npc` | Description · Wants · Secrets · Relationships · In play · Stat block |
| `location` | Description · Features · Occupants · Secrets · Exits · Read-aloud |
| `faction` | Description · Goals · Members · Resources · Secrets |
| `creature` | Description · Behaviour · Tactics · Stat block |
| `item` | Description · Properties · History · Stat block |
| `scene` | Setup · Read-aloud · What happens · Outcomes · Mechanics |
| `lore` | Summary · Detail |
| `hook` | The hook · Truth behind it · Where it leads |

### Citations

In `canon/`, every bullet or paragraph ends with its source:

```markdown
- Launders money for the Tide Court through the inn's cellar trade. [drowned-abbey p.47]
```

The form is `[<source-id> p.<page>]` or `[<source-id> pp.<first>–<last>]`. Page
numbers are PDF page numbers, which is what the GM will type into a viewer.

A fact with no citation fails validation in `canon/`.

### Paraphrase by default

Canon text is written in the vault's own words: short, bulleted, aimed at a GM
mid-session. Two things are kept verbatim:

**Stat blocks and other rules text**, in a fenced block that says what system it is:

````markdown
```statblock system=dnd5e source=drowned-abbey page=62
(exact text from the book)
```
````

Nothing parses the inside of this block. That is what keeps the format
system-agnostic.

**Read-aloud text**, in a callout:

```markdown
> [!read-aloud] [drowned-abbey p.14]
> (exact text from the book)
```

### Links

Link to other entities with `[[type/slug]]` or `[[type/slug|display text]]`. Link
the first mention in each section.

### Conflicts

When two sources disagree, keep both and flag it:

```markdown
> [!conflict]
> - The abbey flooded forty years ago. [drowned-abbey p.3]
> - The abbey flooded "within living memory of no one". [harrowick-gazetteer p.21]
```

## 7. Merge rules

`upsert_entity.py` applies these when a fragment arrives for an entity.

1. **Match.** By ID, then by exact name, then by alias, within the same type. A
   likely-but-uncertain match is written as a new entity and listed for review.
2. **Frontmatter lists** (`aliases`, `tags`, `related`, `sources`) are unioned.
3. **Frontmatter scalars** keep the existing value. A differing new value is recorded
   under `## Notes` as "Sources disagree on `field`: kept X; this source gives Y",
   cited to the new source.
4. **`summary`** keeps the existing value unless the fragment sets `summary_replace: true`.
5. **Body sections** are appended to. A bullet identical to an existing one is
   dropped. Nothing is removed.
6. **Stat blocks** from different sources or systems sit side by side.

Canon is append-only for tools. Only the GM deletes, with one exception:
`lk merge <duplicate> <keep>` folds a duplicate that ingestion itself created into
the entity it duplicates, keeps the old name as an alias, deletes the duplicate and
repoints every reference to it.

After a run, upsert makes a second pass over everything it touched: a `[[Name]]`
link or an ID that misses only by a leading article is pointed at the entity that
now exists.

### Fragments

Upsert's input. A fragment file is a run of entities, each opening with its own
`---` frontmatter block, in the same format as an entity file with these
differences:

- `type` and `name` are required; `summary` is required only for a new entity.
- `id` is optional (derived from type and name); `layer` comes from the command
  (`canon` unless `--layer ideas`).
- `sources` is optional and is derived from the citations in the body.
- Any subset of fields and sections may appear. Text before the first `##`
  heading goes into the type's first section.
- `summary_replace: true` lets a fragment overwrite the summary.
- A line of `---` always starts the next fragment, so fragments cannot use it as a
  horizontal rule.

## 8. Other files

### `vault.yaml`

```yaml
format: 1
name: The Drowned Coast
systems: [dnd5e]
created: 2026-11-16
```

### `sources/<source-id>.md`

```yaml
id: drowned-abbey
title: The Drowned Abbey
kind: adventure          # adventure | setting | bestiary | rulebook | supplement | other
system: dnd5e
pages: 64
file_hash: sha256:…      # identifies the PDF without storing it
ingested: 2026-11-16
```

The body holds the chapter outline with page ranges and a short summary of each
chapter. This is the file that answers "what is this book and how is it organised".

### `table/sessions/<date>-<n>.md`

Frontmatter: `date`, `number`, `present` (entity IDs that appeared), `changed`
(entity IDs whose state changed). Body: what happened, in order, and open threads.

### `table/notes/<type>--<slug>.md`

A note about one canon entity: `about: npc/vessa-thorn`. Holds this table's changes
and current state. It overrides the canon file where they differ.

### `table/party.md`

The player characters, what they know, what they carry, who they have met.

### `_index/<type>.md`

One row per entity across all layers:

```markdown
| ID | Name | Layer | Summary | Tags | Sources |
```

### `INDEX.md`

Vault name, sources, counts per type and layer, links to each type index, and the
five most recent sessions. A reader starts here.

### `.ingest/manifest.json`

```json
{
  "sources": {
    "drowned-abbey": {
      "chunks": [
        {"name": "Chapter 1", "pages": [5, 18], "status": "done", "entities": 14},
        {"name": "Chapter 2a", "pages": [19, 33], "status": "pending"}
      ],
      "flagged_pages": [22, 23]
    }
  }
}
```

`status` is `pending`, `done` or `failed`. `flagged_pages` are pages whose extracted
text looked unreliable and should be read as images.

## 9. Digest

`build_digest.py` produces a small set of files for upload to a Claude Project:
`INDEX.md`, the type indexes, the source outlines, and one bundle per type with every
entity concatenated under its ID as a heading. `table/` is bundled separately so it
can be re-uploaded after each session without touching the rest.

## 10. Validation

`validate.py` fails a vault when:

- an entity lacks a required field, or `id` does not match its path;
- `type` or `layer` is not one from this document;
- a canon entity has an uncited fact, or cites a source with no file in `sources/`;
- a cited page is outside the source's page count;
- an ideas entity has `sources`, or lacks `status` and `generated`;
- an ID in `related` or a typed field points at nothing;
- two entities in a layer share an ID.

It warns when a summary is over 160 characters, an entity has no inbound or outbound
links, or two entities of one type have near-identical names.

## 11. Privacy

A vault contains text from books its owner bought. It is for that GM's own use. The
repo's `.gitignore` excludes vaults, and no tool uploads one anywhere.

## 12. Example

`canon/npc/vessa-thorn.md` (invented for this document):

````markdown
---
id: npc/vessa-thorn
type: npc
name: Vessa Thorn
layer: canon
summary: Innkeeper at the Gilded Eel who launders money for the Tide Court.
aliases: [The Grey Widow]
tags: [innkeeper, tide-court, harrowick]
system: dnd5e
role: innkeeper
location: location/gilded-eel
faction: faction/tide-court
status: alive
related: [npc/brother-alden]
sources:
  - {source: drowned-abbey, pages: [12, 47, 62]}
---

## Description
- Tall, grey-haired, never seen without a ring of cellar keys. [drowned-abbey p.12]
- Runs [[location/gilded-eel|the Gilded Eel]] and knows every boat crew in town. [drowned-abbey p.12]

## Wants
- To buy her way out of the [[faction/tide-court]] before they stop needing her. [drowned-abbey p.47]

## Secrets
- Launders the Court's money through the inn's cellar trade. [drowned-abbey p.47]
- Knows which crypt door [[npc/brother-alden]] sealed, and why. [drowned-abbey p.47]

## In play
- Will trade the crypt's location for safe passage out of Harrowick. [drowned-abbey p.47]

## Stat block
```statblock system=dnd5e source=drowned-abbey page=62
(exact text from the book)
```
````

## 13. Open points for version 1

- Whether `table/prep/` sheets should get frontmatter and an index entry.

- Whether `scene` needs an explicit ordering field for linear adventures, or
  `chapter` plus page order is enough.
- Whether maps and handout images get a type, or stay as page references.
- Whether citations should also carry the book's printed page number where it
  differs from the PDF page.
