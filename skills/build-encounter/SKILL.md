---
name: build-encounter
description: Design encounters, scenes and set pieces for a GM's campaign, grounded in their lorekeeper vault and kept separate from published canon. Use when the user wants encounter ideas, a fight, a social scene, a trap or a complication for a place, faction or session, and a lorekeeper vault is available.
---

# Build encounters from the vault

Here you are allowed to invent, which ingestion never is. The rule that keeps the
vault trustworthy: **everything you create goes to `ideas/`, never `canon/`**, and
says what it was based on.

## Setup

```bash
SKILL_DIR="<this skill's base directory>"
LK="python3 $(ls "$SKILL_DIR"/scripts/lk.py "$SKILL_DIR"/../../scripts/lk.py 2>/dev/null | head -1)"
```

Find the vault as the ask-the-vault skill does: an attached zip
(`$LK unpack <zip> --dest .`) or a reachable folder with `vault.yaml`.

## 1. Gather the ingredients

Work out what the encounter is for: a place, a faction's move, a gap between two
scenes, a random encounter, a boss fight. Then pull what the vault has:

- the location: `$LK show <location-id>` and its `parent`, `exits`, occupants;
- who is there or nearby: `$LK find --type npc <place>`, `--type faction`, `--type creature`;
- what the book already planned there: `$LK find --type scene <place>`;
- the state of play: `table/party.md`, the latest one or two `table/sessions/`,
  and any table notes on these entities (`show` prints them).

Party size, level and the game system decide difficulty. Use what the vault and
the session logs say; ask only if they are missing and it matters for this request.

## 2. Offer options

Give **two or three distinct options** unless the user asked for one. Make them
differ in kind, not in dressing: a fight, a negotiation, a chase, a dilemma. For each:

- **Pitch:** one or two sentences.
- **Built from:** the canon it uses, with page citations (*the Choir meets under
  the pier at low water, salt-wake p.6*).
- **How it runs:** setup, what the opposition wants, two or three beats, how it can end.
- **Stakes and fallout:** what changes in the world for each outcome.
- **Mechanics:** point to stat blocks already in the vault by entity and page.
  Do not invent rules numbers for a specific system unless the user asks; if they
  do, label them as homebrew.

Keep it to what a GM can run from: bullets, not prose.

## 3. Save the one they want

When the user picks one (or asks you to keep them all), write it as a fragment
and upsert it into `ideas/`:

````markdown
---
type: scene
name: Ambush under the Pier
summary: Choir lookouts and a Silt Lurker try to drown the party at low water.
kind: combat
location: location/brinemouth
participants: [faction/brine-choir, creature/silt-lurker]
based_on: [faction/brine-choir, scene/the-bell-ritual]
threat: mid
tags: [generated, low-water]
---
## Setup
- …

## What happens
- …

## Outcomes
- …
````

```bash
$LK upsert <file> --vault <dir> --layer ideas
```

Ideas take no citations and no `sources`; upsert adds `status: draft` and the
date. New NPCs or creatures you invent for it are separate `ideas/` fragments in
the same file. Then `$LK validate --vault <dir>` and fix any errors.

When an idea is used at the table, the log-session skill marks it `used`. It never
moves to `canon/`.

If the vault came as a zip, pack it again at the end (`$LK pack --vault <dir>`)
and send it, so the user keeps the saved ideas.
