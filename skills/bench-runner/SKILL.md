---
name: bench-runner
description: Run a mined task (from pr-task-miner) against a coding agent in an isolated git worktree, then harvest the result as a comparable diff. Scaffolding only — it does NOT invoke the agent; you run whatever agent/mode you want by hand in the prepared worktree, keeping it fully agent-agnostic. Use when the user wants to execute a benchmark task with Claude Code, Codex, or different models/modes and capture the output for side-by-side comparison.
---

# Bench Runner

Step 2 of the benchmark pipeline (step 1 is `pr-task-miner`). It takes a task
package from `tasks/<task_id>/` and produces a **run**: one agent's attempt at the
task, captured as a diff + metadata, under `runs/<task_id>/<run_label>/`.

It is **scaffolding only and agent-agnostic.** It does not run any agent — it cuts
a clean worktree at the task's `base_commit`, hands you the prompt, and you run
whatever agent or mode you want by hand. Then it harvests the diff. This keeps the
runner from having to know about any agent's headless flags or auth.

```
tasks/<id>/  --prepare-->  worktree @ base_commit   (you run the agent here, by hand)
                                  --collect-->  runs/<id>/<run_label>/{result.diff, run-meta.json}
```

## Data layout
- `tasks/<id>/`   — the corpus (read-only input from pr-task-miner)
- `runs/<id>/<run_label>/` — one attempt. `run_label` names the agent/mode, e.g.
  `claude-opus-4.8`, `codex-gpt5`, `claude-haiku-no-thinking`.
- worktrees live under `~/.bm-worktrees/` so they never touch the real repo or
  the `runs/` tree.

## Workflow

### 1. Prepare
```
python3 scripts/prepare_run.py --task tasks/<task_id> --run-label <agent-or-mode>
```
Cuts a detached worktree at `base_commit`, copies `spec.md` to
`runs/<id>/<run_label>/prompt.md` (kept **outside** the worktree so it can't
pollute the diff), and prints the next commands.

### 2. Run the agent yourself
Inside the printed worktree path, run the agent with `prompt.md` as the task. The
agent must NOT see `reference.diff` — that's the gold answer. Examples:
```
cd <worktree>
claude -p "$(cat <run_dir>/prompt.md)"        # or codex exec, or a different model/mode
```
Run each agent/mode you want to compare as its own `run_label`, each from a fresh
`prepare`.

### 3. Collect
```
python3 scripts/collect_run.py --run runs/<task_id>/<run_label> \
    --agent claude-code --model claude-opus-4-8 --mode default \
    --wall-seconds 240 --turns 11 --cost-usd 0.62 --notes "asked 1 clarifying q"
```
Stages everything in the worktree (so committed, staged, unstaged, and new files
all count) and writes `result.diff` = `git diff base_commit`, plus diff stats. The
metadata flags are optional but they're what makes the later comparison rich
(cost/time/turns are the efficiency signals a plain pass-rate benchmark misses).
Add `--cleanup` to remove the worktree when done.

## Notes
- The metadata is hand-entered because the run is manual — capture what the agent
  CLI reports (token cost, turns, wall time) when you have it; leave blank if not.
- `result.diff` is intentionally the same shape as the task's `reference.diff`, so
  the comparator can lay them side by side, with `reference.diff` as one column
  (your original work) and each run as another.
- Comparing/scoring is a separate skill (`bench-comparator`). This skill stops at
  producing runs.
