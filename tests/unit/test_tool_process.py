"""Running external tools: output lines far longer than asyncio's default 64 KiB limit."""

import json
import sys

from opendm.engine.media.process import run_tool

# yt-dlp -J prints the whole page info as one JSON line; for YouTube it is often several MB.
BIG_LINE = (
    "import json, sys; sys.stdout.write(json.dumps({'description': 'x' * 5_000_000}) + '\\n'); "
    "sys.stderr.write('e' * 200_000 + '\\n')"
)


async def test_run_tool_reads_a_multi_megabyte_line() -> None:
    code, out, err = await run_tool([sys.executable, "-c", BIG_LINE], timeout=60)
    assert code == 0
    assert len(json.loads(out)["description"]) == 5_000_000
    assert len(err) == 200_000
