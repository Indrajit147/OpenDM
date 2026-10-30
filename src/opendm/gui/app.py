"""OpenDM desktop app: wires the engine thread, main window, tray, IPC and dialogs."""

import argparse
import contextlib
import dataclasses
import datetime
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from opendm import __version__
from opendm.core.app_settings import AppSettings
from opendm.core.batch import parse_url_list
from opendm.core.branding import APP_MUTEX, APP_NAME, APP_USER_MODEL_ID
from opendm.core.bridge import EngineThread
from opendm.core.errors import ErrorKind
from opendm.core.events import Finished, PowerRequested, ToolProgress, ToolsMissing
from opendm.core.logs import export_diagnostics, setup_logging
from opendm.core.models import AfterAction, DownloadRequest, Job
from opendm.core.paths import (
    app_data_dir,
    database_path,
    default_exe_dir,
    downloads_dir,
    is_portable,
)
from opendm.core.redact import redact_url
from opendm.core.settings import EngineSettings
from opendm.core.windows import set_app_user_model_id
from opendm.discovery.categories import category_folder, match_category
from opendm.engine.http.naming import filename_from_url
from opendm.engine.media.drm import PROTECTED_MESSAGE
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import MediaInfo
from opendm.gui.clipboard import ClipboardMonitor
from opendm.gui.dialogs.browser import BrowserPanel
from opendm.gui.dialogs.countdown import CountdownDialog
from opendm.gui.dialogs.links import LinkPickerDialog
from opendm.gui.dialogs.media import MediaDialog
from opendm.gui.dialogs.queues import QueuesDialog
from opendm.gui.dialogs.settings import SettingsDialog
from opendm.gui.dialogs.tools import ToolProgressDialog, ToolsConsentDialog, ToolsPanel
from opendm.gui.dialogs.update import UpdateDialog
from opendm.gui.dialogs.wizard import FirstRunWizard
from opendm.gui.engine_client import EngineClient
from opendm.gui.icons import app_icon
from opendm.gui.main_window import MainWindow
from opendm.gui.power import perform_power
from opendm.gui.theme import SystemThemeFollower, apply_theme
from opendm.gui.tray import Tray
from opendm.host import register as native_host
from opendm.ipc import client as ipc_client
from opendm.ipc.protocol import Request
from opendm.ipc.server import IpcServer
from opendm.ipc.single_instance import InstanceLock
from opendm.queue.scheduler import DownloadManager
from opendm.tools.location import (
    default_tools_dir,
    relocate_tools,
    same_folder,
    tools_dir_problem,
)
from opendm.tools.manager import ToolInfo
from opendm.updater.github_releases import AppUpdate, Updater, clean_old_installers

log = logging.getLogger(__name__)


def _relay_progress(dialog: ToolProgressDialog) -> Callable[[ToolProgress], None]:
    def relay(event: ToolProgress) -> None:
        if dialog.isVisible():
            dialog.show_progress(event.tool, event.done, event.total)

    return relay


def job_summary(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "state": str(job.state),
        "downloaded": job.downloaded,
        "size": job.size,
        "url": redact_url(job.request.url),
    }


class Application(QObject):
    def __init__(
        self,
        qapp: QApplication,
        data_dir: Path,
        *,
        downloads: Path | None = None,
        tools_dir: Path | None = None,
        updates_dir: Path | None = None,
        portable: bool = False,
        ipc_name: str | None = None,
        engine_settings: EngineSettings | None = None,
        power: Callable[[AfterAction], None] = perform_power,
        countdown_seconds: int = 60,
        scheduler_interval: float = 30.0,
    ) -> None:
        super().__init__()
        self.qapp = qapp
        data_dir.mkdir(parents=True, exist_ok=True)
        self.engine = EngineThread(
            database_path(data_dir),
            settings=engine_settings,
            scheduler_interval=scheduler_interval,
            temp_dir=data_dir / "tmp",  # short-lived cookie files for yt-dlp (per-user folder)
        )
        self.engine.start()
        self.client = EngineClient(self.engine, self)
        self.data_dir = data_dir
        self.downloads_folder = downloads or downloads_dir()  # Windows' Downloads folder
        self.default_tools_dir = tools_dir or default_tools_dir(None, data_dir)
        self.updates_dir = updates_dir or data_dir / "updates"  # installers from the updater
        self.portable = portable
        self.updater = Updater()
        self.update_dialog: UpdateDialog | None = None
        self.run_after_quit: Path | None = None  # a verified installer, started after we exit
        defaults = AppSettings.defaults(
            downloads=self.downloads_folder, data_dir=data_dir, tools_dir=self.default_tools_dir
        )
        stored = self.engine.call(lambda m: m.settings_store.all()).result(10)
        self.settings = AppSettings.from_dict(stored, defaults)
        self._power = power
        self._countdown_seconds = countdown_seconds
        self.countdown: CountdownDialog | None = None
        self._apply_engine_settings()
        self._theme_follower = SystemThemeFollower(qapp)
        apply_theme(qapp, self.settings.theme)

        self.window = MainWindow(self.client, self.settings)
        self.window.settingsRequested.connect(self.open_settings)
        self.window.queuesRequested.connect(self.open_queues)
        self.window.quitRequested.connect(self.quit)
        self.window.mediaRequested.connect(self.open_media)
        self.window.on_close_to_tray = self._closed_to_tray
        self.consent_dialog: ToolsConsentDialog | None = None
        self.media_dialog: MediaDialog | None = None
        self.busy_dialog: ToolProgressDialog | None = None
        self.tools_panel: ToolsPanel | None = None
        self.link_dialog: LinkPickerDialog | None = None

        self.tray: Tray | None = None
        if Tray.available():
            self.tray = Tray(self.window)
            self.tray.show_action.triggered.connect(self.show_window)
            self.tray.add_action.triggered.connect(self._tray_add)
            self.tray.pause_all_action.triggered.connect(
                lambda: self.client.call(lambda m: m.pause_all())
            )
            self.tray.quit_action.triggered.connect(self.quit)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
        self.window.tray_available = self.tray is not None

        self.clipboard = ClipboardMonitor(qapp.clipboard(), self._known_extensions, self)
        self.clipboard.enabled = self.settings.clipboard_monitor
        self.clipboard.linkCopied.connect(self._link_copied)
        self._offered_link: str | None = None
        if self.tray is not None:
            self.tray.messageClicked.connect(self._accept_offered_link)

        self.client.finished.connect(self._finished)
        self.client.powerRequested.connect(self._power_requested)
        self.client.toolsMissing.connect(self._tools_missing)

        self.ipc = IpcServer(self.handle_ipc, self)
        self.ipc_listening = self.ipc.listen(ipc_name or ipc_client.default_name())

    # --- startup -----------------------------------------------------------------------------

    def start(
        self, *, urls: Sequence[str] = (), minimized: bool = False, wizard: bool = True
    ) -> None:
        if wizard and not self.settings.first_run_done:
            dialog = FirstRunWizard(self.settings, self.window)
            if dialog.exec():
                self.save_settings(dialog.result_settings())
            else:
                self.save_settings(_with(self.settings, first_run_done=True))
        self.relocate_tools_if_needed()
        clean_old_installers(self.updates_dir)
        hidden = (minimized or self.settings.start_minimized) and self.tray is not None
        if not hidden:
            self.show_window()
        self.check_tool_updates()
        self.check_app_update()
        if urls:
            self.show_window()
            self.window.add_urls(list(urls))

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def notify(self, title: str, text: str) -> None:
        if self.tray is not None:
            self.tray.notify(title, text)

    # --- settings -----------------------------------------------------------------------------

    def export_diagnostics(
        self,
        target: Path,
        on_done: Callable[[Path], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        """ZIP of logs, settings and versions for a bug report (secrets removed).

        Runs on the engine thread (tool versions come from running the tools)."""
        log_dir, settings = self.data_dir / "logs", self.settings.to_dict()
        portable = self.portable

        async def export(m: DownloadManager) -> Path:
            tools: dict[str, str | None] = {}
            with contextlib.suppress(Exception):
                tools = {t.name: t.version for t in await m.tool_status()}
            about = {"version": __version__, "portable": portable, "tools": tools}
            return export_diagnostics(target, log_dir=log_dir, settings=settings, about=about)

        self.client.call(export, on_done=on_done, on_error=on_error)

    def tools_problem(self, folder: Path, download_dir: Path | None = None) -> str | None:
        return tools_dir_problem(
            folder, download_dir or self.settings.download_dir, self.downloads_folder
        )

    def relocate_tools_if_needed(self) -> None:
        """Tools in the download folder (0.7 allowed it) or in 0.7's default folder on C: move
        to the new default (next to the programs). A folder the user chose elsewhere stays."""
        old, new = self.settings.tools_dir, self.default_tools_dir
        old_default = same_folder(old, self.data_dir / "tools") and not same_folder(old, new)
        if self.tools_problem(old) is None and not old_default:
            return
        moved = relocate_tools(old, new)
        log.info("tools folder %s -> %s (moved: %s)", old, new, ", ".join(moved) or "nothing")
        changes: dict[str, Any] = {"tools_dir": new}
        for field, name in (("ytdlp_path", "yt-dlp"), ("ffmpeg_path", "ffmpeg")):
            override = getattr(self.settings, field)
            if override and name in moved:
                with contextlib.suppress(ValueError):
                    rest = Path(override).relative_to(old / name)
                    changes[field] = str(new / name / rest)
        self.save_settings(_with(self.settings, **changes))
        if moved:
            self.notify(
                self.tr("Helper tools moved"),
                self.tr("yt-dlp and FFmpeg now live in {0}, outside your download folder.").format(
                    new
                ),
            )

    def _apply_engine_settings(self) -> None:
        engine, limit = self.settings.engine_settings(), self.settings.global_limit
        folder, overrides = self.settings.tools_dir, self.settings.tool_overrides()
        self.engine.call(lambda m: m.apply_settings(engine, limit))
        self.engine.call(lambda m: m.configure_tools(folder, overrides))

    def save_settings(self, settings: AppSettings) -> None:
        self.settings = settings
        self.window.settings = settings
        values = settings.to_dict()
        self.client.call(lambda m: m.settings_store.set_many(values))
        self._apply_engine_settings()
        apply_theme(self.qapp, settings.theme)
        self.clipboard.enabled = settings.clipboard_monitor

    def _browser_panel(self) -> BrowserPanel | None:
        if sys.platform != "win32":
            return None

        def register() -> Path:
            host, folder = native_host.registration_target()
            return native_host.register(host, folder)

        def unregister() -> None:
            native_host.unregister(manifest_dir=native_host.registration_target()[1])

        return BrowserPanel(
            status=native_host.status, register=register, unregister=unregister,
            extension_dir=native_host.extension_dir(),
            open_folder=lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))),
        )  # fmt: skip

    def open_settings(self) -> SettingsDialog:
        panel = ToolsPanel(
            self.client,
            on_install=lambda names: self.install_tools(names, then=panel.refresh),
            on_existing=self._use_existing_tool,
            update_check=self.settings.tool_update_check,
        )
        self.tools_panel = panel
        dialog = SettingsDialog(
            self.settings,
            self.window.categories,
            self.window,
            panel,
            self._browser_panel(),
            tools_check=self.tools_problem,
            version=__version__,
            on_check_now=lambda: self.check_app_update(manual=True),
            on_export=self.export_diagnostics,
        )
        dialog.accepted.connect(lambda: self._settings_accepted(dialog))
        dialog.setModal(True)
        dialog.show()
        return dialog

    # --- video/audio (yt-dlp) ---------------------------------------------------------------------

    def open_media(self, request: DownloadRequest) -> None:
        """Page or stream link: make sure the tools exist, analyze it, show the quality picker."""

        def checked(status: list[ToolInfo]) -> None:
            missing = [t.name for t in status if not t.installed]
            if missing:
                self.ask_for_tools(missing, then=lambda: self._analyze(request))
            else:
                self._analyze(request)

        self.client.call(lambda m: m.tool_status(), on_done=checked, on_error=self._show_error)

    def ask_for_tools(self, missing: list[str], then: Callable[[], None] | None) -> None:
        def show(sizes: dict[str, int | None] | BaseException) -> None:
            known = sizes if isinstance(sizes, dict) else {}
            dialog = ToolsConsentDialog(
                missing, self.settings.tools_dir, known, self.window, check=self.tools_problem
            )
            dialog.accepted.connect(lambda: self._consented(dialog, then))
            self.consent_dialog = dialog
            dialog.show()

        self.client.call(lambda m: m.tool_downloads(), on_done=show, on_error=show)

    def _tools_missing(self, event: ToolsMissing) -> None:
        """Video/audio jobs are waiting for the tools: offer to download them (once)."""
        if self.consent_dialog is not None and self.consent_dialog.isVisible():
            return
        self.notify(
            self.tr("Video downloads are waiting"),
            self.tr("{0} is missing. OpenDM can download it again.").format(
                " and ".join("FFmpeg" if n == "ffmpeg" else n for n in event.names)
            ),
        )
        self.ask_for_tools(list(event.names), then=None)

    def _consented(self, dialog: ToolsConsentDialog, then: Callable[[], None] | None) -> None:
        folder = dialog.folder()
        if folder != self.settings.tools_dir:
            self.save_settings(_with(self.settings, tools_dir=folder))
        self.install_tools(dialog.missing, then=then)

    def install_tools(self, names: list[str], then: Callable[[], None] | None = None) -> None:
        progress = ToolProgressDialog(self.window)
        self.busy_dialog = progress
        self.client.toolProgress.connect(_relay_progress(progress))
        progress.show()

        async def install(m: DownloadManager) -> None:
            for name in names:
                await m.install_tool(name)

        def finished(_: object) -> None:
            progress.close()
            if then is not None:
                then()

        def failed(error: BaseException) -> None:
            progress.close()
            self._show_error(error)

        self.client.call(install, on_done=finished, on_error=failed)

    def _use_existing_tool(self, name: str, path: Path) -> None:
        def chosen(info: ToolInfo) -> None:
            field = "ytdlp_path" if name == "yt-dlp" else "ffmpeg_path"
            self.save_settings(_with(self.settings, **{field: str(info.path)}))
            if self.tools_panel is not None:
                self.tools_panel.refresh()

        self.client.call(
            lambda m: m.use_existing_tool(name, path), on_done=chosen, on_error=self._show_error
        )

    def _analyze(self, request: DownloadRequest, *, playlist: bool = False) -> None:
        busy = ToolProgressDialog(self.window)
        busy.setWindowTitle(self.tr("Video or audio"))
        busy.show_step(self.tr("Looking for video and audio on the page..."))
        self.busy_dialog = busy
        busy.show()

        def done(info: MediaInfo) -> None:
            busy.close()
            self._pick_media(request, info)

        def failed(error: BaseException) -> None:
            busy.close()
            self._media_failed(request, error)

        self.client.call(
            lambda m: m.analyze_media(request, playlist=playlist), on_done=done, on_error=failed
        )

    def _pick_media(self, request: DownloadRequest, info: MediaInfo) -> MediaDialog:
        dialog = MediaDialog(
            info, base_dir=self.settings.download_dir, categories=self.window.categories,
            queues=self.window.queues, parent=self.window,
        )  # fmt: skip
        dialog.accepted.connect(lambda: self._add_media(request, dialog))

        def whole_playlist() -> None:
            dialog.close()
            self._analyze(request, playlist=True)

        dialog.wholePlaylistRequested.connect(whole_playlist)
        self.media_dialog = dialog
        dialog.show()
        return dialog

    def _add_media(self, request: DownloadRequest, dialog: MediaDialog) -> None:
        choice = dialog.choice
        if choice is None:
            return
        for entry in choice.entries:
            item = dataclasses.replace(request, url=entry.url, dest_dir=choice.folder)
            self.client.call(
                lambda m, r=item: m.add_media(
                    r, choice.options, queue_id=choice.queue_id, start=choice.start,
                    category_id=choice.category_id,
                )
            )  # fmt: skip

    def _media_failed(self, request: DownloadRequest, error: BaseException) -> None:
        kind = getattr(error, "kind", None)
        if kind is ErrorKind.PROTECTED:
            QMessageBox.information(self.window, APP_NAME, PROTECTED_MESSAGE)
            return
        message = getattr(error, "message", None) or str(error)
        answer = QMessageBox.question(
            self.window, APP_NAME,
            self.tr("No video or audio could be found ({0}).\n\n"
                    "Download the link as a normal file instead?").format(message),
        )  # fmt: skip
        if answer == QMessageBox.StandardButton.Yes:
            self.window.open_start_dialog(request, detect_media=False)

    def _show_error(self, error: BaseException) -> None:
        message = getattr(error, "message", None) or str(error)
        QMessageBox.warning(self.window, APP_NAME, message)

    def check_tool_updates(self, *, force: bool = False) -> None:
        """Opt-in weekly yt-dlp update check (spec 6.8): only notifies, never installs."""
        if not (self.settings.tool_update_check or force):
            return
        today = datetime.date.today()
        last = self.settings.last_tool_check
        if not force and last and (today - datetime.date.fromisoformat(last)).days < 7:
            return
        self.save_settings(_with(self.settings, last_tool_check=today.isoformat()))

        def done(result: tuple[str | None, str] | None) -> None:
            if result is not None and self.tray is not None:
                self.tray.notify(
                    self.tr("yt-dlp update available"),
                    self.tr("Version {0} is out. Settings -> Tools -> Download / update.").format(
                        result[1]
                    ),
                )

        self.client.call(lambda m: m.check_ytdlp_update(), on_done=done, on_error=lambda e: None)

    # --- app updates (spec 6.9) -------------------------------------------------------------

    def check_app_update(self, *, manual: bool = False) -> None:
        """Ask GitHub for a newer OpenDM: at startup if turned on, or from "Check now"."""
        if not (manual or self.settings.update_check):
            return
        prereleases = self.settings.include_prereleases
        updater = self.updater

        def done(update: AppUpdate | None) -> None:
            log.info("update check: %s", update.version if update else "up to date")
            if update is None:
                if manual:
                    QMessageBox.information(
                        self.window, APP_NAME,
                        self.tr("You have the latest version ({0}).").format(__version__),
                    )  # fmt: skip
                return
            if not manual and str(update.version) == self.settings.skipped_version:
                return
            self.show_update(update)

        def failed(error: BaseException) -> None:
            log.warning("update check failed: %s", error)
            if manual:  # a startup check fails quietly (offline, GitHub busy)
                message = getattr(error, "message", None) or str(error)
                QMessageBox.warning(
                    self.window, APP_NAME,
                    self.tr("Could not check for updates: {0}").format(message),
                )  # fmt: skip

        self.client.call(
            lambda m: updater.check(__version__, prereleases=prereleases),
            on_done=done, on_error=failed,
        )  # fmt: skip

    def show_update(self, update: AppUpdate) -> UpdateDialog:
        if self.update_dialog is not None:
            self.update_dialog.close()
        dialog = UpdateDialog(update, __version__, portable=self.portable, parent=self.window)
        dialog.installRequested.connect(lambda: self._install_update(dialog))
        dialog.skipRequested.connect(
            lambda: self.save_settings(_with(self.settings, skipped_version=str(update.version)))
        )
        dialog.pageRequested.connect(
            lambda: QDesktopServices.openUrl(QUrl(update.page_url or self.updater.source.page_url))
        )
        self.update_dialog = dialog
        self.show_window()
        dialog.show()
        return dialog

    def _install_update(self, dialog: UpdateDialog) -> None:
        update, folder, updater = dialog.update_info, self.updates_dir, self.updater
        dialog.set_busy(self.tr("Downloading the installer..."))

        def downloaded(path: Path) -> None:
            log.info("update %s downloaded and verified: %s", update.version, path)
            # The installer replaces our files, so it runs after OpenDM has exited.
            self.run_after_quit = path
            dialog.accept()
            self.quit()

        def failed(error: BaseException) -> None:
            dialog.set_idle()
            message = getattr(error, "message", None) or str(error)
            QMessageBox.warning(
                dialog, APP_NAME, self.tr("The update was not installed: {0}").format(message)
            )

        self.client.call(
            lambda m: updater.download(update, folder, dialog.progressed.emit),
            on_done=downloaded, on_error=failed,
        )  # fmt: skip

    def _settings_accepted(self, dialog: SettingsDialog) -> None:
        self.save_settings(dialog.result_settings())
        categories = dialog.result_categories()

        def store(m: DownloadManager) -> None:
            for category in categories:
                m.categories.save(category)

        self.client.call(store, on_done=lambda _: self.window.reload())

    def open_queues(self) -> QueuesDialog:
        dialog = QueuesDialog(self.client, self.window)
        dialog.finished.connect(lambda _: self.window.reload())
        dialog.setModal(True)
        dialog.show()
        return dialog

    def _known_extensions(self) -> list[str]:
        return [e for c in self.window.categories if not c.fallback for e in c.extensions]

    # --- tray, notifications, clipboard ---------------------------------------------------------

    def _tray_add(self) -> None:
        self.show_window()
        self.window.add_url()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):  # fmt: skip
            self.show_window()

    def _closed_to_tray(self) -> None:
        if not self.settings.close_notice_shown and self.tray is not None:
            self.tray.notify(APP_NAME, self.tr("OpenDM keeps running in the tray. "
                                               "Use Quit in its menu to exit."))  # fmt: skip
            self.save_settings(_with(self.settings, close_notice_shown=True))

    def _finished(self, event: Finished) -> None:
        if self.settings.notifications and self.tray is not None:
            self.tray.notify(self.tr("Download complete"), self.window.notify_finished(event))

    def _link_copied(self, url: str) -> None:
        self._offered_link = url
        if self.tray is not None:
            name = filename_from_url(url) or url
            self.tray.notify(self.tr("Link copied"),
                             self.tr("Click to download {0}").format(name))  # fmt: skip

    def _accept_offered_link(self) -> None:
        if self._offered_link:
            self.show_window()
            self.window.add_urls([self._offered_link])
            self._offered_link = None

    def _power_requested(self, event: PowerRequested) -> CountdownDialog:
        self.countdown = CountdownDialog(
            event.action, event.queue_name, self._power,
            seconds=self._countdown_seconds, parent=self.window,
        )  # fmt: skip
        self.countdown.show()
        return self.countdown

    # --- IPC ------------------------------------------------------------------------------------

    def handle_ipc(self, request: Request) -> Any:
        args = request.args
        if request.cmd == "ping":
            return "pong"
        if request.cmd == "quit":  # same user only (the pipe is per-user); used by the build tests
            QTimer.singleShot(0, self.quit)
            return None
        if request.cmd == "activate":
            self.show_window()
            if args.get("urls"):
                self.window.add_urls(args["urls"])
            return None
        if request.cmd == "list":
            return self.client.call(lambda m: [job_summary(j) for j in m.jobs.list()])
        if request.cmd == "add":
            return self.client.call(self._ipc_add(args))
        if request.cmd == "capture":
            return self.capture(args)
        if request.cmd == "capture_links":
            return self.capture_links(args)
        job_id = args["job_id"]
        if request.cmd == "pause":
            return self.client.call(lambda m: m.pause(job_id))
        if request.cmd == "resume":
            return self.client.call(lambda m: m.start(job_id))
        if request.cmd == "remove":
            delete = bool(args.get("delete_file", False))
            return self.client.call(lambda m: m.remove(job_id, delete_file=delete))
        raise ValueError(f"unsupported command {request.cmd}")

    def capture(self, args: dict[str, Any]) -> dict[str, str]:
        """A download handed over by the browser extension: confirm it in a dialog."""
        request = DownloadRequest(
            url=args["url"],
            dest_dir=self.settings.download_dir,
            filename=args.get("filename") or None,
            referrer=args.get("referrer") or args.get("page_url") or None,
            user_agent=args.get("user_agent") or None,
            cookies=args.get("cookies") or None,
        )
        self.show_window()
        if args.get("media"):
            self.open_media(request)
            return {"shown": "media"}
        self.window.open_start_dialog(request)
        return {"shown": "start"}

    def capture_links(self, args: dict[str, Any]) -> dict[str, Any]:
        """ "Download all links": let the user pick which ones."""
        self.show_window()
        dialog = LinkPickerDialog(
            args["urls"], self.window.categories, page_title=args.get("page_title", ""),
            parent=self.window,
        )  # fmt: skip
        referrer = args.get("page_url") or args.get("referrer") or None
        dialog.accepted.connect(
            lambda: self.window.add_urls(dialog.selected(), ask=False, referrer=referrer)
        )
        self.link_dialog = dialog
        dialog.show()
        return {"shown": "links", "count": dialog.list.count()}

    def _ipc_add(self, args: dict[str, Any]) -> Callable[[DownloadManager], Any]:
        base = self.settings.download_dir

        async def add(m: DownloadManager) -> dict[str, Any]:
            url = args["url"]
            media = MediaOptions.from_dict(args["media"]) if "media" in args else None
            name = args.get("filename") or filename_from_url(url) or ""
            if media is not None:
                name = "x.mp3" if media.audio_only else "x." + media.container
            category = match_category(name, m.categories.list())
            dest = (
                Path(args["dest_dir"]) if args.get("dest_dir") else category_folder(category, base)
            )
            request = DownloadRequest(
                url=url, dest_dir=dest, filename=args.get("filename"),
                headers=args.get("headers") or {}, user_agent=args.get("user_agent"),
                referrer=args.get("referrer"), cookies=args.get("cookies"),
                checksum=args.get("checksum"), speed_limit=args.get("speed_limit"),
            )  # fmt: skip
            if media is not None:
                job = await m.add_media(
                    request, media, start=args.get("start", True), category_id=category.id,
                    queue_id=args.get("queue_id", 1),
                )  # fmt: skip
                return job_summary(job)
            job = await m.add(
                request, start=args.get("start", True), category_id=category.id,
                queue_id=args.get("queue_id", 1), connections=args.get("connections"),
            )  # fmt: skip
            return job_summary(job)

        return add

    # --- shutdown --------------------------------------------------------------------------------

    def quit(self) -> None:
        self.window.allow_close = True
        self.window.close()
        self.qapp.quit()

    def shutdown(self) -> None:
        self.ipc.close()
        self.client.stop()
        if self.tray is not None:
            self.tray.hide()
        self.engine.stop()


def _with(settings: AppSettings, **changes: Any) -> AppSettings:
    import dataclasses

    return dataclasses.replace(settings, **changes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opendm", description=f"{APP_NAME} download manager")
    parser.add_argument("urls", nargs="*", help="links to download")
    parser.add_argument("--minimized", action="store_true", help="start in the tray")
    args = parser.parse_args(argv)
    urls, _ = parse_url_list("\n".join(args.urls))

    lock = InstanceLock(ipc_client.default_name())
    if not lock.acquire():
        # Already running: hand the links over and bring its window forward.
        for _ in range(20):
            try:
                ipc_client.request("activate", {"urls": urls}, timeout=5)
                return 0
            except ipc_client.AppNotRunning:
                import time

                time.sleep(0.25)  # the other instance is still starting
            except ipc_client.IpcError:
                return 1
        return 1

    running = InstanceLock(APP_MUTEX)  # seen by the installer (AppMutex); "lock" decides who runs
    running.acquire()
    set_app_user_model_id(APP_USER_MODEL_ID)
    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setWindowIcon(app_icon())
    qapp.setQuitOnLastWindowClosed(False)
    exe_dir = default_exe_dir()
    data_dir = app_data_dir(exe_dir)
    portable = exe_dir is not None and is_portable(exe_dir)
    setup_logging(data_dir / "logs")
    log.info("OpenDM %s starting (data %s, portable %s)", __version__, data_dir, portable)
    app = Application(
        qapp, data_dir, tools_dir=default_tools_dir(exe_dir, data_dir), portable=portable,
        # Installed: next to the programs (the drive the user chose), removed on uninstall.
        updates_dir=exe_dir / "updates" if exe_dir is not None and not portable else None,
    )  # fmt: skip
    app.start(urls=urls, minimized=args.minimized)
    try:
        return qapp.exec()
    finally:
        app.shutdown()
        running.release()
        lock.release()
        if app.run_after_quit is not None:
            log.info("starting the installer %s", app.run_after_quit)
            run_installer(app.run_after_quit)
        log.info("OpenDM stopped")


def run_installer(path: Path) -> None:
    """Start the verified installer once OpenDM has released its mutex (it is not silent)."""
    import subprocess

    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen([str(path)], creationflags=flags, close_fds=True)


if __name__ == "__main__":
    sys.exit(main())
