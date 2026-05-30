---
name: pr-task-miner
description: Mine local Claude Code transcripts for PR-bounded coding tasks and turn them into reusable, high-quality benchmark examples. Anchors each task to a pull request — the PR's squash commit gives a clean base/after, the feature branch + timestamp tie the chat session to it, and the merged diff becomes the reference answer. Use when the user wants to extract real tasks from their own history to compare coding agents or modes side by side.
---

# PR Task Miner

Turn your real work into benchmark examples. Each example is a **task package**:
a clean spec, the exact starting commit, and the gold-standard diff you actually
shipped — so you can replay the task with a different agent or mode and judge the
results side by side.

The unit is a **pull request**, because a PR gives all three things for free:

- **task boundary** = the PR (solves chat-session segmentation: one session can
  hold several tasks, one task can span sessions)
- **starting code** = the PR's squash commit's parent (`git checkout base_commit`)
- **reference answer** = `git diff base..head`, the diff you merged

The goal is **a few high-quality examples, not a large benchmark.**

## Division of labor

Scripts do the deterministic work; the model does the judgment work.

- **Scripts** (`scripts/`): scan transcripts, find PR candidates, resolve git
  commits, emit the diff + prompts + provenance. Cheap, reproducible.
- **You (the model)**: pick which candidates are worth keeping, and synthesize
  `spec.md` from the messy chat + the PR diff. This can't be done deterministically.

## Workflow

### 1. Discover candidates
```
python3 scripts/discover_tasks.py --pretty
```
Emits a JSON array of PR-bounded candidates, each with a `confidence` and a `why`.
Mapping is anchored on, in order of reliability:
1. **commit-time within the session span** (timezone-normalized — the sturdiest signal)
2. **feature-branch tokens matching the squash-commit subject**
3. **pr-link number** (least reliable — it can be stale or duplicated across sessions, so it only breaks ties)

Prefer `high`-confidence, `local-git` candidates. `github-needed` candidates
(local repo gone, only a GitHub PR URL survives) are surfaced but not yet
buildable — they need a `gh` fetch step that v1 does not implement.

### 2. Triage with the user
Show the candidate list and let the user pick which to keep. Good benchmark
examples are self-contained and judgeable; skip ones that are mostly exploration
or pure discussion. Don't auto-accept everything — borderline calls are exactly
what a human should make.

### 3. Build the package
Pipe one chosen candidate into the builder:
```
python3 scripts/discover_tasks.py \
  | python3 -c "import json,sys; cs=json.load(sys.stdin); print(json.dumps(next(c for c in cs if c['task_id']=='<TASK_ID>')))" \
  | python3 scripts/build_task_package.py --out ./tasks
```
This writes `tasks/<task_id>/` (the corpus) with `reference.diff`,
`source-prompts.md`, and `meta.json`. It deliberately does **not** write `spec.md`.

### 4. Synthesize spec.md (your job)
Read `source-prompts.md` (the user's verbatim turns) and skim `reference.diff`
(what actually shipped). Optionally pull the PR body via `gh pr view <n> --repo
<repo>` for a cleaner intent source. Then write `tasks/<task_id>/spec.md` — a
clean task the user could hand to a fresh agent, starting from `base_commit`.

Hold these principles when writing the spec:

- **Altitude**: capture the goals and constraints, not a step-by-step of the
  original chat. Compress requirement-negotiation turns into their settled outcome.
- **Don't leak the answer**: where the original user left a choice open (a name,
  wording, which example to use), keep it open in the spec. Replays should be
  judged on the *quality* of those choices vs. the reference, not on guessing
  exact strings. Call out what you left open in a short "Deliberately left open"
  section.
- **Be honest about shape**: real tasks are often mixed (a refactor + a doc
  rewrite + a data swap). Say so in the spec rather than pretending it's one clean
  thing. If a task is mostly live back-and-forth with no settle-able spec, flag it
  as a poor fit instead of forcing it.

A finished task package therefore contains four files: `spec.md` (your synthesis),
`reference.diff`, `source-prompts.md`, and `meta.json`. See `tasks/README.md` for
the package layout. The corpus under `tasks/` is local, personal data and is
git-ignored — it is never committed.

## Replaying (out of scope for this skill)
This skill is the **generator**. Actually running a fresh agent against a `spec.md`
and showing the two diffs side by side is a separate step — keep that concern out
of here.

## Known limitations
- Only `local-git` candidates are buildable; `github-needed` needs a `gh` fetch.
- Mapping is session↔PR; a PR built across multiple sessions may under-count
  prompts (only the matched session's turns are captured).
- `spec.md` quality is the whole ballgame and is not automatable — always
  human-review it before trusting an example.
