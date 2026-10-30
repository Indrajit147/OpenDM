"""User settings with defaults; stored as JSON values in the settings table."""

import contextlib
import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from opendm.core.settings import MAX_CONNECTIONS, EngineSettings

THEMES = ("system", "light", "dark")


class ProxyMode(StrEnum):
    SYSTEM = "system"
    NONE = "none"
    MANUAL = "manual"


@dataclass
class AppSettings:
    download_dir: Path
    tools_dir: Path
    first_run_done: bool = False
    theme: str = "system"
    close_to_tray: bool = True
    close_notice_shown: bool = False
    start_minimized: bool = False
    clipboard_monitor: bool = False
    notifications: bool = True
    connections: int = 8
    per_host: int = 8
    global_limit: int | None = None
    proxy_mode: ProxyMode = ProxyMode.SYSTEM
    proxy_url: str = ""
    ytdlp_path: str = ""  # "Use existing..." override; empty = <tools_dir>\yt-dlp\yt-dlp.exe
    ffmpeg_path: str = ""  # override; empty = <tools_dir>\ffmpeg\bin\ffmpeg.exe
    tool_update_check: bool = False  # weekly yt-dlp update check (opt-in, spec 6.8)
    last_tool_check: str = ""  # ISO date of the last check

    def tool_overrides(self) -> dict[str, Path]:
        overrides = {}
        if self.ytdlp_path:
            overrides["yt-dlp"] = Path(self.ytdlp_path)
        if self.ffmpeg_path:
            overrides["ffmpeg"] = Path(self.ffmpeg_path)
        return overrides

    @classmethod
    def defaults(cls, *, downloads: Path, data_dir: Path) -> "AppSettings":
        return cls(download_dir=downloads, tools_dir=data_dir / "tools")

    def to_dict(self) -> dict[str, Any]:
        out = dataclasses.asdict(self)
        out["download_dir"] = str(self.download_dir)
        out["tools_dir"] = str(self.tools_dir)
        out["proxy_mode"] = str(self.proxy_mode)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: "AppSettings") -> "AppSettings":
        """Stored values over defaults; anything invalid falls back to its default."""
        values = dataclasses.asdict(defaults)
        for f in dataclasses.fields(cls):
            if f.name not in data:
                continue
            with contextlib.suppress(TypeError, ValueError):
                values[f.name] = _coerce(f.name, data[f.name], values[f.name])
        return cls(**values)

    def engine_settings(self) -> EngineSettings:
        manual = self.proxy_mode is ProxyMode.MANUAL and bool(self.proxy_url)
        return EngineSettings(
            connections=self.connections,
            per_host_limit=self.per_host,
            proxy=self.proxy_url if manual else None,
            use_system_proxy=self.proxy_mode is ProxyMode.SYSTEM,
        )


def _coerce(name: str, value: Any, default: Any) -> Any:
    if name in ("download_dir", "tools_dir"):
        if not isinstance(value, str) or not value:
            raise ValueError
        return Path(value)
    if name == "theme":
        if value not in THEMES:
            raise ValueError
        return value
    if name == "proxy_mode":
        return ProxyMode(value)
    if name in ("connections", "per_host"):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError
        if not 1 <= value <= MAX_CONNECTIONS:
            raise ValueError
        return value
    if name == "global_limit":
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError
        return value or None
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise TypeError
        return value
    if isinstance(default, str):
        if not isinstance(value, str):
            raise TypeError
        return value
    return value
