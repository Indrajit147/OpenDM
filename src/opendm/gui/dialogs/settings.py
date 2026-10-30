"""Settings dialog. Works on copies; the caller persists the result."""

import dataclasses
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opendm.core.app_settings import AppSettings, ProxyMode
from opendm.core.models import Category
from opendm.core.settings import MAX_CONNECTIONS
from opendm.gui.dialogs.browser import BrowserPanel
from opendm.gui.dialogs.tools import ToolsPanel


def _folder_row(edit: QLineEdit, parent: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(edit)
    button = QPushButton(parent.tr("Browse..."))

    def browse() -> None:
        folder = QFileDialog.getExistingDirectory(parent, parent.tr("Choose folder"), edit.text())
        if folder:
            edit.setText(folder)

    button.clicked.connect(browse)
    row.addWidget(button)
    return row


def _note(text: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addStretch()
    return page


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        categories: list[Category],
        parent: QWidget | None = None,
        tools_panel: ToolsPanel | None = None,
        browser_panel: BrowserPanel | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self.resize(640, 440)
        self._settings = settings
        self._categories = categories
        tabs = QTabWidget()

        general = QWidget()
        form = QFormLayout(general)
        self.download_dir = QLineEdit(str(settings.download_dir))
        form.addRow(self.tr("Download folder:"), _folder_row(self.download_dir, self))
        self.close_to_tray = QCheckBox(self.tr("Closing the window keeps OpenDM in the tray"))
        self.close_to_tray.setChecked(settings.close_to_tray)
        self.start_minimized = QCheckBox(self.tr("Start minimized to the tray"))
        self.start_minimized.setChecked(settings.start_minimized)
        self.clipboard = QCheckBox(self.tr("Offer to download links I copy"))
        self.clipboard.setChecked(settings.clipboard_monitor)
        self.notifications = QCheckBox(self.tr("Notify me when downloads finish"))
        self.notifications.setChecked(settings.notifications)
        for box in (self.close_to_tray, self.start_minimized, self.clipboard, self.notifications):
            form.addRow(box)
        tabs.addTab(general, self.tr("General"))

        connections = QWidget()
        form = QFormLayout(connections)
        self.connections = QSpinBox()
        self.connections.setRange(1, MAX_CONNECTIONS)
        self.connections.setValue(settings.connections)
        self.per_host = QSpinBox()
        self.per_host.setRange(1, MAX_CONNECTIONS)
        self.per_host.setValue(settings.per_host)
        self.limit = QSpinBox()
        self.limit.setRange(0, 10_000_000)
        self.limit.setSuffix(" KiB/s")
        self.limit.setSpecialValueText(self.tr("unlimited"))
        self.limit.setValue((settings.global_limit or 0) // 1024)
        form.addRow(self.tr("Connections per download:"), self.connections)
        form.addRow(self.tr("Connections per server:"), self.per_host)
        form.addRow(self.tr("Total speed limit:"), self.limit)
        tabs.addTab(connections, self.tr("Connections"))

        folders = QWidget()
        layout = QVBoxLayout(folders)
        layout.addWidget(QLabel(self.tr(
            "Folder: empty = download folder, a name = a folder inside it, or a full path."
        )))  # fmt: skip
        self.category_table = QTableWidget(len(categories), 3)
        self.category_table.setHorizontalHeaderLabels(
            [self.tr("Category"), self.tr("Extensions"), self.tr("Folder")]
        )
        self.category_table.horizontalHeader().setStretchLastSection(True)
        for row, category in enumerate(categories):
            self.category_table.setItem(row, 0, QTableWidgetItem(category.name))
            ext = QTableWidgetItem(" ".join(category.extensions))
            self.category_table.setItem(row, 1, ext)
            self.category_table.setItem(row, 2, QTableWidgetItem(category.folder))
        layout.addWidget(self.category_table)
        tabs.addTab(folders, self.tr("Folders"))

        proxy = QWidget()
        form = QFormLayout(proxy)
        self.proxy_mode = QComboBox()
        for mode, label in ((ProxyMode.SYSTEM, self.tr("Use the Windows proxy settings")),
                            (ProxyMode.NONE, self.tr("No proxy")),
                            (ProxyMode.MANUAL, self.tr("Manual HTTP proxy"))):  # fmt: skip
            self.proxy_mode.addItem(label, str(mode))
        self.proxy_mode.setCurrentIndex(self.proxy_mode.findData(str(settings.proxy_mode)))
        self.proxy_url = QLineEdit(settings.proxy_url)
        self.proxy_url.setPlaceholderText("http://proxy.example:3128")
        form.addRow(self.tr("Proxy:"), self.proxy_mode)
        form.addRow(self.tr("Proxy address:"), self.proxy_url)
        form.addRow(QLabel(self.tr("SOCKS proxies are not supported yet.")))
        tabs.addTab(proxy, self.tr("Proxy"))

        appearance = QWidget()
        form = QFormLayout(appearance)
        self.theme = QComboBox()
        for value, label in (("system", self.tr("Same as Windows")), ("light", self.tr("Light")),
                             ("dark", self.tr("Dark"))):  # fmt: skip
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(self.theme.findData(settings.theme))
        form.addRow(self.tr("Theme:"), self.theme)
        tabs.addTab(appearance, self.tr("Appearance"))

        self.browser_panel = browser_panel
        if browser_panel is not None:
            tabs.addTab(browser_panel, self.tr("Browser"))
        tools = QWidget()
        form = QFormLayout(tools)
        self.tools_dir = QLineEdit(str(settings.tools_dir))
        form.addRow(self.tr("Tools folder:"), _folder_row(self.tools_dir, self))
        self.tools_panel = tools_panel
        if tools_panel is not None:
            form.addRow(tools_panel)
        tabs.addTab(tools, self.tr("Tools"))
        tabs.addTab(_note(self.tr("Update checks arrive in a later version.")), self.tr("Updates"))
        self.tabs = tabs

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer = QVBoxLayout(self)
        outer.addWidget(tabs)
        outer.addWidget(buttons)

    def result_settings(self) -> AppSettings:
        limit = self.limit.value() * 1024
        return dataclasses.replace(
            self._settings,
            download_dir=Path(self.download_dir.text().strip() or self._settings.download_dir),
            tools_dir=Path(self.tools_dir.text().strip() or self._settings.tools_dir),
            close_to_tray=self.close_to_tray.isChecked(),
            start_minimized=self.start_minimized.isChecked(),
            clipboard_monitor=self.clipboard.isChecked(),
            notifications=self.notifications.isChecked(),
            connections=self.connections.value(),
            per_host=self.per_host.value(),
            global_limit=limit or None,
            proxy_mode=ProxyMode(self.proxy_mode.currentData()),
            proxy_url=self.proxy_url.text().strip(),
            theme=self.theme.currentData(),
            tool_update_check=(
                self.tools_panel.update_check.isChecked()
                if self.tools_panel is not None
                else self._settings.tool_update_check
            ),
        )

    def result_categories(self) -> list[Category]:
        updated = []
        for row, category in enumerate(self._categories):
            name = self.category_table.item(row, 0).text().strip() or category.name
            extensions = tuple(self.category_table.item(row, 1).text().split())
            folder = self.category_table.item(row, 2).text().strip()
            updated.append(dataclasses.replace(category, name=name, extensions=extensions,
                                               folder=folder))  # fmt: skip
        return updated
