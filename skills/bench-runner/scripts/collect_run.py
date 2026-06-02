#!/usr/bin/env python3
"""Harvest the result of a prepared run after the agent has run in the worktree.

Captures the full delta the agent produced (committed, staged, unstaged, and new
files) relative to base_commit, writes it as result.diff, records diff stats, and
folds in any run metadata you pass (model, mode, cost, time, turns).

Usage:
    python3 collect_run.py --run runs/<task_id>/<run_label> \
        --agent claude-code --model claude-opus-4-8 --mode default \
        --wall-seconds 240 --turns 11 --cost-usd 0.62 --notes "asked 1 clarifying q"
    # add --cleanup to remove the worktree afterwards
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def git(repo, *args):
    out = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, timeout=120
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def diff_stat(repo, base):
    raw = git(repo, "diff", "--numstat", base)
    files = ins = dele = 0
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        a, d, _ = parts
        files += 1
        ins += int(a) if a.isdigit() else 0
        dele += int(d) if d.isdigit() else 0
    return {"files_changed": files, "insertions": ins, "deletions": dele}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="path to runs/<task_id>/<run_label>")
    ap.add_argument("--agent")
    ap.add_argument("--model")
    ap.add_argument("--mode")
    ap.add_argument("--wall-seconds", type=float)
    ap.add_argument("--turns", type=int)
    ap.add_argument("--cost-usd", type=float)
    ap.add_argument("--notes")
    ap.add_argument("--cleanup", action="store_true",
                    help="remove the worktree after collecting")
    args = ap.parse_args()

    run_dir = os.path.abspath(args.run)
    meta_path = os.path.join(run_dir, "run-meta.json")
    meta = json.load(open(meta_path, encoding="utf-8"))
    wt = meta["worktree"]
    repo = meta["repo"]
    base = meta["base_commit"]

    if not os.path.isdir(wt):
        sys.exit(f"worktree missing: {wt}")

    # Stage everything (incl. new files) so `git diff <base>` reflects the full
    # delta whether the agent committed, staged, or left changes in the worktree.
    git(wt, "add", "-A")
    result = git(wt, "diff", base)
    with open(os.path.join(run_dir, "result.diff"), "w", encoding="utf-8") as fh:
        fh.write(result)

    stat = diff_stat(wt, base)
    meta.update({
        "status": "collected",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "diff_stat": stat,
    })
    for k in ("agent", "model", "mode", "notes"):
        v = getattr(args, k)
        if v is not None:
            meta[k] = v
    if args.wall_seconds is not None:
        meta["wall_seconds"] = args.wall_seconds
    if args.turns is not None:
        meta["turns"] = args.turns
    if args.cost_usd is not None:
        meta["cost_usd"] = args.cost_usd

    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    if args.cleanup:
        git(repo, "worktree", "remove", "--force", wt)
        meta["worktree_removed"] = True
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(f"collected: {run_dir}")
    print(f"  result.diff: {len(result.splitlines())} lines | "
          f"{stat['files_changed']} files +{stat['insertions']}/-{stat['deletions']}")
    if args.cleanup:
        print(f"  worktree removed: {wt}")
    print("  NEXT: once you have >=2 runs (or 1 run + reference), run the comparator skill.")


if __name__ == "__main__":
    main()
