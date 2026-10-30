"""Print the CHANGELOG.md section for a version (used by the release workflow).

    python scripts\\release_notes.py v0.8.0-rc.1 > notes.md

A pre-release without its own section uses the final version's section (0.8.0).
"""

import re
import sys
from pathlib import Path

_VERSION = re.compile(r"v?(\d+\.\d+\.\d+)(-[a-z]+\.\d+)?")


def release_notes(changelog: str, version: str) -> str:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise ValueError(f"not a version: {version!r}")
    candidates = [match.group(1) + (match.group(2) or ""), match.group(1)]
    sections = re.split(r"^## ", changelog.replace("\r\n", "\n"), flags=re.M)
    for wanted in candidates:
        for section in sections[1:]:
            heading, _, body = section.partition("\n")
            if heading.startswith(f"[{wanted}]"):
                return body.strip()
    raise LookupError(f"CHANGELOG.md has no section for {version}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: release_notes.py <version or tag>", file=sys.stderr)
        return 2
    changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    try:
        sys.stdout.write(release_notes(changelog, argv[0]) + "\n")
    except (LookupError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
