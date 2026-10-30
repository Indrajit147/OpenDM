"""Light/dark themes (Fusion style). "system" follows the Windows setting live."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_DARK = {
    QPalette.ColorRole.Window: "#202124",
    QPalette.ColorRole.WindowText: "#e8eaed",
    QPalette.ColorRole.Base: "#17181a",
    QPalette.ColorRole.AlternateBase: "#26272a",
    QPalette.ColorRole.ToolTipBase: "#2b2c30",
    QPalette.ColorRole.ToolTipText: "#e8eaed",
    QPalette.ColorRole.Text: "#e8eaed",
    QPalette.ColorRole.Button: "#2b2c30",
    QPalette.ColorRole.ButtonText: "#e8eaed",
    QPalette.ColorRole.BrightText: "#ffffff",
    QPalette.ColorRole.Highlight: "#2f9e8f",
    QPalette.ColorRole.HighlightedText: "#ffffff",
    QPalette.ColorRole.Link: "#6cc3b5",
    QPalette.ColorRole.PlaceholderText: "#8a8d93",
    QPalette.ColorRole.Mid: "#3a3b3f",
    QPalette.ColorRole.Dark: "#111214",
}
_LIGHT_ACCENT = "#1f8577"


def system_is_dark(app: QApplication) -> bool:
    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def effective_theme(mode: str, system_dark: bool) -> str:
    if mode in ("light", "dark"):
        return mode
    return "dark" if system_dark else "light"


def _palette(theme: str, app: QApplication) -> QPalette:
    if theme == "dark":
        palette = QPalette()
        for role, color in _DARK.items():
            palette.setColor(role, QColor(color))
        disabled = QColor("#6b6e74")
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                     QPalette.ColorRole.WindowText):  # fmt: skip
            palette.setColor(QPalette.ColorGroup.Disabled, role, disabled)
        return palette
    palette = app.style().standardPalette()
    palette.setColor(QPalette.ColorRole.Highlight, QColor(_LIGHT_ACCENT))
    palette.setColor(QPalette.ColorRole.Link, QColor(_LIGHT_ACCENT))
    return palette


def apply_theme(app: QApplication, mode: str) -> str:
    """Apply "system", "light" or "dark"; returns the theme now in effect."""
    app.setStyle("Fusion")
    theme = effective_theme(mode, system_is_dark(app))
    app.setPalette(_palette(theme, app))
    app.setProperty("opendm_theme_mode", mode)
    return theme


class SystemThemeFollower:
    """Re-applies the theme when Windows switches light/dark while in "system" mode."""

    def __init__(self, app: QApplication) -> None:
        self._app = app
        app.styleHints().colorSchemeChanged.connect(self._changed)

    def _changed(self) -> None:
        if self._app.property("opendm_theme_mode") == "system":
            apply_theme(self._app, "system")
