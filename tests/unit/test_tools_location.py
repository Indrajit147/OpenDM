"""Where yt-dlp and FFmpeg live: never inside the download folder (M8, user request)."""

from pathlib import Path

from opendm.core.paths import PORTABLE_FLAG
from opendm.tools.location import default_tools_dir, relocate_tools, tools_dir_problem


def test_default_from_source_is_the_data_folder(tmp_path: Path) -> None:
    assert default_tools_dir(None, tmp_path / "data") == tmp_path / "data" / "tools"


def test_default_when_installed_is_next_to_the_programs(tmp_path: Path) -> None:
    exe = tmp_path / "D-drive" / "OpenDM"
    exe.mkdir(parents=True)
    assert default_tools_dir(exe, tmp_path / "Local" / "OpenDM") == exe / "tools"


def test_default_when_portable_is_in_its_data_folder(tmp_path: Path) -> None:
    (tmp_path / PORTABLE_FLAG).write_text("")
    assert default_tools_dir(tmp_path, tmp_path / "data") == tmp_path / "data" / "tools"


def test_download_folder_and_its_subfolders_are_refused(tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    assert tools_dir_problem(downloads, downloads)
    assert tools_dir_problem(downloads / "tools", downloads)
    assert tools_dir_problem(downloads / "a" / "b", downloads)


def test_the_windows_downloads_folder_is_refused_too(tmp_path: Path) -> None:
    downloads, chosen = tmp_path / "Downloads", tmp_path / "D" / "dl"
    assert tools_dir_problem(downloads / "tools", chosen, downloads)
    assert tools_dir_problem(chosen / "x", chosen, downloads)


def test_other_folders_are_fine(tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    assert tools_dir_problem(tmp_path / "Tools", downloads, downloads) is None
    assert tools_dir_problem(tmp_path / "Downloads-tools", downloads) is None  # a sibling
    assert tools_dir_problem(tmp_path, downloads) is None  # a parent is not inside it


def test_comparison_ignores_case_and_dots(tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    weird = Path(str(tmp_path / "x" / ".." / "DOWNLOADS" / "tools"))
    assert tools_dir_problem(weird, downloads)


def _tool_folders(base: Path) -> None:
    (base / "yt-dlp").mkdir(parents=True)
    (base / "yt-dlp" / "yt-dlp.exe").write_bytes(b"ytdlp")
    (base / "ffmpeg" / "bin").mkdir(parents=True)
    (base / "ffmpeg" / "bin" / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (base / "holiday.jpg").write_bytes(b"photo")  # the user's own file stays put


def test_relocate_moves_only_the_tool_folders(tmp_path: Path) -> None:
    old, new = tmp_path / "Downloads", tmp_path / "OpenDM" / "tools"
    _tool_folders(old)
    assert relocate_tools(old, new) == ["yt-dlp", "ffmpeg"]
    assert (new / "yt-dlp" / "yt-dlp.exe").read_bytes() == b"ytdlp"
    assert (new / "ffmpeg" / "bin" / "ffmpeg.exe").read_bytes() == b"ffmpeg"
    assert not (old / "yt-dlp").exists() and not (old / "ffmpeg").exists()
    assert (old / "holiday.jpg").exists()


def test_relocate_never_overwrites(tmp_path: Path) -> None:
    old, new = tmp_path / "Downloads", tmp_path / "tools"
    _tool_folders(old)
    (new / "yt-dlp").mkdir(parents=True)
    (new / "yt-dlp" / "yt-dlp.exe").write_bytes(b"newer")
    assert relocate_tools(old, new) == ["ffmpeg"]
    assert (new / "yt-dlp" / "yt-dlp.exe").read_bytes() == b"newer"
    assert (old / "yt-dlp" / "yt-dlp.exe").exists()  # left where it was


def test_relocate_with_nothing_there(tmp_path: Path) -> None:
    assert relocate_tools(tmp_path / "missing", tmp_path / "tools") == []
    assert relocate_tools(tmp_path, tmp_path) == []
