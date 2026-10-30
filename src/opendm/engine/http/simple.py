"""Small one-shot requests for the tool manager and the app updater (not user downloads)."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from opendm.core.errors import DownloadError, ErrorKind, error_from_status
from opendm.engine.http.transport import Transport

ProgressCallback = Callable[[int, int | None], None]
MAX_TEXT = 1024 * 1024


async def get_text(
    transport: Transport, url: str, headers: dict[str, str] | None = None, limit: int = MAX_TEXT
) -> str:
    """GET a small text resource; closes the transport."""
    try:
        async with transport.stream("GET", url, headers) as resp:
            if not 200 <= resp.status < 300:
                raise error_from_status(resp.status)
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    raise DownloadError(ErrorKind.HTTP_CLIENT, "response too large")
            return body.decode("utf-8", errors="replace")
    finally:
        await transport.aclose()


async def content_length(transport: Transport, url: str) -> int | None:
    """Size from a HEAD request, or None; closes the transport."""
    try:
        async with transport.stream("HEAD", url) as resp:
            value = resp.headers.get("content-length")
            return int(value) if value and value.isdigit() else None
    except DownloadError:
        return None
    finally:
        await transport.aclose()


async def fetch_file(
    transport: Transport, url: str, dest: Path, progress: ProgressCallback | None = None
) -> None:
    """GET ``url`` into ``dest`` (overwritten); closes the transport."""
    try:
        async with transport.stream("GET", url) as resp:
            if not 200 <= resp.status < 300:
                raise error_from_status(resp.status)
            length = resp.headers.get("content-length")
            total = int(length) if length and length.isdigit() else None
            done = 0
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    await asyncio.to_thread(f.write, chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
    finally:
        await transport.aclose()
