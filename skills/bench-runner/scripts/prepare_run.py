#!/usr/bin/env python3
"""Prepare an isolated run of one task for a coding agent.

Scaffolding only — it does NOT invoke any agent. It cuts a clean git worktree at
the task's base_commit so the agent starts from the exact same code the original
task started from, and lays out the prompt. You then run whatever agent/mode you
want inside the worktree, by hand. Afterwards, `collect_run.py` harvests the diff.

    tasks/<id>/  --(prepare)-->  worktree @ base_commit  +  runs/<id>/<run>/run-meta.json
                                      (you run the agent here)
                                          --(collect)-->  runs/<id>/<run>/result.diff

Usage:
    python3 prepare_run.py --task tasks/<task_id> --run-label claude-opus-4.8
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def git(repo, *args):
    out = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="path to tasks/<task_id>")
    ap.add_argument("--run-label", required=True,
                    help="identifies this agent/mode, e.g. claude-opus-4.8 or codex-gpt5")
    ap.add_argument("--runs-root", default="./runs")
    ap.add_argument("--worktree-root", default=os.path.expanduser("~/.bm-worktrees"))
    args = ap.parse_args()

    task_dir = os.path.abspath(args.task)
    meta = json.load(open(os.path.join(task_dir, "meta.json"), encoding="utf-8"))
    task_id = meta["task_id"]
    repo = meta["source"]["local_path"]
    base = meta["git"]["base_commit"]

    if not (repo and os.path.isdir(os.path.join(repo, ".git"))):
        sys.exit(f"task repo not a local git checkout: {repo}")

    run_dir = os.path.abspath(os.path.join(args.runs_root, task_id, args.run_label))
    if os.path.exists(os.path.join(run_dir, "run-meta.json")):
        sys.exit(f"run already exists: {run_dir} (pick a different --run-label)")
    os.makedirs(run_dir, exist_ok=True)

    wt = os.path.join(args.worktree_root, task_id.replace("/", "__"), args.run_label)
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    if os.path.exists(wt):
        sys.exit(f"worktree path already exists: {wt}")
    git(repo, "worktree", "add", "--detach", wt, base)

    # The prompt lives in the run dir, NOT the worktree, so it never pollutes the diff.
    spec_src = os.path.join(task_dir, "spec.md")
    prompt_path = os.path.join(run_dir, "prompt.md")
    with open(spec_src, encoding="utf-8") as fh:
        spec = fh.read()
    with open(prompt_path, "w", encoding="utf-8") as fh:
        fh.write(spec)

    run_meta = {
        "task_id": task_id,
        "run_label": args.run_label,
        "status": "prepared",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "worktree": wt,
        "repo": repo,
        "base_commit": base,
        "prompt": prompt_path,
        # fill these in via collect_run.py flags after you run the agent:
        "agent": None, "model": None, "mode": None,
        "wall_seconds": None, "turns": None, "cost_usd": None, "notes": None,
    }
    with open(os.path.join(run_dir, "run-meta.json"), "w", encoding="utf-8") as fh:
        json.dump(run_meta, fh, ensure_ascii=False, indent=2)

    print(f"prepared run: {run_dir}")
    print(f"  worktree (clean @ {base[:8]}): {wt}")
    print(f"  prompt:   {prompt_path}")
    print()
    print("NEXT — run your agent inside the worktree, e.g.:")
    print(f"  cd {wt}")
    print(f"  claude -p \"$(cat {prompt_path})\"        # or: codex exec, or any agent/mode")
    print("Then harvest the result:")
    print(f"  python3 {os.path.dirname(os.path.abspath(__file__))}/collect_run.py --run {run_dir} \\")
    print("      --agent claude-code --model claude-opus-4-8 --wall-seconds <N> --turns <N>")


if __name__ == "__main__":
    main()
