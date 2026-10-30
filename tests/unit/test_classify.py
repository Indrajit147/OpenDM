import pytest

from opendm.discovery.classify import LinkKind, classify, parse_quality


@pytest.mark.parametrize(
    ("url", "content_type", "kind"),
    [
        ("https://h/file.zip", "application/zip", LinkKind.FILE),
        ("https://h/video.mp4", "video/mp4", LinkKind.FILE),
        ("https://h/download?id=1", "application/octet-stream", LinkKind.FILE),
        ("https://h/stream/index.m3u8", None, LinkKind.MANIFEST),
        ("https://h/live.MPD?token=x", "text/plain", LinkKind.MANIFEST),
        ("https://h/x", "application/vnd.apple.mpegurl", LinkKind.MANIFEST),
        ("https://h/x", "application/dash+xml; charset=utf-8", LinkKind.MANIFEST),
        ("https://www.example.com/watch?v=abc", "text/html; charset=utf-8", LinkKind.PAGE),
        ("https://h/page", "application/xhtml+xml", LinkKind.PAGE),
        ("https://h/unknown", None, LinkKind.FILE),
    ],
)
def test_classify(url: str, content_type: str | None, kind: LinkKind) -> None:
    assert classify(url, content_type) is kind


@pytest.mark.parametrize(
    ("text", "quality"),
    [
        ("best", "best"),
        ("1080p", "1080"),
        ("720", "720"),
        ("audio-mp3", "audio-mp3"),
        ("mp3", "audio-mp3"),
        ("M4A", "audio-m4a"),
    ],
)
def test_parse_quality(text: str, quality: str) -> None:
    assert parse_quality(text) == quality


@pytest.mark.parametrize("bad", ["4k", "999p", "wav", ""])
def test_parse_quality_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_quality(bad)
