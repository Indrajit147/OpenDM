"""Human-readable sizes and durations."""

_UNITS = ("KiB", "MiB", "GiB", "TiB")


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
