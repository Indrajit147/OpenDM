"""Human-readable sizes and durations."""

_UNITS = ("KiB", "MiB", "GiB", "TiB")
_FACTORS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}


def parse_size(text: str) -> int:
    """``"500K"``, ``"1.5M"``, ``"2G"`` or plain bytes -> bytes (binary units)."""
    value = text.strip().upper().removesuffix("B").removesuffix("I")
    unit = value[-1:] if value[-1:] in _FACTORS else ""
    number = value[: len(value) - len(unit)].strip()
    try:
        result = float(number) * _FACTORS[unit]
    except ValueError as exc:
        raise ValueError(f"not a size: {text!r}") from exc
    if result < 0:
        raise ValueError(f"size must not be negative: {text!r}")
    return int(result)


def format_bytes(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    value = float(n)
    for unit in _UNITS:
        value /= 1024
        if value < 1024 or unit == _UNITS[-1]:
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
