"""Retry-After parsing (RFC 9110 10.2.3). The backoff policy is ``core.settings.RetryPolicy``."""

import time
from email.utils import parsedate_to_datetime


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a Retry-After value (delay-seconds or HTTP-date)."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else now
    return max(when - current, 0.0)
