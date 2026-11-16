---
name: log-session
description: Record what happened at the table in a lorekeeper vault — the session log, changes to NPCs, places and factions, what the party learned and gained, and which prepared ideas were used. Use after a game session when the user shares notes, a recap or a transcript, or asks to log, record or update the campaign.
---

# Log a session

The table layer is where this campaign diverges from the books. Never edit
`canon/` to record play; canon stays what the book says, and the table layer
overrides it.

## Setup

```bash
SKILL_DIR="<this skill's base directory>"
LK="python3 $(ls "$SKILL_DIR"/scripts/lk.py "$SKILL_DIR"/../../scripts/lk.py 2>/dev/null | head -1)"
```

Find the vault as the ask-the-vault skill does.

## 1. Read the notes against the vault

The user's notes will be rough. Match every person, place, group and item they
mention to an entity: `$LK find <name>`. Note what is new (someone the party met
who is not in the vault), what changed (dead, moved, angry, revealed), and what
the party learned or got.

If a name matches nothing and the notes do not make clear who it is, list those
at the end rather than guessing.

## 2. Write the session

```bash
$LK session --vault <dir> [--date YYYY-MM-DD] [--title "…"]
```

That creates `table/sessions/<date>-<NNN>.md` with the next number. Fill it in:

- **Frontmatter:** `present`: IDs of entities that appeared; `changed`: IDs whose
  state changed.
- **What happened:** bullets in order, past tense, with `[[type/slug]]` links.
- **Changes to the world:** one bullet per change, linked.
- **Open threads:** what is unresolved, as the GM would put it next session.

## 3. Update what changed

For each entity in `changed`:

```bash
$LK note <id> --vault <dir>
```

That creates or finds `table/notes/<type>--<slug>.md`. Update **Current state**
(replace it: it is "now"), add to **Changes from canon** (what differs from the
book), and append to **History at this table** with the session date. Set
`updated` in its frontmatter.

New people or places the GM invented at the table: write them as `ideas/`
fragments with `status: used` (`$LK upsert <file> --layer ideas`), since they are
not from a book but are now real in this campaign.

Ideas from `ideas/` that were used: set their `status` to `used` (edit the
frontmatter). Ideas the GM dropped can become `discarded`.

Update `table/party.md`: characters, what they know, what they carry, who they
have met.

## 4. Check and deliver

```bash
$LK validate --vault <dir>
$LK index --vault <dir>
```

Fix errors. If the vault came as a zip, `$LK pack --vault <dir>` and send it back.
If the user works from a Claude Project digest, tell them only `table.md` needs
re-uploading: `$LK digest --vault <dir>` rebuilds it.

Close with the open threads list, since that is what next session's prep starts from.
