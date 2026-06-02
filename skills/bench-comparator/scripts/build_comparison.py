#!/usr/bin/env python3
"""Assemble a side-by-side comparison for one task's runs.

Gathers the task's reference.diff (your original work) and every run under
runs/<task_id>/, computes light navigation signals (files touched, +/- lines,
turns, wall time, cost), and writes a scannable compare.md skeleton plus a
structured comparison.json.

It deliberately does NOT score or rank. The point is to put the artifacts in
front of a human and let them judge. The LLM step (see SKILL.md) fills in the
"key differences" navigation notes — still descriptive, never a verdict.

Usage:
    python3 build_comparison.py --task tasks/<task_id> [--runs-root ./runs]
"""
import argparse
import json
import os
import sys


def parse_unified_diff(text):
    """Return {path: {'ins': n, 'del': n, 'binary': bool}} from a unified diff."""
    files = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("diff --git"):
            # "diff --git a/x b/y" -> use the b/ path
            parts = line.split(" b/", 1)
            cur = parts[1] if len(parts) == 2 else line.split()[-1]
            files.setdefault(cur, {"ins": 0, "del": 0, "binary": False})
        elif line.startswith("Binary files") and cur:
            files[cur]["binary"] = True
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("+") and cur:
            files[cur]["ins"] += 1
        elif line.startswith("-") and cur:
            files[cur]["del"] += 1
    return files


def load_diff(path):
    if not os.path.isfile(path):
        return None, {}
    text = open(path, encoding="utf-8").read()
    return text, parse_unified_diff(text)


def totals(filemap):
    return {
        "files": len(filemap),
        "ins": sum(f["ins"] for f in filemap.values()),
        "del": sum(f["del"] for f in filemap.values()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="path to tasks/<task_id>")
    ap.add_argument("--runs-root", default="./runs")
    args = ap.parse_args()

    task_dir = os.path.abspath(args.task)
    meta = json.load(open(os.path.join(task_dir, "meta.json"), encoding="utf-8"))
    task_id = meta["task_id"]

    runs_dir = os.path.join(args.runs_root, task_id)
    if not os.path.isdir(runs_dir):
        sys.exit(f"no runs found at {runs_dir} — run bench-runner first")

    # reference (your original work) is column zero
    ref_path = os.path.join(task_dir, "reference.diff")
    _, ref_files = load_diff(ref_path)
    columns = [{
        "label": "reference (yours)",
        "diff_path": os.path.relpath(ref_path, runs_dir),
        "files": ref_files,
        "totals": totals(ref_files),
        "meta": {},
    }]

    # each run
    for label in sorted(os.listdir(runs_dir)):
        rmeta_path = os.path.join(runs_dir, label, "run-meta.json")
        if not os.path.isfile(rmeta_path):
            continue
        rmeta = json.load(open(rmeta_path, encoding="utf-8"))
        rdiff = os.path.join(runs_dir, label, "result.diff")
        _, rfiles = load_diff(rdiff)
        columns.append({
            "label": label,
            "diff_path": os.path.relpath(rdiff, runs_dir),
            "files": rfiles,
            "totals": totals(rfiles),
            "meta": {k: rmeta.get(k) for k in
                     ("agent", "model", "mode", "turns", "wall_seconds", "cost_usd", "notes")},
        })

    if len(columns) < 2:
        sys.exit("need at least one run to compare against the reference")

    # union of touched files, for an overlap view
    all_files = sorted(set().union(*[set(c["files"]) for c in columns]))

    comparison = {"task_id": task_id, "columns": columns, "files_union": all_files}
    with open(os.path.join(runs_dir, "comparison.json"), "w", encoding="utf-8") as fh:
        json.dump(comparison, fh, ensure_ascii=False, indent=2)

    _write_markdown(runs_dir, task_dir, task_id, meta, columns, all_files)
    print(f"wrote {os.path.join(runs_dir, 'compare.md')}")
    print(f"      {os.path.join(runs_dir, 'comparison.json')}")
    print(f"  columns: {', '.join(c['label'] for c in columns)}")
    print("  NEXT (LLM): read the diffs and fill the 'Key differences' TODOs + the "
          "'At a glance' note. Describe differences; do not score.")


def _write_markdown(runs_dir, task_dir, task_id, meta, columns, all_files):
    L = []
    L.append(f"# Comparison — {task_id}\n")
    L.append(f"- Spec: `{os.path.relpath(os.path.join(task_dir, 'spec.md'), runs_dir)}`")
    L.append(f"- Base commit: `{meta['git']['base_commit'][:12]}`")
    L.append(f"- PR: {meta['source'].get('pr_url') or '—'}\n")

    L.append("## At a glance")
    L.append("> _LLM: 2-4 sentences pointing the reader at what actually differs "
             "between the columns. Navigation, not a verdict. The human decides which is better._\n")

    # signals table
    L.append("## Signals (navigation only — not a score)\n")
    head = "| signal | " + " | ".join(c["label"] for c in columns) + " |"
    sep = "|" + "---|" * (len(columns) + 1)
    L.append(head)
    L.append(sep)
    def row(name, fn):
        return "| " + name + " | " + " | ".join(fn(c) for c in columns) + " |"
    L.append(row("files changed", lambda c: str(c["totals"]["files"])))
    L.append(row("+lines", lambda c: str(c["totals"]["ins"])))
    L.append(row("-lines", lambda c: str(c["totals"]["del"])))
    L.append(row("model", lambda c: str(c["meta"].get("model") or "—")))
    L.append(row("mode", lambda c: str(c["meta"].get("mode") or "—")))
    L.append(row("turns", lambda c: str(c["meta"].get("turns") if c["meta"].get("turns") is not None else "—")))
    L.append(row("wall (s)", lambda c: str(c["meta"].get("wall_seconds") if c["meta"].get("wall_seconds") is not None else "—")))
    L.append(row("cost ($)", lambda c: str(c["meta"].get("cost_usd") if c["meta"].get("cost_usd") is not None else "—")))
    L.append("")

    # files-touched overlap matrix
    L.append("## Files touched (✓ = changed by that column)\n")
    head = "| file | " + " | ".join(c["label"] for c in columns) + " |"
    L.append(head)
    L.append("|" + "---|" * (len(columns) + 1))
    for f in all_files:
        cells = []
        for c in columns:
            if f in c["files"]:
                fi = c["files"][f]
                cells.append("bin" if fi["binary"] else f"+{fi['ins']}/-{fi['del']}")
            else:
                cells.append("·")
        L.append(f"| `{f}` | " + " | ".join(cells) + " |")
    L.append("")

    # per-column detail with the LLM-filled note
    L.append("## Per-column notes\n")
    for c in columns:
        L.append(f"### {c['label']}")
        L.append(f"- diff: `{c['diff_path']}`")
        if c["meta"].get("notes"):
            L.append(f"- run notes: {c['meta']['notes']}")
        L.append(f"- **Key differences vs others:** _TODO (LLM): one or two lines, "
                 f"descriptive. e.g. 'only column to refactor X', 'left Y untouched'._")
        L.append("")

    with open(os.path.join(runs_dir, "compare.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


if __name__ == "__main__":
    main()
