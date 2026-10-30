"""App version numbers: ``X.Y.Z`` with an optional ``-alpha.N``, ``-beta.N`` or ``-rc.N``.

Release tags are the same with a leading ``v`` (``v0.8.0-rc.1``). Pre-releases sort before
the final version, so 0.8.0-rc.1 < 0.8.0-rc.2 < 0.8.0 < 0.8.1-rc.1.
"""

import re
from typing import NamedTuple

_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")
_PRE_ORDER = {"alpha": 0, "beta": 1, "rc": 2, None: 3}


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    pre: str | None = None
    pre_number: int = 0

    @property
    def is_prerelease(self) -> bool:
        return self.pre is not None

    @property
    def base(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def windows(self) -> str:
        """Four numbers for Windows file version fields."""
        return f"{self.base}.0"

    def _key(self) -> tuple[int, ...]:
        return (self.major, self.minor, self.patch, _PRE_ORDER[self.pre], self.pre_number)

    def __lt__(self, other: object) -> bool:
        return self._key() < other._key() if isinstance(other, Version) else NotImplemented

    def __gt__(self, other: object) -> bool:
        return self._key() > other._key() if isinstance(other, Version) else NotImplemented

    def __le__(self, other: object) -> bool:
        return self._key() <= other._key() if isinstance(other, Version) else NotImplemented

    def __ge__(self, other: object) -> bool:
        return self._key() >= other._key() if isinstance(other, Version) else NotImplemented

    def __str__(self) -> str:
        return self.base + (f"-{self.pre}.{self.pre_number}" if self.pre else "")


def parse_version(text: str) -> Version:
    match = _PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"not a version: {text!r}")
    major, minor, patch, pre, number = match.groups()
    return Version(int(major), int(minor), int(patch), pre, int(number or 0))
