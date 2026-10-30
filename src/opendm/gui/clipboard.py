"""Opt-in clipboard monitor: notices copied links that look like downloadable files."""

from collections.abc import Callable, Collection
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QClipboard

from opendm.core.batch import parse_url_list


def looks_downloadable(url: str, extensions: Collection[str]) -> bool:
    path = urlsplit(url).path.lower()
    return any(path.endswith("." + ext) for ext in extensions)


class ClipboardMonitor(QObject):
    linkCopied = Signal(str)

    def __init__(
        self,
        clipboard: QClipboard,
        extensions: Callable[[], Collection[str]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._clipboard = clipboard
        self._extensions = extensions
        self._last = ""
        self.enabled = False
        clipboard.dataChanged.connect(self._changed)

    def _changed(self) -> None:
        if not self.enabled:
            return
        text = self._clipboard.text().strip()
        if not text or "\n" in text or text == self._last or len(text) > 8192:
            return
        urls, _ = parse_url_list(text)
        if len(urls) == 1 and looks_downloadable(urls[0], self._extensions()):
            self._last = text
            self.linkCopied.emit(urls[0])
