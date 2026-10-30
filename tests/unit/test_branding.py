import re

from opendm.core import branding


def test_app_name() -> None:
    assert branding.APP_NAME == "OpenDM"


def test_native_host_name_follows_chrome_rules() -> None:
    # Chrome: lowercase alphanumerics, underscores and dots; no leading/trailing dot.
    assert re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)*", branding.NATIVE_HOST_NAME)


def test_partial_suffix_is_an_extension() -> None:
    assert branding.PARTIAL_SUFFIX.startswith(".")
    assert branding.STATE_SUFFIX.startswith(".")
    assert branding.PARTIAL_SUFFIX != branding.STATE_SUFFIX


def test_executable_names_derive_from_app_name() -> None:
    assert branding.GUI_EXE == "OpenDM.exe"
    assert branding.CLI_EXE == "opendm-cli.exe"
    assert branding.HOST_EXE == "opendm-host.exe"
