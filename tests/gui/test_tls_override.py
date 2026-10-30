"""Turning off certificate checks: only after a certificate error, per download (spec 7)."""

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.models import DownloadRequest
from tests.gui.conftest import GuiApp
from tests.server.app import FaultServer


def dialog_for(gui: GuiApp, server: FaultServer, qtbot):
    request = DownloadRequest(server.url("/file/a.bin?size=10K"), gui.settings.download_dir)
    dialog = gui.window.open_start_dialog(request, detect_media=False)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.probe_result is not None, timeout=10_000)
    return dialog


def test_checks_stay_on_and_the_option_is_hidden(qtbot, gui: GuiApp, server) -> None:
    dialog = dialog_for(gui, server, qtbot)
    assert not dialog.insecure_box.isVisible()
    dialog.start_button.click()
    assert dialog.choice is not None and dialog.choice.request.verify_tls


def test_certificate_error_offers_a_per_download_override(qtbot, gui: GuiApp, server) -> None:
    dialog = dialog_for(gui, server, qtbot)
    dialog._probe_failed(DownloadError(ErrorKind.TLS, "certificate verify failed"))
    assert dialog.insecure_box.isVisible() and not dialog.insecure_box.isChecked()
    assert "certificate" in dialog.error_label.text().lower()
    dialog.insecure_box.setChecked(True)
    assert "only" in dialog.insecure_warning.text().lower()  # explains the risk
    assert dialog.insecure_warning.isVisible()
    dialog.start_button.click()
    assert dialog.choice is not None and not dialog.choice.request.verify_tls


def test_other_errors_do_not_offer_it(qtbot, gui: GuiApp, server) -> None:
    dialog = dialog_for(gui, server, qtbot)
    dialog._probe_failed(DownloadError(ErrorKind.NOT_FOUND, "server replied HTTP 404"))
    assert not dialog.insecure_box.isVisible()
