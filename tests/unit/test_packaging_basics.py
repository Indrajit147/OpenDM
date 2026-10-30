"""Version, Windows identity and the mutex the installer checks (M7)."""

import re
import sys
import uuid
from importlib.metadata import version

import pytest

from opendm import __version__
from opendm.core import branding
from opendm.core.version import parse_version
from opendm.core.windows import set_app_user_model_id
from opendm.ipc.single_instance import InstanceLock


def test_version_has_one_source() -> None:
    v = parse_version(__version__)  # raises if the format is wrong
    # pyproject reads it from opendm/__init__.py; pip writes "0.8.0-rc.1" as "0.8.0rc1".
    short = {"alpha": "a", "beta": "b", "rc": "rc"}
    expected = v.base + (f"{short[v.pre]}{v.pre_number}" if v.pre else "")
    assert version("opendm") == expected


def test_app_mutex_name_is_fixed_and_plain() -> None:
    # Inno Setup's AppMutex needs a fixed name (no user name, no backslash).
    assert re.fullmatch(r"[A-Za-z0-9-]+", branding.APP_MUTEX)
    assert branding.APP_MUTEX != branding.PIPE_NAME


def test_app_mutex_is_seen_while_held() -> None:
    name = f"{branding.APP_MUTEX}-test-{uuid.uuid4().hex[:8]}"
    held = InstanceLock(name)
    assert held.acquire()
    assert not InstanceLock(name).acquire()
    held.release()


def test_app_user_model_id_format() -> None:
    # CompanyName.ProductName, at most 128 characters, no spaces.
    assert re.fullmatch(r"[A-Za-z0-9]+\.[A-Za-z0-9]+", branding.APP_USER_MODEL_ID)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_set_app_user_model_id() -> None:
    assert set_app_user_model_id(branding.APP_USER_MODEL_ID)
