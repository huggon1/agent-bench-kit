#!/usr/bin/env python3
"""Discover PR-bounded task candidates from local Claude Code transcripts.

A "task" is anchored to a pull request: the PR's squash/merge commit gives a
clean before/after (base = commit^, head = commit), the feature branch and
timestamp tie the chat session to it, and the resulting diff is the reference
answer. This script does only the deterministic part: scan transcripts, find
candidates, resolve git commits, and emit JSON. Spec synthesis is the LLM's job
(see SKILL.md).

Usage:
    python3 discover_tasks.py [--projects-dir DIR] [--pretty]

Output: JSON array of candidate tasks on stdout.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import timezone
from datetime import datetime

PR_RE = re.compile(r"\(#(\d+)\)\s*$")
SKIP_BRANCHES = {"main", "master", "HEAD", "", None}


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


def scan_session(path):
    """Pull the few facts we need from one transcript file."""
    cwd = None
    branches = set()
    pr_links = []  # (prNumber, prUrl, prRepository)
    first_ts = last_ts = None
    user_prompts = 0
    tools = {"Write": 0, "Edit": 0, "Read": 0, "Bash": 0}
    for line in _iter_jsonl(path):
        if line.get("cwd"):
            cwd = line["cwd"]
        gb = line.get("gitBranch")
        if gb:
            branches.add(gb)
        ts = line.get("timestamp")
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        if line.get("type") == "pr-link":
            pr_links.append(
                (line.get("prNumber"), line.get("prUrl"), line.get("prRepository"))
            )
        if line.get("type") == "user" and not line.get("isMeta"):
            if is_real_prompt(line.get("message", {})):
                user_prompts += 1
        msg = line.get("message", {})
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    nm = b.get("name")
                    if nm in tools:
                        tools[nm] += 1
    feature_branches = sorted(b for b in branches if b not in SKIP_BRANCHES)
    return {
        "session_file": path,
        "cwd": cwd,
        "feature_branches": feature_branches,
        "pr_links": pr_links,
        "span_utc": [first_ts, last_ts],
        "user_prompt_count": user_prompts,
        "tools": tools,
    }


def _iter_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def git(repo, *args):
    try:
        out = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout if out.returncode == 0 else None
    except Exception:
        return None


def pr_commits(repo):
    """All '(#N)' squash/merge commits in a repo: hash, parent, subject, pr, date."""
    if not os.path.isdir(os.path.join(repo, ".git")):
        return []
    out = git(repo, "log", "--all", "--format=%H%x09%P%x09%cI%x09%s")
    if not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        h, parents, cdate, subject = parts
        m = PR_RE.search(subject)
        if not m:
            continue
        first_parent = parents.split(" ")[0] if parents else None
        rows.append({
            "head": h,
            "base": first_parent,
            "date": cdate,
            "subject": subject,
            "pr_number": int(m.group(1)),
        })
    return rows


def branch_tokens(name):
    # "chore/rename-vault-and-rewrite-readme" -> {rename, vault, rewrite, readme, ...}
    return {t for t in re.split(r"[/_\-\s]+", (name or "").lower()) if len(t) > 2}


def to_utc(iso):
    """Parse an ISO timestamp (any offset, or trailing Z) to a UTC datetime."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def commit_in_span(commit_iso, span, slack_min=5):
    """True if the commit time falls within the session span (± slack), in UTC."""
    c = to_utc(commit_iso)
    a = to_utc(span[0])
    b = to_utc(span[1])
    if not (c and a and b):
        return False
    span_secs = slack_min * 60
    return (a.timestamp() - span_secs) <= c.timestamp() <= (b.timestamp() + span_secs)


def match_session(sess, commits):
    """Pick the best PR commit for a session. Returns (commit, confidence, why)."""
    pr_nums = {n for n, _, _ in sess["pr_links"] if n is not None}
    feat = sess["feature_branches"]
    feat_tokens = set().union(*(branch_tokens(b) for b in feat)) if feat else set()
    span = sess["span_utc"]

    scored = []
    for c in commits:
        score = 0
        reasons = []
        # timestamp proximity is the sturdiest signal (timezone-normalized)
        if commit_in_span(c["date"], span):
            score += 3
            reasons.append("commit-time within session span")
        # branch-name token overlap with the commit subject
        overlap = feat_tokens & branch_tokens(c["subject"])
        if len(overlap) >= 2:
            score += 2
            reasons.append(f"branch tokens match subject ({sorted(overlap)})")
        elif len(overlap) == 1:
            score += 1
            reasons.append(f"weak branch token match ({sorted(overlap)})")
        # pr-link number (least reliable: can be stale/duplicated)
        if c["pr_number"] in pr_nums:
            score += 1
            reasons.append("pr-link number matches")
        if score:
            scored.append((score, c, reasons))
    if not scored:
        return None, "none", []
    scored.sort(key=lambda x: -x[0])
    best_score, best, reasons = scored[0]
    conf = "high" if best_score >= 4 else "medium" if best_score >= 2 else "low"
    return best, conf, reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--projects-dir",
        default=os.path.expanduser("~/.claude/projects"),
    )
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    candidates = []
    seen_heads = set()
    for path in sorted(glob.glob(os.path.join(args.projects_dir, "*", "*.jsonl"))):
        sess = scan_session(path)
        repo = sess["cwd"]
        local_git = bool(repo and os.path.isdir(os.path.join(repo, ".git")))
        commits = pr_commits(repo) if local_git else []

        commit, conf, reasons = match_session(sess, commits)
        pr_repo = next((r for _, _, r in sess["pr_links"] if r), None)
        pr_num = next((n for n, _, _ in sess["pr_links"] if n is not None), None)
        pr_url = next((u for _, u, _ in sess["pr_links"] if u), None)

        if commit:
            key = (repo, commit["head"])
            if key in seen_heads:
                continue
            seen_heads.add(key)
            candidates.append({
                "task_id": _slug(repo, commit["subject"]),
                "resolution": "local-git",
                "confidence": conf,
                "why": reasons,
                "repo_path": repo,
                "pr_repository": pr_repo,
                "pr_number": commit["pr_number"],
                "pr_url": pr_url,
                "branch": sess["feature_branches"][0] if sess["feature_branches"] else None,
                "base_commit": commit["base"],
                "head_commit": commit["head"],
                "head_subject": commit["subject"],
                "session_file": path,
                "span_utc": sess["span_utc"],
                "user_prompt_count": sess["user_prompt_count"],
                "tools": sess["tools"],
            })
        elif pr_repo and pr_num is not None:
            # local git gone but we know the GitHub PR -> needs `gh` fallback
            candidates.append({
                "task_id": f"{pr_repo}#{pr_num}",
                "resolution": "github-needed",
                "confidence": "low",
                "why": ["no local git; pr-link present, fetch via gh"],
                "repo_path": repo,
                "pr_repository": pr_repo,
                "pr_number": pr_num,
                "pr_url": pr_url,
                "branch": sess["feature_branches"][0] if sess["feature_branches"] else None,
                "base_commit": None,
                "head_commit": None,
                "session_file": path,
                "span_utc": sess["span_utc"],
                "user_prompt_count": sess["user_prompt_count"],
                "tools": sess["tools"],
            })

    order = {"high": 0, "medium": 1, "low": 2}
    candidates.sort(key=lambda c: (order.get(c["confidence"], 9), c["task_id"]))
    print(json.dumps(candidates, ensure_ascii=False, indent=2 if args.pretty else None))


def _slug(repo, subject):
    base = os.path.basename(repo.rstrip("/")) if repo else "repo"
    s = re.sub(r"\(#\d+\)\s*$", "", subject).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50]
    return f"{base}/{s}"


if __name__ == "__main__":
    main()
