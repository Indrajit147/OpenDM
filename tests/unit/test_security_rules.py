"""Spec 7 security rules, checked against the source so they keep holding (M9 review)."""

import ast
from pathlib import Path

from opendm.core.models import DownloadRequest

SRC = Path(__file__).resolve().parents[2] / "src" / "opendm"
# The only places allowed to start a program, and why (docs/SECURITY.md).
PROCESS_STARTERS = {
    "engine/media/process.py",  # yt-dlp / FFmpeg, in a kill-on-close job object
    "host/relay.py",  # the browser host starts OpenDM.exe when it is not running
    "gui/power.py",  # "shut down after the queue", after a countdown the user can cancel
    "gui/app.py",  # the update installer, verified against SHA256SUMS.txt, after Install
}
_STARTER_CALLS = {
    "subprocess": {"Popen", "run", "call", "check_call", "check_output"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "os": {"system", "startfile", "spawnv", "execv", "popen"},
}


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            owner = func.value.id if isinstance(func, ast.Attribute) and isinstance(
                func.value, ast.Name) else ""  # fmt: skip
            yield node, name, owner


def _sources():
    for path in sorted(SRC.rglob("*.py")):
        yield path.relative_to(SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def test_no_shell_true_anywhere() -> None:
    offenders = [
        f"{rel}:{node.lineno}"
        for rel, tree in _sources()
        for node, _, _ in _calls(tree)
        for kw in node.keywords
        if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant) and not kw.value.value)
    ]
    assert offenders == []


def test_processes_start_only_in_known_places_with_argument_lists() -> None:
    starters: dict[str, list[int]] = {}
    for rel, tree in _sources():
        for node, name, owner in _calls(tree):
            if name in _STARTER_CALLS.get(owner, ()):
                starters.setdefault(rel, []).append(node.lineno)
                assert name not in ("system", "startfile", "popen", "create_subprocess_shell"), rel
                if name != "create_subprocess_exec" and node.args:
                    first = node.args[0]
                    assert not isinstance(first, (ast.Constant, ast.JoinedStr)), (
                        f"{rel}:{node.lineno} passes a command string; use a list"
                    )
    assert set(starters) <= PROCESS_STARTERS, set(starters) - PROCESS_STARTERS


def test_tls_checks_are_on_by_default(tmp_path: Path) -> None:
    assert DownloadRequest("https://example.com/a", tmp_path).verify_tls


def test_the_update_installer_runs_only_after_a_verified_download() -> None:
    text = (SRC / "gui" / "app.py").read_text(encoding="utf-8")
    # run_after_quit is set in one place: the callback of Updater.download (SHA-256 checked).
    assert text.count("self.run_after_quit = path") == 1
    block = text[text.index("def _install_update") : text.index("def _settings_accepted")]
    assert "self.run_after_quit = path" in block and "updater.download(" in block
