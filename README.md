# agent-bench-kit

Turn your own coding-agent history into a small, high-quality benchmark — then
use it to compare agents and modes side by side.

Public benchmarks (SWE-bench and friends) measure GitHub issues, not *your* work,
and they leak into training sets. `agent-bench-kit` mines tasks from your own
local Claude Code / Codex transcripts, anchors each one to a real pull request,
and lets you replay it with a different agent or model and **judge the results
yourself**. The goal is a handful of examples you trust — not a big leaderboard.

## Why a pull request is the unit

Anchoring each task to a PR solves three hard problems for free:

- **Task boundary** — one chat session can hold several tasks, and one task can
  span sessions. A PR is a clean, self-contained unit of work.
- **Starting code** — the PR's squash-commit parent is the exact state the work
  began from. Check it out and any agent starts on equal footing.
- **Reference answer** — the merged diff is what *you* actually shipped, a natural
  baseline to compare new attempts against.

## No score, on purpose

This kit never assigns a number or declares a winner. Judging whether one diff is
"better" than another is exactly what an LLM grader does unreliably and what a
human who understands the task does well. So the tooling's job is to make the
artifacts **legible** — put the diffs side by side, surface light navigation
signals (files touched, ± lines, turns, wall time, cost), and point attention at
what differs. You decide which result is better.

Those efficiency signals (turns / time / cost) are surfaced precisely because a
pass-rate benchmark hides them and they're often what you actually care about —
but they inform, they don't rank.

## The pipeline

Three skills, run in order. Each puts deterministic work in a script and leaves
judgment work to a model.

```
① mine     skills/pr-task-miner/     →  tasks/<id>/          (your corpus)
② run      skills/bench-runner/      →  runs/<id>/<label>/   (one per agent/mode)
③ compare  skills/bench-comparator/  →  runs/<id>/compare.md (side-by-side)
```

### ① pr-task-miner
Scans local transcripts, finds PR-bounded task candidates, and resolves each to a
git base/head commit. Mapping is anchored on commit-time within the chat session,
feature-branch tokens, and the PR link (in that order of reliability). It emits
`reference.diff`, the verbatim prompts, and provenance; you synthesize the clean
`spec.md`.

### ② bench-runner
Scaffolding only — it does **not** invoke any agent, keeping it agent-agnostic. It
cuts an isolated git worktree at the task's base commit and hands you the prompt;
you run whatever agent or mode you want by hand; then it harvests the diff and
metadata into a run.

### ③ bench-comparator
Lays the reference and every run side by side in a `compare.md` with a signals
table and a files-touched matrix, then a model fills in descriptive "what differs"
notes. No score.

## Quickstart

```bash
# ① mine a task into your corpus
python3 skills/pr-task-miner/scripts/discover_tasks.py --pretty      # pick a high-confidence candidate
#   pipe it to build_task_package.py, then write tasks/<id>/spec.md yourself

# ② run each agent/mode you want to compare
python3 skills/bench-runner/scripts/prepare_run.py  --task tasks/<id> --run-label claude-opus-4.8
#   run your agent by hand inside the printed worktree
python3 skills/bench-runner/scripts/collect_run.py  --run runs/<id>/claude-opus-4.8 --model claude-opus-4-8 --turns N

# ③ build the side-by-side report
python3 skills/bench-comparator/scripts/build_comparison.py --task tasks/<id>
#   then fill compare.md's "At a glance" and "Key differences" notes
```

Each skill's `SKILL.md` has the full workflow and the principles behind it.

## Privacy

The mined corpus (`tasks/`) and run outputs (`runs/`) contain **your** code and
prompts. They are git-ignored and never committed — this repository ships only the
tooling. Scrub any task package before sharing it.

## Requirements

- Python 3.9+
- `git` (with worktree support)
- Local Claude Code transcripts under `~/.claude/projects/` (and/or Codex history)
- `gh` (optional) for fetching PRs whose local checkout is gone

## Status & limitations

- Only locally-available git repos are buildable today; transcripts whose repo is
  gone are detected but need a `gh` fetch step that isn't built yet.
- Session↔PR mapping is heuristic; always eyeball the `confidence` and provenance.
- `spec.md` quality is the whole ballgame and is human-reviewed by design.

## License

MIT — see [LICENSE](LICENSE).
