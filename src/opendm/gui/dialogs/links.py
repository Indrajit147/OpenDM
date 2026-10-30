"""Pick which of a page's links to download ("Download all links with OpenDM")."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opendm.core.models import Category
from opendm.discovery.categories import match_category
from opendm.engine.http.naming import filename_from_url


class LinkPickerDialog(QDialog):
    def __init__(
        self,
        urls: list[str],
        categories: list[Category],
        *,
        page_title: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Download links"))
        self.resize(640, 480)
        intro = QLabel(
            self.tr("Links found on {0}:").format(page_title) if page_title
            else self.tr("Links found on the page:")
        )  # fmt: skip
        intro.setWordWrap(True)
        self.kind = QComboBox()
        self.kind.addItem(self.tr("All links"), None)
        for category in categories:
            self.kind.addItem(category.name, category.id)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Filter"))
        self.list = QListWidget()
        self._category_of: dict[str, int | None] = {}
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            name = filename_from_url(url) or url
            category = match_category(name, categories) if categories else None
            self._category_of[url] = category.id if category else None
            item = QListWidgetItem(f"{name}    {url}" if name != url else url)
            item.setData(Qt.ItemDataRole.UserRole, url)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # Pre-select things that look like files to download, not ordinary pages.
            likely_file = category is not None and not category.fallback
            item.setCheckState(Qt.CheckState.Checked if likely_file else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.count = QLabel()
        select_all = QPushButton(self.tr("Select shown"))
        select_none = QPushButton(self.tr("Clear shown"))
        select_all.clicked.connect(lambda: self._set_shown(Qt.CheckState.Checked))
        select_none.clicked.connect(lambda: self._set_shown(Qt.CheckState.Unchecked))
        filters = QHBoxLayout()
        filters.addWidget(self.kind)
        filters.addWidget(self.search, 1)
        toggles = QHBoxLayout()
        toggles.addWidget(select_all)
        toggles.addWidget(select_none)
        toggles.addStretch()
        toggles.addWidget(self.count)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr("Download"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(filters)
        layout.addWidget(self.list)
        layout.addLayout(toggles)
        layout.addWidget(self.buttons)
        self.kind.currentIndexChanged.connect(self._filter)
        self.search.textChanged.connect(self._filter)
        self.list.itemChanged.connect(self._update_count)
        self._update_count()

    def _items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count())]

    def _filter(self) -> None:
        wanted = self.kind.currentData()
        text = self.search.text().strip().lower()
        for item in self._items():
            url = item.data(Qt.ItemDataRole.UserRole)
            visible = (wanted is None or self._category_of.get(url) == wanted) and (
                not text or text in item.text().lower()
            )
            item.setHidden(not visible)

    def _set_shown(self, state: Qt.CheckState) -> None:
        for item in self._items():
            if not item.isHidden():
                item.setCheckState(state)

    def selected(self) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._items()
            if item.checkState() == Qt.CheckState.Checked
        ]

    def _update_count(self) -> None:
        chosen = len(self.selected())
        self.count.setText(self.tr("{0} of {1} selected").format(chosen, self.list.count()))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(chosen > 0)
