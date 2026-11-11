import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from modflow_devtools.release import changelog, version

FIXTURE = Path(__file__).resolve().parent / "release"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "hello"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("builddir*", "bin", ".pixi"))
    return root


def test_get(repo):
    assert version.get_version(repo) == "0.1.0.dev0"


def test_set_updates_every_target(repo):
    date = datetime(2026, 11, 10, tzinfo=UTC)
    version.set_version(repo, "1.2.3", date=date)
    assert version.get_version(repo) == "1.2.3"
    assert "version: '1.2.3'" in (repo / "meson.build").read_text()
    assert 'version = "1.2.3"' in (repo / "pixi.toml").read_text()
    assert "VERSION = '1.2.3 11/10/2026'" in (repo / "src" / "hello.f90").read_text()


def test_set_keeps_line_endings(repo):
    path = repo / "src" / "hello.f90"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    version.set_version(repo, "1.2.3")
    assert b"\r\n" in path.read_bytes()
    assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")


@pytest.mark.parametrize("value", ["1.2", "v1.2.3", "1.2.3rc1", "1.2.3.dev"])
def test_set_rejects_bad_versions(repo, value):
    with pytest.raises(SystemExit):
        version.set_version(repo, value)


def test_next():
    assert version.next_version("1.5.0") == "1.6.0.dev0"
    assert version.next_version("1.5.2") == "1.6.0.dev2"
    assert version.next_version("1.6.0.dev0") == "1.7.0.dev0"


def test_is_release(repo):
    assert version.main(["--root", str(repo), "--is-release"]) == 1
    version.set_version(repo, "1.0.0")
    assert version.main(["--root", str(repo), "--is-release"]) == 0


def test_version_txt(repo):
    meson = repo / "meson.build"
    meson.write_text(
        meson.read_text().replace("version: '0.1.0.dev0'", "version: files('version.txt')")
    )
    (repo / "version.txt").write_text("1.0.03\n")
    assert version.get_version(repo) == "1.0.03"
    version.set_version(repo, "1.0.4")
    assert (repo / "version.txt").read_text() == "1.0.4\n"


def test_without_pixi_or_config(repo):
    (repo / "pixi.toml").unlink()
    (repo / "release.toml").unlink()
    version.set_version(repo, "2.0.0")
    assert version.get_version(repo) == "2.0.0"


def test_missing_target_fails(repo):
    path = repo / "src" / "hello.f90"
    path.write_text(path.read_text().replace("VERSION =", "V ="))
    with pytest.raises(SystemExit):
        version.set_version(repo, "1.2.3")


CHANGELOG = """\
# Changelog

## Version 1.2.0 (2026-11-10)

### Features

* Something new

## Version 1.1.0 (2026-01-01)

### Fixes

* Something old
"""


def test_notes(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    assert changelog.notes(tmp_path, "1.2.0") == "### Features\n\n* Something new\n"
    assert changelog.notes(tmp_path, "1.1.0") == "### Fixes\n\n* Something old\n"
    with pytest.raises(SystemExit):
        changelog.notes(tmp_path, "1.0.0")


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


@pytest.mark.skipif(shutil.which("git-cliff") is None, reason="needs git-cliff")
def test_update(repo):
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feat: first")
    git(repo, "tag", "v0.1.0")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix(io): read the thing")
    git(repo, "commit", "-q", "--allow-empty", "-m", "ci: skipped")
    git(repo, "commit", "-q", "--allow-empty", "-m", "fix(ci): also skipped")
    changelog.update(repo, "0.2.0", "MODFLOW-ORG/hello", "Hello")
    text = (repo / "CHANGELOG.md").read_text()
    assert "Features, fixes, and performance changes in each Hello release." in text
    assert "## Version 0.2.0" in text
    assert "io: Read the thing" in text
    assert "https://github.com/MODFLOW-ORG/hello/commit/" in text
    assert "first" not in text and "skipped" not in text
    assert changelog.notes(repo, "0.2.0").startswith("### Fixes")

    # a second release prepends, keeping the first
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore(release): 0.2.0")
    git(repo, "tag", "v0.2.0")
    git(repo, "commit", "-q", "--allow-empty", "-m", "perf: faster")
    changelog.update(repo, "0.3.0", "MODFLOW-ORG/hello", "Hello")
    text = (repo / "CHANGELOG.md").read_text()
    assert text.count("# Changelog") == 1
    assert text.index("## Version 0.3.0") < text.index("## Version 0.2.0")
    assert "Faster" in changelog.notes(repo, "0.3.0")
