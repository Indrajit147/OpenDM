"""A stand-in for yt-dlp in tests. Behaviour depends on the URL's first path segment:

ok        quick download of a "video" (format 137) and an "audio" (format 140) part
slow      writes a .part file slowly; honours --continue (resumes from the part size)
spawn     like slow, but first starts a child process and writes its pid to child.pid
drm       fails like yt-dlp on DRM-protected content
netfail   fails with a network error
playlist  -J returns a playlist of three entries
Every invocation's arguments are appended to $FAKE_YTDLP_LOG (JSON lines) if set.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

PARTS = {"137": 1000, "140": 400}


def option(argv: list[str], name: str, default: str | None = None) -> str | None:
    values = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == name]
    return values[-1] if values else default


def main(argv: list[str]) -> int:
    log = os.environ.get("FAKE_YTDLP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(argv) + "\n")
    if "--version" in argv:
        print("2099.01.01")
        return 0
    url = argv[-1]
    mode = urlsplit(url).path.strip("/").split("/")[0] or "ok"
    if mode == "drm":
        print("ERROR: [fake] abc: This video is DRM protected", file=sys.stderr)
        return 1
    if mode == "netfail":
        print("ERROR: Unable to download webpage: <urlopen error timed out>", file=sys.stderr)
        return 1
    if "-J" in argv:
        if mode == "playlist":
            entries = [
                {"id": str(i), "title": f"Item {i}", "url": f"http://fake/ok/{i}", "duration": 3}
                for i in (1, 2, 3)
            ]
            print(json.dumps({"_type": "playlist", "id": "pl", "title": "Fake List",
                              "webpage_url": url, "entries": entries}))  # fmt: skip
            return 0
        print(json.dumps({
            "id": "abc", "title": "Fake Clip", "webpage_url": url, "duration": 5,
            "extractor": "fake", "thumbnail": None, "uploader": "Tester",
            "formats": [
                {"format_id": "137", "height": 1080, "vcodec": "avc1", "acodec": "none"},
                {"format_id": "22", "height": 720, "vcodec": "avc1", "acodec": "mp4a"},
                {"format_id": "140", "vcodec": "none", "acodec": "mp4a"},
            ],
            "subtitles": {"en": [{"ext": "vtt"}]},
            "automatic_captions": {"bn": [{"ext": "vtt"}]},
        }))  # fmt: skip
        return 0

    home = Path((option(argv, "-P") or "home:.").split(":", 1)[1])
    template = option(argv, "-o") or "%(title)s [%(id)s].%(ext)s"
    ext = (
        option(argv, "--audio-format")
        if "-x" in argv
        else option(argv, "--merge-output-format", "mp4")
    )
    name = (template.replace("%(title).150B", "Fake Clip").replace("%(title)s", "Fake Clip")
            .replace("%(id)s", "abc").replace("%(ext)s", ext or "mp4"))  # fmt: skip
    target = home / name
    prints = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--print"]
    for spec in prints:
        stage, _, text = spec.partition(":")
        if stage == "before_dl":
            print(text.replace("%(filename)s", str(target)), flush=True)
    if mode == "spawn":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        (home / "child.pid").write_text(str(child.pid))
    slow = mode in ("slow", "spawn")
    home.mkdir(parents=True, exist_ok=True)
    for fid, size in PARTS.items():
        part = home / f"{name}.f{fid}.part"
        start = part.stat().st_size if part.exists() and "--continue" in argv else 0
        with open(part, "ab" if start else "wb") as f:
            done = start
            while done < size:
                step = min(100, size - done)
                f.write(b"x" * step)
                f.flush()
                done += step
                print(f"OPENDM_PROGRESS downloading {done} {size} NA 1000.0 1 {fid}", flush=True)
                if slow:
                    time.sleep(0.1)
    print('[Merger] Merging formats into "' + str(target) + '"', flush=True)
    with open(target, "wb") as out:
        for fid in PARTS:
            part = home / f"{name}.f{fid}.part"
            out.write(part.read_bytes())
            part.unlink()
    for spec in prints:
        stage, _, text = spec.partition(":")
        if stage == "after_move":
            print(text.replace("%(filepath)s", str(target)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
