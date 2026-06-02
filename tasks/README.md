# tasks/ — your benchmark corpus (local, git-ignored)

This directory holds the tasks mined from **your own** coding-agent history by the
`pr-task-miner` skill. Its contents are personal (your code diffs, your prompts)
and are **git-ignored** — only this README is tracked. Nothing here is committed.

Each task is a folder produced by `pr-task-miner`:

```
tasks/<task_id>/
├── spec.md           # the clean task you hand to an agent (you synthesize this)
├── reference.diff    # your original merged PR diff — the comparison baseline
├── source-prompts.md # your verbatim chat turns, for traceability
└── meta.json         # provenance: repo, base/head commit, mapping confidence
```

`<task_id>` is usually `<repo>/<pr-slug>`, so packages nest by repository.

To populate this directory, run the `pr-task-miner` skill (see
`skills/pr-task-miner/SKILL.md`). To run agents against these tasks and compare
results, see `skills/bench-runner` and `skills/bench-comparator`.
