#!/usr/bin/env python3
"""
Freshness check for the 99 Nights Guide Hub data files.

Runs every 48 hours via GitHub Actions (.github/workflows/freshness-reminder.yml).
It only READS git history and opens/closes reminder issues — it never
modifies, generates or publishes any content. Content stays hand-written
and original (required by Google AdSense and the Google quality guidelines).

Rules:
- data/codes.yaml  -> reminder issue after 28 days without a commit touching it
- data/comments.yaml -> reminder issue after 45 days without a commit touching it
When the file is refreshed, the reminder issue is closed automatically.
"""
import os
import subprocess
import datetime
import sys

CUTOFFS = [
    ("data/codes.yaml", 28, "⏰ Codes freshness reminder", "Codes data"),
    ("data/comments.yaml", 45, "💬 Feedback freshness reminder", "Feedback data"),
]
TAG_HINT = "freshness reminder"


def run(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def last_commit_date(path):
    out = run("git", "log", "-1", "--format=%cI", "--", path)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    try:
        return datetime.datetime.fromisoformat(out.stdout.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def open_reminder_issues():
    """Return [(number, title)] for open issues whose title contains TAG_HINT."""
    out = run("gh", "issue", "list", "--state", "open", "--limit", "100")
    if out.returncode != 0:
        return []
    issues = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and TAG_HINT.lower() in parts[1].lower():
            try:
                issues.append((int(parts[0]), parts[1]))
            except ValueError:
                continue
    return issues


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    open_issues = {title: num for num, title in open_reminder_issues()}
    print(f"Open reminder issues: {open_issues}")

    for path, cutoff_days, title, label in CUTOFFS:
        d = last_commit_date(path)
        if d is None:
            print(f"{path}: never committed yet — skipping")
            continue
        age = (now - d).days
        print(f"{path}: last updated {age} days ago (cutoff {cutoff_days})")
        if age >= cutoff_days:
            if title not in open_issues:
                body = (
                    f"**{label} is stale** — last updated {age} days ago.\n\n"
                    f"- File: `{path}`\n"
                    "- What to do: refresh it — verify codes in-game, or publish new real player comments — then commit and push.\n"
                    "- Why: freshness is the #1 ranking factor for guide sites, and Google AdSense requires regularly updated, original content.\n"
                    "- This reminder runs automatically every 48 hours."
                )
                r = run("gh", "issue", "create", "--title", title, "--body", body)
                print(f"Opened reminder issue: {title} -> {r.returncode}")
            else:
                print(f"Reminder issue already open: {title}")
        else:
            if title in open_issues:
                run("gh", "issue", "close", str(open_issues[title]))
                print(f"Closed reminder issue: {title} (data is fresh)")
            else:
                print(f"Fresh — nothing to do for {path}")

    print("Freshness check done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
