"""The console programs stay small and fast: no Qt in opendm-cli or opendm-host (M7)."""

import subprocess
import sys

import pytest

CHECK = (
    "import sys, runpy; import {module}; "
    "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6')); "
    "print(bad); sys.exit(1 if bad else 0)"
)


@pytest.mark.parametrize(
    "module",
    [
        "opendm.cli.__main__",
        "opendm.host.__main__",
        "opendm.host.register",
        "opendm.queue.scheduler",  # the CLI's --standalone engine
    ],
)
def test_console_programs_do_not_import_qt(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", CHECK.format(module=module)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
