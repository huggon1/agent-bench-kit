#!/usr/bin/env python3
"""Build a task package from one discovery candidate.

Takes a single candidate JSON object (from discover_tasks.py) on stdin or via
--candidate-file, and writes the deterministic parts of the task package:

    <out>/<task_id>/
        reference.diff      gold answer: git diff base..head  (kept separate; do NOT feed to the agent under test)
        source-prompts.md   the user's verbatim chat turns, for traceability
        meta.json           provenance: repo, commits, mapping confidence, diff stat

It does NOT write spec.md — synthesizing a clean spec from the prompts + PR diff
is the LLM's job (see SKILL.md).

Usage:
    discover_tasks.py | jq '.[0]' | python3 build_task_package.py --out ./examples
    python3 build_task_package.py --candidate-file cand.json --out ./examples
"""
import argparse
import json
import os
import re
import subprocess
import sys


def text_of(message):
    if not isinstance(message, dict):
        return ""
    c = message.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(
            b.get("text", "")
            for b in c
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def is_real_prompt(message):
    t = text_of(message).strip()
    if not t or t.startswith(("<local-command", "<command", "<bash")):
        return False
    c = message.get("content")
    if isinstance(c, list) and c and all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in c
    ):
        return False
    return True


def extract_prompts(session_file):
    prompts = []
    path = os.path.expanduser(session_file)
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "user" or o.get("isMeta"):
                continue
            msg = o.get("message", {})
            if is_real_prompt(msg):
                prompts.append(text_of(msg).strip())
    return prompts


def git(repo, *args):
    out = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, timeout=60
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def diff_stat(repo, base, head):
    raw = git(repo, "diff", "--numstat", base, head)
    files = ins = dele = 0
    for line in raw.splitlines():
        a, d, _ = (line.split("\t", 2) + ["", "", ""])[:3]
        files += 1
        ins += int(a) if a.isdigit() else 0
        dele += int(d) if d.isdigit() else 0
    return {"files_changed": files, "insertions": ins, "deletions": dele}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-file", help="JSON candidate; omit to read stdin")
    ap.add_argument("--out", default="./tasks", help="output root dir (the corpus)")
    args = ap.parse_args()

    raw = (
        open(args.candidate_file, encoding="utf-8").read()
        if args.candidate_file
        else sys.stdin.read()
    )
    cand = json.loads(raw)

    if cand.get("resolution") != "local-git":
        sys.exit(
            f"candidate '{cand.get('task_id')}' has resolution="
            f"{cand.get('resolution')}; only local-git is supported in v1. "
            "(github-needed candidates require a `gh` fetch step, not yet built.)"
        )

    repo = cand["repo_path"]
    base, head = cand["base_commit"], cand["head_commit"]
    task_dir = os.path.join(args.out, cand["task_id"])
    os.makedirs(task_dir, exist_ok=True)

    # 1. reference diff (the gold answer)
    ref = git(repo, "diff", base, head)
    with open(os.path.join(task_dir, "reference.diff"), "w", encoding="utf-8") as fh:
        fh.write(ref)

    # 2. verbatim prompts
    prompts = extract_prompts(cand["session_file"])
    lines = [
        "# Raw user prompts (verbatim)",
        "",
        "Traceability record — the user's actual chat turns, in order. spec.md is",
        "a synthesis of these + the PR diff; this file preserves the originals so",
        "you can judge how faithful that synthesis is.",
        "",
    ]
    for i, p in enumerate(prompts, 1):
        lines.append(f"{i}. {p}")
        lines.append("")
    with open(os.path.join(task_dir, "source-prompts.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    # 3. meta.json
    meta = {
        "task_id": cand["task_id"],
        "source": {
            "repo": cand.get("pr_repository"),
            "local_path": repo,
            "pr_number": cand.get("pr_number"),
            "pr_url": cand.get("pr_url"),
            "branch": cand.get("branch"),
        },
        "git": {
            "base_commit": base,
            "head_commit": head,
            "head_subject": cand.get("head_subject"),
        },
        "transcript": {
            "session_file": cand["session_file"],
            "span_utc": cand.get("span_utc"),
            "user_prompt_count": len(prompts),
        },
        "mapping_provenance": {
            "confidence": cand.get("confidence"),
            "why": cand.get("why"),
        },
        "diff_stat": diff_stat(repo, base, head),
        "tools": cand.get("tools"),
        "spec_status": "TODO — synthesize spec.md from source-prompts.md + reference.diff (see SKILL.md)",
    }
    with open(os.path.join(task_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(f"wrote task package: {task_dir}")
    print(f"  reference.diff   ({len(ref.splitlines())} lines)")
    print(f"  source-prompts.md ({len(prompts)} prompts)")
    print(f"  meta.json        (confidence={meta['mapping_provenance']['confidence']})")
    print("  NEXT: synthesize spec.md (LLM step) — see SKILL.md workflow step 4")


if __name__ == "__main__":
    main()
