---
name: prep-session
description: Prepare a GM for their next session from a lorekeeper vault — where the party is, what is likely to happen, who they will meet, open threads and quick references. Use when the user asks to prep, plan or get ready for the next session (or a specific one) and a lorekeeper vault is available.
---

# Prep the next session

The output is a **prep sheet**: one page a GM can run from. Short, scannable,
every canon fact traceable to a page.

## Setup

```bash
SKILL_DIR="<this skill's base directory>"
LK="python3 $(ls "$SKILL_DIR"/scripts/lk.py "$SKILL_DIR"/../../scripts/lk.py 2>/dev/null | head -1)"
```

Find the vault as the ask-the-vault skill does.

## 1. Where things stand

- `INDEX.md`, then the latest one or two `table/sessions/` (open threads first)
  and `table/party.md`.
- Table notes on anything the last session changed (the `changed` list in the
  session's frontmatter): `$LK show <id>` prints the note with the entity.
- If there are no sessions yet, this is session one: start from the adventure's
  opening (the source outline in `sources/<id>.md`, and its first scenes).

## 2. What is likely next

- The scenes the party is heading for: `$LK find --type scene` plus the place
  names from the open threads; for linear adventures follow `chapter` and page order.
- Who they will probably meet: NPCs and factions tied to those scenes and places
  (`participants`, `occupants`, `_index/backlinks.md`).
- What is moving off-screen: factions with goals in play, hooks not yet taken,
  `draft` ideas the GM saved for this stretch.

Ask the user what they expect only if the threads point in very different
directions; otherwise prep for the two most likely.

## 3. The prep sheet

Use these sections, skip any that are empty:

1. **Recap**: three to five bullets, written so the GM can read them aloud.
2. **Open threads**: what the party is chasing; what is chasing them.
3. **Likely scenes**: for each, location, the point of the scene, key read-aloud
   (short, cited), what can go wrong, where it leads.
4. **People**: for each NPC likely to appear, one line each for *wants*, *secret*,
   *voice or manner*, and their current state from table notes. Cite pages.
5. **Off-screen**: what factions do this session if left alone.
6. **Stat blocks to have open**: entity IDs and pages.
7. **Ideas**: one or two optional complications, clearly marked as yours (or
   existing `draft` ideas from `ideas/`). Offer to save new ones with the
   build-encounter skill.
8. **Ask the table**: anything the GM needs to decide or check before play.

Precedence as always: table notes over canon, canon over ideas.

## 4. Deliver

Give the prep sheet in the reply. If the user wants to keep it, also save it in
the vault at `table/prep/<date>.md` (create the folder if needed) and, if the vault
came as a zip, pack it again and send it.
