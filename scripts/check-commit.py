#!/usr/bin/env python3
"""Check new commit subjects or a PR_TITLE supplied by CI."""
import os
from pathlib import Path
import re
import sys

PATTERN = re.compile(
    r"(feat|fix|docs|refactor|test|build|ci|perf|chore|revert)"
    r"(\([a-z0-9][a-z0-9._/-]*\))?!?: \S(?:[^\r\n]*\S)?"
)


def valid_subject(subject):
    return len(subject) <= 72 and PATTERN.fullmatch(subject) is not None


def main():
    if len(sys.argv) == 2:
        message = Path(sys.argv[1]).read_text(encoding="utf-8")
        lines = message.splitlines()
        subject = lines[0] if lines else ""
    elif len(sys.argv) == 1:
        subject = os.environ.get("PR_TITLE", "")
    else:
        raise SystemExit("Usage: check-commit.py [COMMIT_MESSAGE_FILE]")
    if not valid_subject(subject):
        print("Use type(scope): summary, at most 72 characters. Scope is optional.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
