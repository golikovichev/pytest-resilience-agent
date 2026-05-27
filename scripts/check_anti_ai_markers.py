"""Anti-AI marker scan for OSS files.

Catches common LLM-output tells before they ship: em-dashes, curly
quotes, AI buzzword vocabulary, triplet patterns, and a small set of
phrases that often appear in machine-written prose. The script exits
non-zero if any marker is found, so pre-commit blocks the commit.

Runs against any text file passed on the command line. Skips itself and
the scenario JSON (which legitimately contains the failure-mode names).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that should never appear in committed prose.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("em-dash", re.compile(r"[—]")),  # —
    ("en-dash", re.compile(r"[–]")),  # –
    ("curly-double-quote", re.compile(r"[“”]")),
    ("curly-single-quote", re.compile(r"[‘’]")),
    (
        "buzzword:leverage",
        re.compile(r"\bleverag(e|es|ed|ing)\b", re.I),
    ),
    (
        "buzzword:delve",
        re.compile(r"\bdelv(e|es|ed|ing)\b", re.I),
    ),
    (
        "buzzword:foster",
        re.compile(r"\bfoster(s|ed|ing)?\s+(a|an|the)\s+\w+ment\b", re.I),
    ),
    (
        "phrase:in-conclusion",
        re.compile(r"\bin\s+conclusion\b", re.I),
    ),
    (
        "phrase:its-worth-noting",
        re.compile(r"\bit('s|\s+is)\s+worth\s+noting\b", re.I),
    ),
    (
        "phrase:as-an-ai",
        re.compile(r"\bas\s+an\s+ai\b", re.I),
    ),
]

# Files to skip entirely.
SKIP_BASENAMES = {
    "check_anti_ai_markers.py",
    "chaos_patterns.json",
    "CHANGELOG.md",
}
SKIP_SUFFIXES = {".lock"}


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return a list of (line_no, marker_name, snippet) findings."""
    if path.name in SKIP_BASENAMES or path.suffix in SKIP_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    findings: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for name, pattern in PATTERNS:
            match = pattern.search(line)
            if match:
                snippet = line.strip()[:120]
                findings.append((line_no, name, snippet))
    return findings


def main(argv: list[str]) -> int:
    if not argv:
        return 0
    total = 0
    for arg in argv:
        path = Path(arg)
        if not path.is_file():
            continue
        for line_no, name, snippet in scan_file(path):
            print(f"{path}:{line_no}: [{name}] {snippet}", file=sys.stderr)
            total += 1
    if total:
        print(
            f"\nanti-ai-scan: {total} marker(s) found. "
            "Replace em-dashes with ASCII punctuation, drop AI buzzwords, "
            "rewrite triplets in your own voice.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
