---
name: bench-comparator
description: Lay out a task's runs side by side for human judgment — the reference (your original work) plus every agent/mode run, with light navigation signals (files touched, +/- lines, turns, time, cost) and an LLM-written "what's different" note. By design it does NOT score or rank; it makes the artifacts scannable so you decide which result is better. Use after bench-runner has produced one or more runs for a mined task.
---

# Bench Comparator

Step 3 (final) of the pipeline: `pr-task-miner` → `bench-runner` → **`bench-comparator`**.

It takes a task's `reference.diff` and all of its runs and produces a scannable
`runs/<task_id>/compare.md` that puts the diffs side by side. The core principle,
held since the project's framing: **no automated score.** The most qualified judge
is the user, who understands the task. This skill's job is to make comparison
*legible* and point attention at what differs — not to declare a winner.

## Workflow

### 1. Build the skeleton (script)
```
python3 scripts/build_comparison.py --task tasks/<task_id> [--runs-root ./runs]
```
Writes `runs/<task_id>/compare.md` and `comparison.json`. The reference (your
original work) is always column zero, every run a further column. The script fills
the deterministic parts:
- a **signals table** (files changed, +/- lines, model, mode, turns, wall time, cost)
- a **files-touched matrix** (which column changed which file, with per-file +/-)
- per-column links to each `result.diff`

### 2. Fill the navigation notes (LLM — your job)
Open each column's diff (`reference.diff` and every `result.diff`) and edit
`compare.md`:
- Replace each **"Key differences vs others"** TODO with one or two *descriptive*
  lines: what only this column did, what it skipped, where it diverged in approach.
- Write the **"At a glance"** note (2-4 sentences) pointing the reader at the real
  differences so they don't have to read every diff.

Strict rule: **describe, don't judge.** Say "only column B refactored the shared
util module" — never "B is better." Adjectives like better/worse/cleaner are the
user's call. If two columns are nearly identical, say so; that's useful navigation.

### 3. Hand it to the user
The user reads `compare.md`, opens the diffs that the notes flag as interesting,
and forms their own judgment — optionally recording it themselves.

## Signals are navigation, not truth
- The numbers (lines, turns, cost) help the user decide *which diffs to read first*,
  not which run "won." A smaller diff isn't automatically better; a cheaper run
  isn't automatically better. Present them flatly.
- Efficiency signals (turns/time/cost) are surfaced because they're exactly what a
  pass-rate benchmark hides and what the user often actually cares about — but they
  inform, they don't rank.

## Notes
- Re-running the script regenerates the deterministic sections and **overwrites**
  the TODO placeholders — fill the notes after the final `build_comparison.py` run,
  or keep them in a separate file if you re-generate often.
- Works with a single run (run vs reference). More runs just add columns.
