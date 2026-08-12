#!/usr/bin/env python3
"""
Convert PEP 440 version strings to Nuitka-compatible 4-part numeric versions.

Nuitka's --product-version requires major.minor.patch.build format.
PEP 440 versions like 0.1.2rc0 or 1.0.3a1 need sanitization.

Phase ordering (same as PEP 440):
    a (alpha) < b (beta) < rc < stable

The 4th component encodes both phase and pre-release number:
    - Stable: 9000
    - rcN:    7000 + N
    - bN:     5000 + N
    - aN:     3000 + N
    - devN:   1000 + N
    - postN:  9000 + N (higher than stable)
    - revN:   9000 + N (same as post)

Examples:
    0.1.0      → 0.1.0.9000  (stable)
    0.1.2a0    → 0.1.2.3000  (alpha)
    0.1.2a1    → 0.1.2.3001
    0.1.2b0    → 0.1.2.5000  (beta)
    0.1.2rc0   → 0.1.2.7000  (release candidate)
    0.1.2rc1   → 0.1.2.7001
    1.0.3.dev5 → 1.0.3.1005  (dev)
"""

import re
import sys

# Phase offsets — spaced to allow 999 pre-release increments per phase
PHASE_OFFSETS = {
    "dev": 1000,
    "a": 3000,  # alpha
    "b": 5000,  # beta
    "rc": 7000,
}

# post and rev are treated as higher than stable
POST_OFFSET = 9000
STABLE_BUILD = 9000


def convert(pep440_version: str) -> str:
    """
    Convert a PEP 440 version to Nuitka's 4-part numeric format.

    The 4th component encodes both pre-release phase and number:
    - Stable releases: 9000
    - Pre-releases: phase_offset + number
    """
    # Extract base version (digits and dots before any pre-release suffix)
    base_match = re.match(r"(\d+(?:\.\d+)*)", pep440_version)
    if not base_match:
        raise ValueError(f"Cannot parse version: {pep440_version}")

    base = base_match.group(1)
    parts = base.split(".")
    while len(parts) < 3:
        parts.append("0")
    major, minor, patch = parts[0], parts[1], parts[2]

    # Check for post-release or revision
    post_match = re.search(r"(?:post|rev)(\d+)", pep440_version)
    if post_match:
        build = POST_OFFSET + int(post_match.group(1))
        return f"{major}.{minor}.{patch}.{build}"

    # Check for pre-release phase
    prerelease_match = re.search(r"(dev|a|b|rc)(\d+)", pep440_version)
    if prerelease_match:
        phase = prerelease_match.group(1)
        number = int(prerelease_match.group(2))
        offset = PHASE_OFFSETS[phase]
        build = offset + number
        return f"{major}.{minor}.{patch}.{build}"

    # Stable release
    return f"{major}.{minor}.{patch}.{STABLE_BUILD}"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <pep440-version>", file=sys.stderr)
        return 1

    try:
        print(convert(sys.argv[1]))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
