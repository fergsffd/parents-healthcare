"""
Knowledge-status manifest for Parents' Healthcare.
Shows which datafiles changed since the last manual upload to the claude.ai
Project Knowledge, and records a new upload point.

  python phc_knowledge_status.py          # list datafiles changed since last upload
  python phc_knowledge_status.py mark     # record HEAD as the new upload point

The upload point is a commit hash stored in knowledge-status.txt at the repo root.
Uncommitted edits to datafiles are listed too, but commit before uploading.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "knowledge-status.txt"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def changed_since(commit: str | None) -> list[str]:
    if commit:
        committed = git("diff", "--name-only", commit, "HEAD", "--", "datafiles/").splitlines()
    else:
        # Never uploaded: every tracked datafile counts as changed.
        committed = git("ls-files", "datafiles/").splitlines()
    uncommitted = git("diff", "--name-only", "HEAD", "--", "datafiles/").splitlines()
    return sorted(set(committed) | set(uncommitted))


def main() -> None:
    last = MANIFEST.read_text().strip() if MANIFEST.exists() else None

    if sys.argv[1:] == ["mark"]:
        head = git("rev-parse", "HEAD")
        MANIFEST.write_text(head + "\n")
        print(f"Upload point recorded: {head[:7]}. Commit knowledge-status.txt.")
        return

    files = changed_since(last)
    print(f"Last upload: {last[:7] if last else 'never'}")
    if files:
        print("Upload these (delete old file in Project Knowledge first):")
        for f in files:
            print(f"  {f}")
    else:
        print("Project Knowledge is current.")


if __name__ == "__main__":
    main()
