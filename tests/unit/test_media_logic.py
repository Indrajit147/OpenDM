"""Media engine logic that needs no tools: formats, DRM detection, cookies, progress."""

import os
from pathlib import Path

import pytest

from opendm.core.errors import ErrorKind
from opendm.engine.media.cookies import temporary_cookie_file
from opendm.engine.media.drm import dash_is_protected, hls_is_protected, info_is_protected
from opendm.engine.media.formats import MediaOptions, available_heights, ytdlp_format_args
from opendm.engine.media.progress import (
    PROGRESS_MARK,
    ProgressTracker,
    classify_ytdlp_error,
    formats_hidden,
    parse_line,
)
from opendm.engine.media.ytdlp import has_streams, video_in_playlist

# --- formats ---------------------------------------------------------------------------------


def test_best_video_defaults() -> None:
    args = ytdlp_format_args(MediaOptions())
    assert args[:2] == ["-f", "bv*+ba/b"]
    assert args[2:4] == ["--merge-output-format", "mp4"]
    assert "--remux-video" in args


def test_height_cap_and_container() -> None:
    args = ytdlp_format_args(MediaOptions(quality="720", container="mkv"))
    assert args[1] == "bv*[height<=720]+ba/b[height<=720]/b"
    assert args[args.index("--merge-output-format") + 1] == "mkv"


@pytest.mark.parametrize("fmt", ["mp3", "m4a"])
def test_audio_only(fmt: str) -> None:
    args = ytdlp_format_args(MediaOptions(quality=f"audio-{fmt}"))
    assert args[:2] == ["-f", "ba/b"]
    assert ["-x", "--audio-format", fmt] == args[2:5]
    assert "--merge-output-format" not in args


def test_subtitles_and_thumbnail() -> None:
    args = ytdlp_format_args(
        MediaOptions(subtitles=("en", "bn"), auto_subtitles=True, embed_thumbnail=True)
    )
    assert args[args.index("--sub-langs") + 1] == "en,bn"
    assert "--write-subs" in args and "--write-auto-subs" in args
    assert "--convert-subs" in args and "--embed-thumbnail" in args


def test_invalid_options_rejected() -> None:
    with pytest.raises(ValueError):
        MediaOptions(quality="999")
    with pytest.raises(ValueError):
        MediaOptions(container="avi")
    with pytest.raises(ValueError):
        MediaOptions(subtitles=("en;rm",))


def test_options_round_trip() -> None:
    options = MediaOptions(quality="1080", container="webm", subtitles=("en",))
    assert MediaOptions.from_dict(options.to_dict()) == options


def test_available_heights() -> None:
    formats = [
        {"height": 1080, "vcodec": "avc1"},
        {"height": 720, "vcodec": "vp9"},
        {"height": 720, "vcodec": "avc1"},
        {"height": None, "vcodec": "none", "acodec": "opus"},
        {"vcodec": "avc1"},
    ]
    assert available_heights(formats) == [1080, 720]


# --- DRM -------------------------------------------------------------------------------------

AES128 = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="https://example.com/key.bin",IV=0x1234
#EXTINF:4.0,
seg0.ts
"""
SAMPLE_AES = '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://key",KEYFORMAT="com.apple.streamingkeydelivery"\n'
WIDEVINE_HLS = (
    '#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=SAMPLE-AES-CTR,URI="data:,x",'
    'KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n'
)


@pytest.mark.parametrize(
    ("text", "protected"),
    [
        ("#EXTM3U\n#EXTINF:4,\nseg0.ts\n", False),
        (AES128, False),  # decision M5-2: plain AES-128 is allowed
        ("#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n", False),
        (SAMPLE_AES, True),
        (WIDEVINE_HLS, True),
        ('#EXT-X-KEY:METHOD=AES-128,URI="k",KEYFORMAT="com.microsoft.playready"\n', True),
    ],
)
def test_hls_protection(text: str, protected: bool) -> None:
    assert hls_is_protected(text) is protected


CLEAR_MPD = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet/></Period></MPD>'
WIDEVINE_MPD = (
    "<MPD><Period><AdaptationSet><ContentProtection "
    'schemeIdUri="urn:uuid:EDEF8BA9-79D6-4ACE-A3C8-27DCD51D21ED"/></AdaptationSet></Period></MPD>'
)
CENC_MPD = (
    '<MPD><ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011" value="cenc"/></MPD>'
)


@pytest.mark.parametrize(
    ("text", "protected"), [(CLEAR_MPD, False), (WIDEVINE_MPD, True), (CENC_MPD, True)]
)
def test_dash_protection(text: str, protected: bool) -> None:
    assert dash_is_protected(text) is protected


def test_info_protection() -> None:
    assert not info_is_protected({"formats": [{"format_id": "1"}]})
    assert info_is_protected({"_has_drm": True})
    assert info_is_protected({"formats": [{"has_drm": True}, {"has_drm": True}]})
    # Some formats DRM-free: yt-dlp skips the protected ones, the rest is fine.
    assert not info_is_protected({"formats": [{"has_drm": True}, {"format_id": "2"}]})


# --- cookies ---------------------------------------------------------------------------------


def test_temporary_cookie_file(tmp_path: Path) -> None:
    with temporary_cookie_file(
        "a=1; session=s3cr3t", "https://www.example.com/v", tmp_path
    ) as path:
        assert path.parent == tmp_path
        lines = path.read_text("utf-8").splitlines()
        assert lines[0] == "# Netscape HTTP Cookie File"
        rows = [line.split("\t") for line in lines[1:] if line and not line.startswith("#")]
        assert rows == [
            ["www.example.com", "FALSE", "/", "TRUE", "0", "a", "1"],
            ["www.example.com", "FALSE", "/", "TRUE", "0", "session", "s3cr3t"],
        ]
        if os.name != "nt":
            assert path.stat().st_mode & 0o077 == 0
    assert not path.exists()  # deleted afterwards


def test_cookie_file_deleted_on_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), temporary_cookie_file("a=1", "http://h/", tmp_path) as path:
        raise RuntimeError
    assert not path.exists()


def test_no_cookies_no_file(tmp_path: Path) -> None:
    with temporary_cookie_file(None, "http://h/", tmp_path) as path:
        assert path is None
    assert list(tmp_path.iterdir()) == []


def test_cookie_values_cannot_inject_lines(tmp_path: Path) -> None:
    with temporary_cookie_file("a=1\nevil\tline; b=2", "http://h/", tmp_path) as path:
        assert path is not None
        text = path.read_text("utf-8")
    assert "evil" not in text


# --- progress --------------------------------------------------------------------------------


def test_parse_progress_line() -> None:
    line = f"{PROGRESS_MARK} downloading 1048576 4194304 NA 524288.5 6 137"
    event = parse_line(line)
    assert event == ("progress", {"status": "downloading", "downloaded": 1048576,
                                  "total": 4194304, "speed": 524288.5, "eta": 6.0,
                                  "format_id": "137"})  # fmt: skip


def test_parse_progress_uses_estimate_and_handles_na() -> None:
    kind, data = parse_line(f"{PROGRESS_MARK} downloading 100 NA 2000.0 NA NA 22")
    assert kind == "progress" and data["total"] == 2000 and data["speed"] is None


def test_parse_other_lines() -> None:
    assert parse_line("OPENDM_FILE:D:\\dl\\Clip [abc].mp4") == ("file", "D:\\dl\\Clip [abc].mp4")
    assert parse_line('[Merger] Merging formats into "x.mp4"') == ("phase", "merging")
    assert parse_line("[ExtractAudio] Destination: x.mp3") == ("phase", "converting")
    assert parse_line("[EmbedThumbnail] ffmpeg: Adding thumbnail") == ("phase", "converting")
    assert parse_line("[download] Destination: x") is None


def test_tracker_sums_separate_video_and_audio() -> None:
    tracker = ProgressTracker()
    tracker.update({"format_id": "137", "downloaded": 500, "total": 1000, "status": "downloading"})
    tracker.update({"format_id": "137", "downloaded": 1000, "total": 1000, "status": "finished"})
    tracker.update({"format_id": "140", "downloaded": 100, "total": 400, "status": "downloading"})
    assert (tracker.downloaded, tracker.total) == (1100, 1400)


@pytest.mark.parametrize(
    ("stderr", "kind"),
    [
        ("ERROR: [youtube] abc: This video is DRM protected", ErrorKind.PROTECTED),
        ("ERROR: [generic] Unsupported URL: https://example.com/", ErrorKind.MEDIA),
        ("ERROR: Unable to download webpage: <urlopen error timed out>", ErrorKind.NETWORK),
        ("ERROR: unable to download video data: HTTP Error 403: Forbidden", ErrorKind.LINK_EXPIRED),
        ("ERROR: unable to download video data: HTTP Error 404: Not Found", ErrorKind.NOT_FOUND),
        ("ERROR: Postprocessing: ffmpeg not found", ErrorKind.MEDIA),
        ("", ErrorKind.MEDIA),
    ],
)
def test_classify_ytdlp_error(stderr: str, kind: ErrorKind) -> None:
    error = classify_ytdlp_error(stderr)
    assert error.kind is kind
    if stderr:
        assert "ERROR:" not in error.message


# --- streams hidden by cookies -----------------------------------------------------------------


def test_formats_hidden() -> None:
    assert formats_hidden("WARNING: Only images are available for download.")
    assert formats_hidden("ERROR: [youtube] x: Requested format is not available. Use ...")
    assert not formats_hidden("ERROR: Unable to download webpage: timed out")


def test_has_streams() -> None:
    storyboard = {"format_id": "sb0", "vcodec": "none", "acodec": "none"}
    assert not has_streams({"formats": [storyboard]})
    assert has_streams({"formats": [storyboard, {"vcodec": "none", "acodec": "opus"}]})
    assert has_streams({"formats": [{"format_id": "0", "url": "http://x/v"}]})  # no codec info
    assert has_streams({"url": "http://x/v.mp4"})
    assert not has_streams({})


def test_video_inside_a_playlist() -> None:
    assert video_in_playlist("https://www.youtube.com/watch?v=Ks3&list=RDKs3&start_radio=1")
    assert video_in_playlist("https://m.youtube.com/watch?list=PL1&v=x")
    assert not video_in_playlist("https://www.youtube.com/watch?v=Ks3")
    assert not video_in_playlist("https://www.youtube.com/playlist?list=PL1")
    assert not video_in_playlist("https://example.com/watch?v=&list=")
