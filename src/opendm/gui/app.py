"""OpenDM desktop app: wires the engine thread, main window, tray, IPC and dialogs."""

import argparse
import dataclasses
import datetime
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from opendm.core.app_settings import AppSettings
from opendm.core.batch import parse_url_list
from opendm.core.branding import APP_NAME
from opendm.core.bridge import EngineThread
from opendm.core.errors import ErrorKind
from opendm.core.events import Finished, PowerRequested, ToolProgress
from opendm.core.models import AfterAction, DownloadRequest, Job
from opendm.core.paths import app_data_dir, database_path, default_exe_dir, downloads_dir
from opendm.core.redact import redact_url
from opendm.core.settings import EngineSettings
from opendm.discovery.categories import category_folder, match_category
from opendm.engine.http.naming import filename_from_url
from opendm.engine.media.drm import PROTECTED_MESSAGE
from opendm.engine.media.formats import MediaOptions
from opendm.engine.media.ytdlp import MediaInfo
from opendm.gui.clipboard import ClipboardMonitor
from opendm.gui.dialogs.countdown import CountdownDialog
from opendm.gui.dialogs.media import MediaDialog
from opendm.gui.dialogs.queues import QueuesDialog
from opendm.gui.dialogs.settings import SettingsDialog
from opendm.gui.dialogs.tools import ToolProgressDialog, ToolsConsentDialog, ToolsPanel
from opendm.gui.dialogs.wizard import FirstRunWizard
from opendm.gui.engine_client import EngineClient
from opendm.gui.icons import app_icon
from opendm.gui.main_window import MainWindow
from opendm.gui.power import perform_power
from opendm.gui.theme import SystemThemeFollower, apply_theme
from opendm.gui.tray import Tray
from opendm.ipc import client as ipc_client
from opendm.ipc.protocol import Request
from opendm.ipc.server import IpcServer
from opendm.ipc.single_instance import InstanceLock
from opendm.queue.scheduler import DownloadManager
from opendm.tools.manager import ToolInfo


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
        defaults = AppSettings.defaults(downloads=downloads or downloads_dir(), data_dir=data_dir)
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
        hidden = (minimized or self.settings.start_minimized) and self.tray is not None
        if not hidden:
            self.show_window()
        self.check_tool_updates()
        if urls:
            self.show_window()
            self.window.add_urls(list(urls))

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    # --- settings -----------------------------------------------------------------------------

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

    def open_settings(self) -> SettingsDialog:
        panel = ToolsPanel(
            self.client,
            on_install=lambda names: self.install_tools(names, then=panel.refresh),
            on_existing=self._use_existing_tool,
            update_check=self.settings.tool_update_check,
        )
        self.tools_panel = panel
        dialog = SettingsDialog(self.settings, self.window.categories, self.window, panel)
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

    def ask_for_tools(self, missing: list[str], then: Callable[[], None]) -> None:
        def show(sizes: dict[str, int | None] | BaseException) -> None:
            known = sizes if isinstance(sizes, dict) else {}
            dialog = ToolsConsentDialog(missing, self.settings.tools_dir, known, self.window)
            dialog.accepted.connect(lambda: self._consented(dialog, then))
            self.consent_dialog = dialog
            dialog.show()

        self.client.call(lambda m: m.tool_downloads(), on_done=show, on_error=show)

    def _consented(self, dialog: ToolsConsentDialog, then: Callable[[], None]) -> None:
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

    def _analyze(self, request: DownloadRequest) -> None:
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

        self.client.call(lambda m: m.analyze_media(request), on_done=done, on_error=failed)

    def _pick_media(self, request: DownloadRequest, info: MediaInfo) -> MediaDialog:
        dialog = MediaDialog(
            info, base_dir=self.settings.download_dir, categories=self.window.categories,
            queues=self.window.queues, parent=self.window,
        )  # fmt: skip
        dialog.accepted.connect(lambda: self._add_media(request, dialog))
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
        if request.cmd == "activate":
            self.show_window()
            if args.get("urls"):
                self.window.add_urls(args["urls"])
            return None
        if request.cmd == "list":
            return self.client.call(lambda m: [job_summary(j) for j in m.jobs.list()])
        if request.cmd == "add":
            return self.client.call(self._ipc_add(args))
        job_id = args["job_id"]
        if request.cmd == "pause":
            return self.client.call(lambda m: m.pause(job_id))
        if request.cmd == "resume":
            return self.client.call(lambda m: m.start(job_id))
        if request.cmd == "remove":
            delete = bool(args.get("delete_file", False))
            return self.client.call(lambda m: m.remove(job_id, delete_file=delete))
        raise ValueError(f"unsupported command {request.cmd}")

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

    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setWindowIcon(app_icon())
    qapp.setQuitOnLastWindowClosed(False)
    app = Application(qapp, app_data_dir(default_exe_dir()))
    app.start(urls=urls, minimized=args.minimized)
    try:
        return qapp.exec()
    finally:
        app.shutdown()
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
