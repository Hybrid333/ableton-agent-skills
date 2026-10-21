---
name: finish-the-track
description: "Score every unfinished Ableton set by how close it is to done and name the two or three nearest to finished — with the one concrete next step per set. Use for 'what should I finish next', 'which tracks are almost done', 'overview of my projects', 'I keep starting new ones', or when planning a week of music work."
---

# Finish the Track

Answers the only question that matters with 70 half-finished sets: **which one
do I finish next?**

Tool: [`tools/finish_the_track.py`](../../tools/finish_the_track.py)
(needs `als_lib.py` next to it, otherwise stdlib only).

---

## Run it in two steps — always

Walking a mounted folder can take **~40 seconds** on its own, which eats most of
a typical agent shell timeout. Build the list first, then score it:

```bash
# step 1 — file list (separate call, otherwise timeout)
find "<Music>" "<Documents/Ableton>" -name Backup -prune -o -name "*.als" -print > als_list.txt

# step 2 — score
cd tools
export PYTHONDONTWRITEBYTECODE=1
python3 finish_the_track.py als_list.txt --top 3 --json ftt.json
```

With more than ~50 sets, split the list (`head`/`tail`) into two calls — 67 sets
take about 25 seconds of compute.

Useful switches:

- `--all` — also older versions with the same name (default: newest only)
- `--include-templates` — rank bought templates too
- `--exclude REGEX` — skip paths/names, repeatable

---

## How it scores

| Points | Criterion |
|---|---|
| 30 | Arrangement — length in bars **and** whether the set of playing tracks changes |
| 25 | Instruments — share of tracks with notes that also have an instrument |
| 15 | Structure — locators present, named, sensible section lengths |
| 15 | Production — automation envelopes with real data, a master chain |
| 15 | Output — a bounce exists next to the project |

Stages: **sketch** (<25) · **loop** (25–44) · **arrangement** (45–64) ·
**mix** (65–84) · **finished** (85+).

**Blockers don't lower the score.** A set can be 90% done and still not open
because a sample is missing. That's a different problem from being unfinished
and is reported separately.

---

## Traps real data exposed

**Bought templates clog the list.** Template and demo projects are finished by
definition and otherwise end up on top while the user's own half-finished tracks
sink. They're marked `[Template]` and taken out of the shortlist. Anything under
`/Templates/` or `/Factory Packs/` counts as a template too.

**`._Name.als` are not sets.** AppleDouble resource forks that travel along when
copying from a Mac. Unfiltered they show up as "broken" — ten at once in one
real library.

**Versioned duplicates.** `Track [2020-06-03 121210].als` — often three to five
side by side. By default only the newest per base name counts.

**A 116-bar set can still be a "loop".** If the same tracks always play, length
isn't arrangement. That's exactly why texture variety goes into the score and
not just bar count.

---

## How to report back

**Don't pass the table through.** The table is raw material. What the user needs:

1. **Two or three sets**, not ten. More choice means less deciding.
2. **The one next step per set**, not the whole list. "Load instruments on 10
   tracks" is an evening. "Automation, master chain and bounce" is an excuse.
3. **How old the set is.** Something untouched for 1,200 days is a different
   decision from something from yesterday — maybe letting go is the right answer.
   You may say so.
4. **Blockers first**, if there is one. A missing sample costs five minutes with
   `ableton-set-doctor` and otherwise blocks the whole evening.

If a set scores over 85: say it's done and hand over to `mix-check` instead of
tweaking further.

---

## Run it weekly

External accountability is the strongest lever against abandoned tracks. After
the first run, offer to set it up as a recurring task — e.g. Monday morning,
with the top 3 as a short message. Offer once, in one sentence; never set it up
unasked.
