"""Turn the quality picker's choices into yt-dlp arguments."""

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

HEIGHTS = ("2160", "1440", "1080", "720", "480", "360")
QUALITIES = ("best", *HEIGHTS, "audio-mp3", "audio-m4a")
CONTAINERS = ("mp4", "mkv", "webm")
_LANG = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


@dataclass(frozen=True)
class MediaOptions:
    quality: str = "best"
    container: str = "mp4"
    subtitles: tuple[str, ...] = ()
    auto_subtitles: bool = False
    embed_thumbnail: bool = False

    def __post_init__(self) -> None:
        if self.quality not in QUALITIES:
            raise ValueError(f"unknown quality {self.quality!r}")
        if self.container not in CONTAINERS:
            raise ValueError(f"unknown container {self.container!r}")
        for lang in self.subtitles:
            if not _LANG.match(lang):
                raise ValueError(f"bad subtitle language {lang!r}")

    @property
    def audio_only(self) -> bool:
        return self.quality.startswith("audio-")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["subtitles"] = list(self.subtitles)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaOptions":
        return cls(
            quality=data.get("quality", "best"),
            container=data.get("container", "mp4"),
            subtitles=tuple(data.get("subtitles", ())),
            auto_subtitles=bool(data.get("auto_subtitles", False)),
            embed_thumbnail=bool(data.get("embed_thumbnail", False)),
        )


def ytdlp_format_args(options: MediaOptions) -> list[str]:
    if options.audio_only:
        fmt = options.quality.removeprefix("audio-")
        args = ["-f", "ba/b", "-x", "--audio-format", fmt, "--audio-quality", "0"]
    else:
        if options.quality == "best":
            selector = "bv*+ba/b"
        else:
            h = options.quality
            selector = f"bv*[height<={h}]+ba/b[height<={h}]/b"
        args = [
            "-f", selector,
            "--merge-output-format", options.container,
            "--remux-video", options.container,
        ]  # fmt: skip
    if options.subtitles:
        args += [
            "--write-subs",
            "--sub-langs",
            ",".join(options.subtitles),
            "--convert-subs",
            "srt",
        ]
        if options.auto_subtitles:
            args.append("--write-auto-subs")
    if options.embed_thumbnail:
        args.append("--embed-thumbnail")
    return args


def available_heights(formats: Iterable[dict[str, Any]]) -> list[int]:
    """Distinct video heights, highest first."""
    heights = {
        f["height"]
        for f in formats
        if isinstance(f.get("height"), int) and f.get("vcodec") not in (None, "none")
    }
    return sorted(heights, reverse=True)
