"""App updater against a fake GitHub releases API on the test server (spec 6.9, M8)."""

import hashlib
import json
from pathlib import Path

import pytest

from opendm.core.errors import DownloadError, ErrorKind
from opendm.core.version import parse_version
from opendm.updater.github_releases import (
    Updater,
    UpdateSource,
    clean_old_installers,
    pick_update,
)
from tests.server.app import FaultServer

INSTALLER = b"MZ-fake-installer" * 500


def asset(name: str, url: str, size: int = 10) -> dict:
    return {"name": name, "size": size, "browser_download_url": url}


def release(tag: str, *, prerelease: bool = False, draft: bool = False, assets=None) -> dict:
    version = tag.removeprefix("v")
    base = "https://github.com/Indrajit147/OpenDM/releases/download/" + tag + "/"
    return {
        "tag_name": tag, "name": f"OpenDM {version}", "draft": draft, "prerelease": prerelease,
        "body": f"Notes for {version}", "html_url": f"https://github.com/x/releases/tag/{tag}",
        "assets": assets if assets is not None else [
            asset(f"OpenDM-{version}-setup.exe", base + f"OpenDM-{version}-setup.exe", 26_000_000),
            asset(f"OpenDM-{version}-portable.zip", base + f"OpenDM-{version}-portable.zip"),
            asset("SHA256SUMS.txt", base + "SHA256SUMS.txt"),
        ],
    }  # fmt: skip


RELEASES = [
    release("v0.9.0-rc.1", prerelease=True),
    release("v0.8.1"),
    release("v0.8.0"),
    release("v0.9.0", draft=True),  # drafts are never offered
    release("not-a-version"),
]


# --- choosing a release (no network) -----------------------------------------------------------


def test_newest_final_release_is_offered() -> None:
    update = pick_update(RELEASES, parse_version("0.8.0"), prereleases=False)
    assert update is not None and str(update.version) == "0.8.1"
    assert update.installer is not None and update.installer.name == "OpenDM-0.8.1-setup.exe"
    assert update.installer.size == 26_000_000
    assert update.sums is not None and update.notes == "Notes for 0.8.1"
    assert update.page_url.endswith("/v0.8.1")


def test_prereleases_only_when_asked() -> None:
    update = pick_update(RELEASES, parse_version("0.8.0"), prereleases=True)
    assert update is not None and str(update.version) == "0.9.0-rc.1"


def test_a_prerelease_tag_marked_as_final_is_still_a_prerelease() -> None:
    releases = [release("v0.9.0-rc.2", prerelease=False)]
    assert pick_update(releases, parse_version("0.8.0"), prereleases=False) is None


def test_nothing_newer() -> None:
    assert pick_update(RELEASES, parse_version("0.8.1"), prereleases=False) is None
    assert pick_update(RELEASES, parse_version("0.9.0-rc.1"), prereleases=True) is None
    assert pick_update([], parse_version("0.8.1"), prereleases=True) is None


def test_running_a_prerelease_offers_the_final_version() -> None:
    update = pick_update([release("v0.8.0")], parse_version("0.8.0-rc.2"), prereleases=False)
    assert update is not None and str(update.version) == "0.8.0"


def test_bad_entries_are_skipped() -> None:
    junk = [{"tag_name": 5}, {"draft": False}, "text", release("v0.8.2", assets=[{"name": 1}])]
    update = pick_update([*junk, release("v0.8.1")], parse_version("0.8.0"), prereleases=False)
    assert update is not None and str(update.version) == "0.8.2"
    assert update.installer is None  # the broken asset was ignored


# --- against the test server -------------------------------------------------------------------


@pytest.fixture
def site(server: FaultServer, tmp_path: Path):
    root = tmp_path / "static"
    (root / "dl").mkdir(parents=True)
    (root / "dl" / "OpenDM-0.9.0-setup.exe").write_bytes(INSTALLER)
    digest = hashlib.sha256(INSTALLER).hexdigest()
    (root / "dl" / "SHA256SUMS.txt").write_text(
        f"{'0' * 64}  OpenDM-0.9.0-portable.zip\n{digest}  OpenDM-0.9.0-setup.exe\n"
    )
    entry = release("v0.9.0", assets=[
        asset("OpenDM-0.9.0-setup.exe", server.url("/static/dl/OpenDM-0.9.0-setup.exe"),
              len(INSTALLER)),
        asset("SHA256SUMS.txt", server.url("/static/dl/SHA256SUMS.txt")),
    ])  # fmt: skip
    (root / "releases.json").write_text(json.dumps([entry]))
    server.static_root = root
    source = UpdateSource(
        api_url=server.url("/static/releases.json"),
        feed_url=server.url("/static/releases.atom"),  # absent unless a test writes it
        download_prefix=server.url("/static/dl/"),
        page_url=server.url("/static/"),
    )
    yield root, source
    server.static_root = None


async def test_check_finds_the_newer_release(site) -> None:
    _, source = site
    update = await Updater(source).check("0.8.0", prereleases=False)
    assert update is not None and str(update.version) == "0.9.0"
    assert await Updater(source).check("0.9.0", prereleases=False) is None


async def test_download_verifies_the_installer(site, tmp_path: Path) -> None:
    _, source = site
    updater = Updater(source)
    update = await updater.check("0.8.0", prereleases=False)
    assert update is not None
    seen: list[tuple[int, int | None]] = []
    path = await updater.download(update, tmp_path / "updates", lambda d, t: seen.append((d, t)))
    assert path == tmp_path / "updates" / "OpenDM-0.9.0-setup.exe"
    assert path.read_bytes() == INSTALLER
    assert seen and seen[-1] == (len(INSTALLER), len(INSTALLER))
    assert list(path.parent.iterdir()) == [path]  # no partial file left


async def test_a_wrong_checksum_is_refused_and_deleted(site, tmp_path: Path) -> None:
    root, source = site
    (root / "dl" / "OpenDM-0.9.0-setup.exe").write_bytes(b"tampered")
    updater = Updater(source)
    update = await updater.check("0.8.0", prereleases=False)
    assert update is not None
    with pytest.raises(DownloadError) as exc:
        await updater.download(update, tmp_path / "updates")
    assert exc.value.kind is ErrorKind.CHECKSUM_MISMATCH
    assert not any((tmp_path / "updates").iterdir())


async def test_missing_checksum_entry_is_refused(site, tmp_path: Path) -> None:
    root, source = site
    (root / "dl" / "SHA256SUMS.txt").write_text(f"{'0' * 64}  something-else.exe\n")
    updater = Updater(source)
    update = await updater.check("0.8.0", prereleases=False)
    assert update is not None
    with pytest.raises(DownloadError) as exc:
        await updater.download(update, tmp_path / "updates")
    assert exc.value.kind is ErrorKind.CHECKSUM_MISMATCH


async def test_links_outside_the_project_are_refused(site, tmp_path: Path) -> None:
    _, source = site
    other = UpdateSource(api_url=source.api_url, download_prefix="https://example.invalid/",
                         page_url=source.page_url)  # fmt: skip
    updater = Updater(other)
    update = await updater.check("0.8.0", prereleases=False)
    assert update is not None
    with pytest.raises(DownloadError):
        await updater.download(update, tmp_path / "updates")
    assert not (tmp_path / "updates").exists() or not any((tmp_path / "updates").iterdir())


async def test_api_errors_are_reported(server: FaultServer) -> None:
    source = UpdateSource(
        api_url=server.url("/status/500"), feed_url=server.url("/status/500"),
        download_prefix="x", page_url="x",
    )  # fmt: skip
    with pytest.raises(DownloadError):
        await Updater(source).check("0.8.0", prereleases=False)


# --- GitHub's hourly limit: fall back to the public releases feed ----------------------------

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en-US">
  <title>Release notes from OpenDM</title>
  <entry>
    <id>tag:github.com,2008:Repository/1/v0.9.0-rc.1</id>
    <link rel="alternate" type="text/html" href="https://example.invalid/tag/v0.9.0-rc.1"/>
    <title>OpenDM 0.9.0-rc.1</title>
    <content type="html">&lt;p&gt;Test build&lt;/p&gt;</content>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1/v0.9.0</id>
    <link rel="alternate" type="text/html" href="https://example.invalid/tag/v0.9.0"/>
    <title>OpenDM 0.9.0</title>
    <content type="html">&lt;h3&gt;Added&lt;/h3&gt;&lt;p&gt;Feeds&lt;/p&gt;</content>
  </entry>
  <entry>
    <id>tag:github.com,2008:Repository/1/not-a-version</id>
    <title>Something else</title>
  </entry>
</feed>
"""


@pytest.fixture
def limited(site, server: FaultServer):
    """The API answers 403 (hourly limit reached); the feed and the files are there."""
    root, source = site
    feed = FEED.replace("v0.9.0-rc.1", "v0.9.1-rc.1").replace("0.9.0-rc.1", "0.9.1-rc.1")
    (root / "releases.atom").write_text(feed, encoding="utf-8")
    tag_dir = root / "dl" / "v0.9.0"
    tag_dir.mkdir()
    for name in ("OpenDM-0.9.0-setup.exe", "SHA256SUMS.txt"):
        (tag_dir / name).write_bytes((root / "dl" / name).read_bytes())
    source = UpdateSource(
        api_url=server.url("/status/403"), feed_url=server.url("/static/releases.atom"),
        download_prefix=source.download_prefix, page_url=source.page_url,
    )  # fmt: skip
    return root, source


async def test_limit_falls_back_to_the_feed(limited, tmp_path: Path) -> None:
    _, source = limited
    updater = Updater(source)
    update = await updater.check("0.8.0", prereleases=False)
    assert update is not None and str(update.version) == "0.9.0"
    assert update.installer is not None
    assert update.installer.url == source.download_prefix + "v0.9.0/OpenDM-0.9.0-setup.exe"
    assert update.sums is not None and update.sums.url.endswith("v0.9.0/SHA256SUMS.txt")
    assert update.notes_format == "html" and "Feeds" in update.notes
    assert update.page_url == "https://example.invalid/tag/v0.9.0"
    path = await updater.download(update, tmp_path / "updates")  # still checked against SHA-256
    assert path.read_bytes() == INSTALLER


async def test_feed_respects_the_prerelease_choice(limited) -> None:
    _, source = limited
    update = await Updater(source).check("0.8.0", prereleases=True)
    assert update is not None and str(update.version) == "0.9.1-rc.1"
    assert await Updater(source).check("0.9.0", prereleases=False) is None


async def test_limit_and_no_feed_explains_the_limit(server: FaultServer) -> None:
    source = UpdateSource(
        api_url=server.url("/status/403"), feed_url=server.url("/status/500"),
        download_prefix="x", page_url="x",
    )  # fmt: skip
    with pytest.raises(DownloadError) as exc:
        await Updater(source).check("0.8.0", prereleases=False)
    assert "limit" in exc.value.message and "try again" in exc.value.message


async def test_unreadable_api_answer(site) -> None:
    root, source = site
    (root / "releases.json").write_text("{not json")
    with pytest.raises(DownloadError) as exc:
        await Updater(source).check("0.8.0", prereleases=False)
    assert exc.value.kind is ErrorKind.HTTP_CLIENT


def test_old_installers_are_cleaned(tmp_path: Path) -> None:
    for name in ("OpenDM-0.8.0-setup.exe", "OpenDM-0.9.0-setup.exe.part", "notes.txt"):
        (tmp_path / name).write_text("x")
    clean_old_installers(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["notes.txt"]
    clean_old_installers(tmp_path / "missing")  # no folder: nothing to do
