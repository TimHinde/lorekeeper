---
name: ask-the-vault
description: Answer a GM's questions about their campaign from a lorekeeper vault, with page citations. Use when the user asks who, what, where or why about their campaign, adventure or setting ("who knows about the cult?", "what's in the crypt?", "what did the party promise Maren?") and a lorekeeper vault or vault zip is available.
---

# Answer questions from the vault

## Setup

Find the CLI: `scripts/lk.py` inside this skill's folder, or two folders up from it.

```bash
SKILL_DIR="<this skill's base directory>"
LK="python3 $(ls "$SKILL_DIR"/scripts/lk.py "$SKILL_DIR"/../../scripts/lk.py 2>/dev/null | head -1)"
```

Missing dependency: `pip install PyMuPDF PyYAML` (add `--break-system-packages` if needed).

Find the vault: an attached zip (`$LK unpack <zip> --dest .`), or a reachable folder
with a `vault.yaml`. If there is none, say so and offer to ingest a book with the
ingest-book skill. If the user has uploaded a lorekeeper digest to a Claude
Project instead, the same rules apply: read `00-index.md` first, then the bundles.

## How to look things up

Do not read the whole vault. Narrow down:

1. Read `INDEX.md` once per conversation: sources, counts, recent sessions.
2. `$LK find <words> --vault <dir>` searches names, aliases, tags, summaries and
   text; add `--type npc` (or any type) or `--tag <tag>` to narrow it. It prints
   `id, layer, name, summary`.
3. `$LK show <id-or-name> [more…] --vault <dir>` prints whole entities, each with
   any table note about it.
4. Follow the trail: `related` and other ID fields, `[[links]]` in the body, and
   `_index/backlinks.md` for what points *at* an entity ("who knows about X" is
   usually a backlinks question).
5. For "what happened", read `table/sessions/` (newest first) and `table/party.md`.

A type index (`_index/npc.md` etc.) is a good way to scan everything of one kind.

## What is true

The vault has three layers. When they disagree:

1. **`table/`** wins: session logs and notes record what changed at this table.
   A table note's "Changes from canon" overrides the canon file.
2. **`canon/`** is what the books say.
3. **`ideas/`** is generated material. Treat it as true only if `status: used`;
   mention `draft` ideas only as ideas.

If two sources disagree (a `[!conflict]` callout or a "Sources disagree" note),
give both.

## Answering

- Lead with the answer, briefly. GMs ask mid-prep or mid-session.
- Cite canon facts with the page: *Maren pays 20 silver for the wreck (salt-wake
  p.3)*. Name the entity when it helps the GM find it again.
- Say plainly when the vault does not cover something. Do not fill gaps from what
  you may know about the published product; if you add your own suggestion, label
  it as yours. That keeps canon and invention apart, which is the point of the vault.
- **Spoilers:** if the user says players can see the answer, use only material
  whose `visibility` is `player-safe`, plus things the party has learned according
  to `table/party.md` and the session logs. Without that, assume the user is the GM.

If an answer reveals something worth keeping, such as a decision the GM makes
while asking, offer to record it with the log-session skill rather than editing
canon.
