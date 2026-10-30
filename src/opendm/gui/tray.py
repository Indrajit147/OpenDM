"""System tray icon with quick actions and completion notifications."""

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from opendm.core.branding import APP_NAME
from opendm.gui.icons import app_icon


class Tray(QSystemTrayIcon):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(app_icon(), parent)
        self.setToolTip(APP_NAME)
        menu = QMenu(parent)
        self.show_action = QAction(self.tr("Show OpenDM"), menu)
        self.add_action = QAction(self.tr("Add URL..."), menu)
        self.pause_all_action = QAction(self.tr("Pause all"), menu)
        self.quit_action = QAction(self.tr("Quit"), menu)
        for action in (self.show_action, self.add_action, self.pause_all_action):
            menu.addAction(action)
        menu.addSeparator()
        menu.addAction(self.quit_action)
        self.setContextMenu(menu)
        self._menu = menu

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def notify(self, title: str, text: str) -> None:
        if self.isVisible():
            self.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)
