"""Main window: toolbar, sidebar of views, download table, status bar."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStyle,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
)

from opendm.core.app_settings import AppSettings
from opendm.core.batch import parse_url_list
from opendm.core.branding import APP_NAME
from opendm.core.events import Finished, Progress
from opendm.core.models import Category, DownloadRequest, Job, JobState, Queue
from opendm.core.units import format_bytes
from opendm.discovery.categories import category_folder, match_category
from opendm.engine.http.naming import filename_from_url
from opendm.gui.dialogs.add_url import AddUrlDialog
from opendm.gui.dialogs.details import DetailsDialog
from opendm.gui.dialogs.start_download import StartDownloadDialog
from opendm.gui.engine_client import EngineClient
from opendm.gui.icons import app_icon
from opendm.gui.models.downloads import (
    ADDED,
    ETA,
    JOB_ROLE,
    NAME,
    PROGRESS,
    SIZE,
    SPEED,
    STATUS,
    DownloadsFilter,
    DownloadsModel,
)
from opendm.gui.widgets.progress_delegate import ProgressDelegate

_RUNNING = {JobState.PROBING, JobState.DOWNLOADING, JobState.VERIFYING}
# Opening these runs code: always ask first (spec 7: never auto-run downloads).
RISKY_SUFFIXES = frozenset(
    [
        ".exe",
        ".msi",
        ".msix",
        ".appx",
        ".bat",
        ".cmd",
        ".com",
        ".scr",
        ".ps1",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".hta",
        ".lnk",
        ".jar",
    ]
)
MAX_LINK_FILE = 1024 * 1024
MIN_NAME_WIDTH = 220


class MainWindow(QMainWindow):
    settingsRequested = Signal()
    queuesRequested = Signal()
    quitRequested = Signal()
    mediaRequested = Signal(object)  # DownloadRequest for a video/audio page or stream

    def __init__(self, client: EngineClient, settings: AppSettings) -> None:
        super().__init__()
        self.client = client
        self.settings = settings
        self.categories: list[Category] = []
        self.queues: list[Queue] = []
        self.tray_available = False
        self.allow_close = False
        self.on_close_to_tray: Callable[[], None] | None = None
        self._details: dict[str, DetailsDialog] = {}
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1100, 640)
        self.setAcceptDrops(True)

        self.model = DownloadsModel(self)
        self.proxy = DownloadsFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegateForColumn(PROGRESS, ProgressDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(ADDED, Qt.SortOrder.AscendingOrder)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)  # long names/statuses are elided; full text in the tooltip
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)
        self._size_columns()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._double_clicked)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)

        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderHidden(True)
        self.sidebar.itemSelectionChanged.connect(self._view_changed)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search downloads"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.proxy.set_search)
        splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.table)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 940])
        self.setCentralWidget(splitter)
        self._build_actions()
        self.speed_label = QLabel()
        self.count_label = QLabel()
        self.statusBar().addWidget(self.count_label)
        self.statusBar().addPermanentWidget(self.speed_label)

        client.jobUpdated.connect(self.model.update_job)
        client.jobUpdated.connect(lambda _: self._update_status())
        client.jobRemoved.connect(self.model.remove_job)
        client.progress.connect(self._on_progress)
        self.reload()

    # --- setup -------------------------------------------------------------------------------

    def _build_actions(self) -> None:
        style = self.style()
        icon = style.standardIcon
        sp = QStyle.StandardPixmap

        def make(text: str, pixmap: QStyle.StandardPixmap, slot: Callable[[], None],
                 shortcut: str | None = None) -> QAction:  # fmt: skip
            action = QAction(icon(pixmap), text, self)
            action.triggered.connect(slot)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            return action

        self.add_action = make(
            self.tr("Add URL"), sp.SP_FileDialogNewFolder, self.add_url, "Ctrl+N"
        )
        self.resume_action = make(self.tr("Resume"), sp.SP_MediaPlay, self.resume_selected)
        self.pause_action = make(self.tr("Pause"), sp.SP_MediaPause, self.pause_selected)
        self.stop_all_action = make(self.tr("Stop all"), sp.SP_MediaStop, self.stop_all)
        self.delete_action = make(self.tr("Delete"), sp.SP_TrashIcon, self.delete_selected, "Del")
        self.queues_action = make(self.tr("Queues"), sp.SP_FileDialogListView,
                                  self.queuesRequested.emit)  # fmt: skip
        self.settings_action = make(self.tr("Settings"), sp.SP_FileDialogDetailedView,
                                    self.settingsRequested.emit)  # fmt: skip
        toolbar = self.addToolBar(self.tr("Main"))
        toolbar.setObjectName("main-toolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        for action in (self.add_action, self.resume_action, self.pause_action,
                       self.stop_all_action, self.delete_action):  # fmt: skip
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.queues_action)
        toolbar.addAction(self.settings_action)
        toolbar.addSeparator()
        toolbar.addWidget(self.search)
        self._update_actions()

    def _size_columns(self) -> None:
        """Compact fixed widths sized from the font; the name takes all remaining space.

        (ResizeToContents is avoided: it re-measures every row on each progress update.)
        """
        metrics = self.table.fontMetrics()
        pad = 18

        def fits(sample: str) -> int:
            return metrics.horizontalAdvance(sample) + pad

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        self._preferred = {
            SIZE: fits("999.9 MiB"),
            PROGRESS: fits("100.0%") + 40,
            SPEED: fits("999.9 MiB/s"),
            ETA: fits("99:59:59"),
            STATUS: fits("Downloading") + 40,
            ADDED: fits("2026-12-31 23:59"),
        }
        for column in range(self.model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        self.table.viewport().installEventFilter(self)
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Name gets what is left, but at least MIN_NAME_WIDTH; others shrink to 60% if needed."""
        header = self.table.horizontalHeader()
        available = self.table.viewport().width()
        preferred = sum(self._preferred.values())
        scale = 1.0
        if available - preferred < MIN_NAME_WIDTH:
            scale = max((available - MIN_NAME_WIDTH) / preferred, 0.6)
        used = 0
        for column, width in self._preferred.items():
            size = int(width * scale)
            header.resizeSection(column, size)
            used += size
        header.resizeSection(NAME, max(available - used, MIN_NAME_WIDTH))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_columns()
        return super().eventFilter(watched, event)

    def reload(self) -> None:
        self.client.call(
            lambda m: (m.jobs.list(), m.categories.list(), m.queues.list()),
            on_done=self._loaded,
        )

    def _loaded(self, data: tuple[list[Job], list[Category], list[Queue]]) -> None:
        jobs, self.categories, self.queues = data
        self.model.set_jobs(jobs)
        self._build_sidebar()
        self._update_status()

    def _build_sidebar(self) -> None:
        self.sidebar.blockSignals(True)
        self.sidebar.clear()

        def item(text: str, kind: str, value: int | None = None,
                 parent: QTreeWidgetItem | None = None) -> QTreeWidgetItem:  # fmt: skip
            node = QTreeWidgetItem([text])
            node.setData(0, Qt.ItemDataRole.UserRole, (kind, value))
            if parent is None:
                self.sidebar.addTopLevelItem(node)
            else:
                parent.addChild(node)
            return node

        first = item(self.tr("All downloads"), "all")
        cats = item(self.tr("Categories"), "all")
        for category in self.categories:
            item(category.name, "category", category.id, cats)
        item(self.tr("Unfinished"), "unfinished")
        item(self.tr("Finished"), "finished")
        queues = item(self.tr("Queues"), "all")
        for queue in self.queues:
            item(queue.name, "queue", queue.id, queues)
        self.sidebar.expandAll()
        self.sidebar.setCurrentItem(first)
        self.sidebar.blockSignals(False)
        self._view_changed()

    def select_view(self, kind: str, value: int | None = None) -> None:
        for node in self._all_items():
            if node.data(0, Qt.ItemDataRole.UserRole) == (kind, value):
                self.sidebar.setCurrentItem(node)
                return

    def _all_items(self) -> list[QTreeWidgetItem]:
        found = []
        stack = [self.sidebar.topLevelItem(i) for i in range(self.sidebar.topLevelItemCount())]
        while stack:
            node = stack.pop(0)
            found.append(node)
            stack += [node.child(i) for i in range(node.childCount())]
        return found

    def _view_changed(self) -> None:
        current = self.sidebar.currentItem()
        if current is not None:
            kind, value = current.data(0, Qt.ItemDataRole.UserRole)
            self.proxy.set_view(kind, value)

    # --- selection & actions -------------------------------------------------------------------

    def selected_jobs(self) -> list[Job]:
        rows = self.table.selectionModel().selectedRows()
        return [self.proxy.data(index, JOB_ROLE) for index in rows]

    def _update_actions(self) -> None:
        jobs = self.selected_jobs()
        self.resume_action.setEnabled(any(j.state not in _RUNNING | {JobState.COMPLETED}
                                          for j in jobs))  # fmt: skip
        self.pause_action.setEnabled(any(j.state in _RUNNING | {JobState.QUEUED} for j in jobs))
        self.delete_action.setEnabled(bool(jobs))

    def resume_selected(self) -> None:
        for job in self.selected_jobs():
            job_id = job.id
            self.client.call(lambda m, j=job_id: m.start(j))

    def pause_selected(self) -> None:
        for job in self.selected_jobs():
            job_id = job.id
            self.client.call(lambda m, j=job_id: m.pause(j))

    def stop_all(self) -> None:
        self.client.call(lambda m: m.pause_all())

    def delete_selected(self, *, confirm: Callable[[int], tuple[bool, bool]] | None = None) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            return
        ok, delete_files = (confirm or self._confirm_delete)(len(jobs))
        if not ok:
            return
        for job in jobs:
            job_id = job.id
            self.client.call(lambda m, j=job_id: m.remove(j, delete_file=delete_files))

    def _confirm_delete(self, count: int) -> tuple[bool, bool]:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Delete"))
        box.setText(self.tr("Remove {0} download(s) from the list?").format(count))
        also = QCheckBox(self.tr("Also delete the downloaded file(s) from disk"))
        box.setCheckBox(also)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        ok = box.exec() == QMessageBox.StandardButton.Yes
        return ok, also.isChecked()

    def _context_menu(self, pos: QPoint) -> None:
        jobs = self.selected_jobs()
        if not jobs:
            return
        menu = self.build_context_menu(jobs)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def build_context_menu(self, jobs: list[Job]) -> QMenu:
        menu = QMenu(self)
        job = jobs[0]
        single = len(jobs) == 1
        done = job.state is JobState.COMPLETED
        if single and done:
            menu.addAction(self.tr("Open file"), lambda: self.open_file(job))
        if single and job.final_path is not None:
            menu.addAction(self.tr("Open folder"), lambda: self.open_folder(job))
        menu.addAction(self.resume_action)
        menu.addAction(self.pause_action)
        if single:
            menu.addAction(self.tr("Details"), lambda: self.show_details(job))
            url = job.request.url
            menu.addAction(self.tr("Copy link"), lambda: QGuiApplication.clipboard().setText(url))
            if not done:
                menu.addAction(self.tr("Refresh link..."), lambda: self.refresh_link(job))
        if any(j.state in (JobState.COMPLETED, JobState.FAILED) for j in jobs):
            menu.addAction(self.tr("Download again"), self.redownload_selected)
        move = menu.addMenu(self.tr("Move to queue"))
        for queue in self.queues:
            qid = queue.id
            move.addAction(queue.name, lambda q=qid: self.move_selected(q))
        menu.addSeparator()
        menu.addAction(self.delete_action)
        return menu

    def _double_clicked(self, index: QModelIndex) -> None:
        job = self.proxy.data(index, JOB_ROLE)
        if job.state is JobState.COMPLETED:
            self.open_file(job)
        else:
            self.show_details(job)

    def open_file(self, job: Job, *, confirm: Callable[[Path], bool] | None = None) -> bool:
        path = job.final_path
        if path is None or not path.exists():
            QMessageBox.warning(self, APP_NAME, self.tr("The file is no longer there."))
            return False
        if path.suffix.lower() in RISKY_SUFFIXES and not (confirm or self._confirm_run)(path):
            return False
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _confirm_run(self, path: Path) -> bool:
        answer = QMessageBox.warning(
            self, self.tr("Run program?"),
            self.tr("{0} is a program. Only run it if you trust where it came from. Run it?")
            .format(path.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )  # fmt: skip
        return answer == QMessageBox.StandardButton.Yes

    def open_folder(self, job: Job) -> None:
        if job.final_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(job.final_path.parent)))

    def show_details(self, job: Job) -> DetailsDialog:
        dialog = self._details.get(job.id)
        if dialog is None or not dialog.isVisible():
            dialog = DetailsDialog(self.client, job, self)
            self._details[job.id] = dialog
        dialog.show()
        dialog.raise_()
        return dialog

    def refresh_link(self, job: Job) -> None:
        dialog = AddUrlDialog(self, text="")
        dialog.setWindowTitle(self.tr("Refresh link"))
        dialog.tabs.setTabEnabled(1, False)
        if dialog.exec() and dialog.urls():
            url, job_id = dialog.urls()[0], job.id
            self.client.call(lambda m: m.refresh_link(job_id, url))

    def redownload_selected(self) -> None:
        for job in self.selected_jobs():
            job_id = job.id
            self.client.call(lambda m, j=job_id: m.redownload(j))

    def move_selected(self, queue_id: int) -> None:
        for job in self.selected_jobs():
            job_id = job.id
            self.client.call(lambda m, j=job_id: m.move_to_queue(j, queue_id))

    # --- adding downloads ------------------------------------------------------------------------

    def add_url(self) -> None:
        dialog = AddUrlDialog(self)
        if dialog.exec():
            self.add_urls(dialog.urls())

    def add_urls(self, urls: list[str], *, ask: bool = True) -> StartDownloadDialog | None:
        """One link: show the start dialog. Several: add them all to Main, sorted by category."""
        if not urls:
            return None
        if len(urls) == 1 and ask:
            return self.open_start_dialog(DownloadRequest(urls[0], self.settings.download_dir))
        for url in urls:
            name = filename_from_url(url) or ""
            category = match_category(name, self.categories) if self.categories else None
            folder = (category_folder(category, self.settings.download_dir) if category
                      else self.settings.download_dir)  # fmt: skip
            request = DownloadRequest(url=url, dest_dir=folder)
            cid = category.id if category else None
            self.client.call(lambda m, r=request, c=cid: m.add(r, category_id=c))
        return None

    def open_start_dialog(
        self, request: DownloadRequest, *, detect_media: bool = True
    ) -> StartDownloadDialog:
        dialog = StartDownloadDialog(
            self.client, request, base_dir=self.settings.download_dir,
            categories=self.categories, queues=self.queues, parent=self,
            detect_media=detect_media,
        )  # fmt: skip
        dialog.accepted.connect(lambda: self._start_chosen(dialog))
        dialog.mediaDetected.connect(self.mediaRequested.emit)
        dialog.setModal(False)
        dialog.show()
        return dialog

    def _start_chosen(self, dialog: StartDownloadDialog) -> None:
        choice = dialog.choice
        if choice is None:
            return
        self.client.call(
            lambda m: m.add(choice.request, queue_id=choice.queue_id, start=choice.start,
                            category_id=choice.category_id)
        )  # fmt: skip

    # --- drag and drop ----------------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.add_urls(self.urls_from_drop(event.mimeData()))
        event.acceptProposedAction()

    def urls_from_drop(self, mime) -> list[str]:
        text_parts: list[str] = []
        for url in mime.urls() if mime.hasUrls() else []:
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                small = path.is_file() and path.stat().st_size <= MAX_LINK_FILE
                if path.suffix.lower() == ".txt" and small:
                    text_parts.append(path.read_text("utf-8", errors="replace"))
            else:
                text_parts.append(url.toString())
        if not text_parts and mime.hasText():
            text_parts.append(mime.text())
        urls, _ = parse_url_list("\n".join(text_parts))
        return urls

    # --- live updates -----------------------------------------------------------------------------

    def _on_progress(self, event: Progress) -> None:
        self.model.update_progress(event)
        self._update_status()

    def _update_status(self) -> None:
        jobs = self.model.jobs()
        running = sum(1 for j in jobs if j.state in _RUNNING)
        self.count_label.setText(self.tr("{0} downloading, {1} total").format(running, len(jobs)))
        self.speed_label.setText(f"{format_bytes(self.model.total_speed())}/s")
        self._update_actions()

    def notify_finished(self, event: Finished) -> str:
        return self.tr("{0} has finished downloading.").format(event.path.name)

    # --- closing ----------------------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.allow_close and self.settings.close_to_tray and self.tray_available:
            event.ignore()
            self.hide()
            if self.on_close_to_tray is not None:
                self.on_close_to_tray()
            return
        event.accept()
        self.quitRequested.emit()
