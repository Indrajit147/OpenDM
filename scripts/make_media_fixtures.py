"""Generate media test fixtures with FFmpeg (spec 8). Output is git-ignored.

    .venv\\Scripts\\python.exe scripts\\make_media_fixtures.py D:\\Tools\\ffmpeg\\bin\\ffmpeg.exe

Creates in tests/fixtures/media:
    clip.mp4            5 s, 320x240 test pattern + 440 Hz tone (H.264 + AAC)
    hls/index.m3u8      unencrypted HLS of the clip (1 s segments)
    dash/manifest.mpd   DASH with separate video and audio streams (yt-dlp must merge them)
    page.html + subs.vtt  an HTML page with <video> and an English subtitle track
    hls_drm/index.m3u8  the HLS segments behind a SAMPLE-AES (FairPlay) key: must be refused
    dash_drm/manifest.mpd  the DASH manifest with Widevine ContentProtection: must be refused
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "media"
WIDEVINE = (
    '<ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed" '
    'value="Widevine"/>'
)
SUBS = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello from OpenDM

00:00:02.000 --> 00:00:05.000
This is a test subtitle
"""
PAGE = """<!doctype html>
<html><head><title>OpenDM test video</title></head>
<body><video controls width="320">
<source src="clip.mp4" type="video/mp4">
<track kind="subtitles" srclang="en" label="English" src="subs.vtt">
</video></body></html>
"""


def run(ffmpeg: Path, *args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *args], check=True, cwd=cwd
    )


def make(ffmpeg: Path, out: Path = OUT) -> Path:
    if out.exists():
        shutil.rmtree(out)
    for sub in ("hls", "dash", "hls_drm", "dash_drm"):
        (out / sub).mkdir(parents=True)
    clip = out / "clip.mp4"
    run(ffmpeg,
        "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "25", "-c:a", "aac", "-b:a", "96k",
        "-shortest", "-movflags", "+faststart", str(clip))  # fmt: skip
    run(ffmpeg, "-i", str(clip), "-c", "copy", "-f", "hls", "-hls_time", "1",
        "-hls_playlist_type", "vod", "-hls_segment_filename", str(out / "hls" / "seg%03d.ts"),
        str(out / "hls" / "index.m3u8"))  # fmt: skip
    # The DASH muxer writes segments relative to the working folder, so run it in place.
    run(ffmpeg, "-i", str(clip), "-map", "0:v", "-map", "0:a", "-c", "copy", "-f", "dash",
        "-seg_duration", "1", "-use_template", "1", "-use_timeline", "1",
        "-adaptation_sets", "id=0,streams=v id=1,streams=a",
        "manifest.mpd", cwd=out / "dash")  # fmt: skip
    (out / "subs.vtt").write_text(SUBS, encoding="utf-8")
    (out / "page.html").write_text(PAGE, encoding="utf-8")

    hls = (out / "hls" / "index.m3u8").read_text(encoding="utf-8")
    key = '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://opendm-test",KEYFORMAT="com.apple.streamingkeydelivery"'
    protected = hls.replace("#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-PLAYLIST-TYPE:VOD\n" + key, 1)
    protected = protected.replace("seg", "../hls/seg")
    (out / "hls_drm" / "index.m3u8").write_text(protected, encoding="utf-8")

    mpd = (out / "dash" / "manifest.mpd").read_text(encoding="utf-8")
    head, sep, rest = mpd.partition("<AdaptationSet")
    end = rest.index(">") + 1
    drm_mpd = head + sep + rest[:end] + "\n" + WIDEVINE + rest[end:]
    drm_mpd = drm_mpd.replace('media="', 'media="../dash/').replace(
        'initialization="', 'initialization="../dash/'
    )
    (out / "dash_drm" / "manifest.mpd").write_text(drm_mpd, encoding="utf-8")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    print("fixtures written to", make(Path(argv[0])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
