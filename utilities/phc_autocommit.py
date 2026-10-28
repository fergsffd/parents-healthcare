#!/usr/bin/env python3
"""
Auto-commit for Parents' Healthcare datafiles.
Run by phc-autocommit.timer. Commits and pushes changes to datafiles/*.md and
knowledge-status.txt only, naming every path explicitly (never `git add -A`).

Skips a run when:
  - nothing allowed has changed
  - an allowed file changed in the last QUIET_SECONDS (an edit session is
    probably still going; the next run picks it up)
Refuses to commit (exits 1, so the unit shows failed) when a changed file
contains something the redaction profile forbids in git: an SSN, a full
Medicare MBI, or a labeled full date of birth.

  phc_autocommit.py            # commit + push if needed
  phc_autocommit.py --dry-run  # report what would happen
"""

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QUIET_SECONDS = 90

_MBI = "AC-HJKMNP-RT-Y"
FORBIDDEN = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("full Medicare MBI", re.compile(
        rf"\b[1-9][{_MBI}][{_MBI}0-9]\d-?[{_MBI}][{_MBI}0-9]\d-?[{_MBI}]{{2}}\d{{2}}\b")),
    ("full date of birth", re.compile(
        r"(?i)\b(?:dob|date\s+of\s+birth|birth\s*date)\b\W{0,3}"
        r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})")),
]


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def changed_paths() -> list[str]:
    tracked = git("diff", "--name-only", "HEAD", "--", "datafiles/", "knowledge-status.txt")
    untracked = git("ls-files", "--others", "--exclude-standard", "--", "datafiles/",
                    "knowledge-status.txt")
    paths = set(tracked.splitlines()) | set(untracked.splitlines())
    return sorted(p for p in paths if p and (
        p == "knowledge-status.txt" or (p.startswith("datafiles/") and p.endswith(".md")
                                         and p.count("/") == 1)))


def log(msg: str):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run

    paths = changed_paths()
    if not paths:
        return 0

    existing = [REPO / p for p in paths if (REPO / p).exists()]
    newest = max((p.stat().st_mtime for p in existing), default=0)
    if time.time() - newest < QUIET_SECONDS:
        log(f"{len(paths)} changed file(s), last edit {int(time.time() - newest)}s ago; waiting")
        return 0

    problems = []
    for p in existing:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for label, pattern in FORBIDDEN:
                if pattern.search(line):
                    problems.append(f"{p.relative_to(REPO)}:{n}: looks like a {label}")
    if problems:
        log("REFUSING to commit; fix these lines first:")
        for msg in problems:
            log(f"  {msg}")
        return 1

    names = ", ".join(Path(p).name for p in paths)
    message = f"Auto: update {names}"
    if dry:
        log(f"would commit: {message}")
        return 0

    git("add", "--", *paths)
    git("commit", "-q", "-m", message, "--", *paths)
    log(f"committed {git('rev-parse', '--short', 'HEAD')}: {message}")

    try:
        git("push", "-q", "origin", "main")
    except RuntimeError:
        log("push rejected; rebasing on origin/main and retrying")
        git("pull", "-q", "--rebase", "origin", "main")
        git("push", "-q", "origin", "main")
    log("pushed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        log(f"ERROR: {e}")
        sys.exit(1)
