"""User-supplied checksums (spec 6.1): SHA-256, SHA-1 or MD5."""

import hashlib
import string
from pathlib import Path

HEX_LENGTHS = {"sha256": 64, "sha1": 40, "md5": 32}
_BY_LENGTH = {n: algo for algo, n in HEX_LENGTHS.items()}


def parse_checksum(text: str) -> tuple[str, str]:
    """``"sha256:<hex>"`` (or bare hex, algorithm inferred from length) -> (algo, hex)."""
    algo, sep, digest = text.strip().rpartition(":")
    algo = algo.lower() if sep else _BY_LENGTH.get(len(digest), "")
    digest = digest.lower()
    if algo not in HEX_LENGTHS:
        raise ValueError(f"unsupported checksum {text!r}; use sha256:, sha1: or md5:")
    if len(digest) != HEX_LENGTHS[algo] or not set(digest) <= set(string.hexdigits.lower()):
        raise ValueError(f"not a valid {algo} digest: {digest!r}")
    return algo, digest


def file_digest(path: Path, algo: str) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, algo).hexdigest()
