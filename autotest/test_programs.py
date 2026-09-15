"""
Tests for the programs API.

Unlike the models/DFNs APIs, there is no registry to sync - installation is
driven directly by GitHub releases from one of the three real MODFLOW-ORG
distributions (`executables`, `modflow6`, `modflow6-nightly-build`), and a
local per-program ledger tracks what's installed where.
"""

import argparse
import json
import subprocess
import sys
import warnings
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from flaky import flaky

from modflow_devtools.markers import requires_github
from modflow_devtools.programs import (
    KNOWN_REPOS,
    InstallationMetadata,
    ProgramCache,
    ProgramInstallation,
    ProgramInstallationError,
    _compute_file_hash,
    _select_asset,
    _verify_hash,
    download_archive,
    extract_release_archive,
    get_bindir_options,
    get_bindir_shortcut_map,
    get_executable,
    get_platform,
    install_program,
    list_installed,
    register_installation,
    select_bindir,
    uninstall_program,
)
from modflow_devtools.programs.__main__ import cmd_install, cmd_list, cmd_uninstall, main

warnings.filterwarnings("ignore", message=".*modflow_devtools.programs.*experimental.*")


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Route the program cache (archives + installation ledger) to a temp dir
    so tests never touch the developer's real ~/.cache/modflow-devtools."""
    cache = ProgramCache(root=tmp_path / "programs-cache")
    monkeypatch.setattr("modflow_devtools.programs._DEFAULT_CACHE", cache)
    return cache


def _make_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


def _exe(name: str) -> str:
    """Expected filename for a real (live, auto-detected-platform) install -
    Windows executables get a real .exe extension, appended by extract_release_archive
    via get_platform()/get_binary_suffixes(). Fixture-driven extract_release_archive
    tests pass an explicit ostag="linux" and don't need this."""
    return f"{name}.exe" if sys.platform == "win32" else name


class TestPlatform:
    def test_get_platform_returns_supported_ostag(self):
        assert get_platform() in ("linux", "mac", "macarm", "win64")


class TestHashing:
    def test_compute_and_verify(self, tmp_path):
        f = tmp_path / "file.bin"
        f.write_bytes(b"hello world")
        digest = _compute_file_hash(f)
        assert _verify_hash(f, f"sha256:{digest}")
        assert not _verify_hash(f, f"sha256:{'0' * 64}")

    def test_verify_hash_bad_format(self, tmp_path):
        f = tmp_path / "file.bin"
        f.write_bytes(b"data")
        with pytest.raises(ValueError):
            _verify_hash(f, "not-a-valid-hash")


class TestSelectAsset:
    def test_matches_whole_token_only(self):
        release = {
            "tag_name": "6.8.0",
            "assets": [
                {"name": "mf6.8.0_win64ext.zip"},
                {"name": "mf6.8.0_win64.zip"},
                {"name": "mf6.8.0_linux.zip"},
            ],
        }
        asset = _select_asset(release, "win64")
        assert asset["name"] == "mf6.8.0_win64.zip"

    def test_mac_does_not_match_macarm(self):
        release = {"tag_name": "v1", "assets": [{"name": "macarm.zip"}]}
        with pytest.raises(ProgramInstallationError):
            _select_asset(release, "mac")

    def test_macarm_matches_macarm(self):
        release = {"tag_name": "v1", "assets": [{"name": "macarm.zip"}]}
        assert _select_asset(release, "macarm")["name"] == "macarm.zip"

    def test_no_match_raises_with_available_assets_listed(self):
        release = {"tag_name": "v1", "assets": [{"name": "linux.zip"}]}
        with pytest.raises(ProgramInstallationError, match=r"linux\.zip"):
            _select_asset(release, "win64")


class TestExtractReleaseArchive:
    def test_code_json_bundle_versions_each_program_independently(self, tmp_path):
        archive = _make_zip(
            tmp_path / "linux.zip",
            {
                "code.json": json.dumps(
                    {
                        "mf6": {"version": "6.8.0", "shared_object": False},
                        "mfnwt": {"version": "1.3.0", "shared_object": False},
                        "libmf6": {"version": "6.8.0", "shared_object": True},
                    }
                ).encode(),
                "mf6": b"fake-mf6-binary",
                "mfnwt": b"fake-mfnwt-binary",
                "libmf6.so": b"fake-shared-object",
            },
        )
        dest = tmp_path / "out"
        extracted = extract_release_archive(archive, dest, release_tag="29.0", ostag="linux")

        by_name = {p.name: p for p in extracted}
        assert by_name["mf6"].version == "6.8.0"
        assert by_name["mfnwt"].version == "1.3.0"
        assert by_name["libmf6"].version == "6.8.0"
        assert by_name["libmf6"].is_shared_object
        assert not by_name["mf6"].is_shared_object
        assert (dest / "mf6").exists()
        assert (dest / "libmf6.so").exists()

    def test_code_json_bundle_respects_subset(self, tmp_path):
        archive = _make_zip(
            tmp_path / "linux.zip",
            {
                "code.json": json.dumps(
                    {
                        "mf6": {"version": "6.8.0", "shared_object": False},
                        "mfnwt": {"version": "1.3.0", "shared_object": False},
                    }
                ).encode(),
                "mf6": b"fake-mf6-binary",
                "mfnwt": b"fake-mfnwt-binary",
            },
        )
        dest = tmp_path / "out"
        extracted = extract_release_archive(
            archive, dest, release_tag="29.0", ostag="linux", subset={"mfnwt"}
        )
        assert [p.name for p in extracted] == ["mfnwt"]
        assert not (dest / "mf6").exists()

    def test_plain_archive_versions_by_release_tag(self, tmp_path):
        archive = _make_zip(
            tmp_path / "linux.zip",
            {
                "mf6.8.0_linux/bin/mf6": b"fake-mf6-binary",
                "mf6.8.0_linux/bin/zbud6": b"fake-zbud6-binary",
                "mf6.8.0_linux/bin/libmf6.so": b"fake-shared-object",
            },
        )
        dest = tmp_path / "out"
        extracted = extract_release_archive(archive, dest, release_tag="6.8.0", ostag="linux")

        assert {p.name for p in extracted} == {"mf6", "zbud6", "libmf6"}
        assert all(p.version == "6.8.0" for p in extracted)
        # nested archive dir should not survive extraction
        assert not (dest / "mf6.8.0_linux").exists()
        assert (dest / "mf6").exists()

    def test_flat_archive_no_bin_dir(self, tmp_path):
        archive = _make_zip(tmp_path / "linux.zip", {"mf6": b"fake-mf6-binary"})
        dest = tmp_path / "out"
        extracted = extract_release_archive(archive, dest, release_tag="1.0", ostag="linux")
        assert [p.name for p in extracted] == ["mf6"]
        assert (dest / "mf6").exists()

    def test_no_match_raises(self, tmp_path):
        archive = _make_zip(tmp_path / "linux.zip", {"mf6": b"fake-mf6-binary"})
        with pytest.raises(ProgramInstallationError):
            extract_release_archive(
                archive, tmp_path / "out", release_tag="1.0", ostag="linux", subset={"nope"}
            )


class TestInstallationMetadata:
    def test_add_list_remove_roundtrip(self, isolated_cache):
        metadata = InstallationMetadata("mf6")
        assert not metadata.load()

        inst = ProgramInstallation(
            version="6.8.0",
            platform="linux",
            bindir=Path("/usr/local/bin"),
            installed_at=datetime.now(UTC),
            source={"repo": "MODFLOW-ORG/modflow6", "tag": "6.8.0"},
            executables=["mf6"],
        )
        metadata.add_installation(inst)

        reloaded = InstallationMetadata("mf6")
        assert reloaded.load()
        assert len(reloaded.list_installations()) == 1
        assert reloaded.list_installations()[0].version == "6.8.0"

        reloaded.remove_installation("6.8.0", Path("/usr/local/bin"))
        assert reloaded.list_installations() == []

    def test_add_installation_replaces_same_version_and_bindir(self, isolated_cache):
        metadata = InstallationMetadata("mf6")
        bindir = Path("/usr/local/bin")
        for tag in ("v1", "v2"):
            metadata.add_installation(
                ProgramInstallation(
                    version="6.8.0",
                    platform="linux",
                    bindir=bindir,
                    installed_at=datetime.now(UTC),
                    source={"tag": tag},
                    executables=["mf6"],
                )
            )
        assert len(metadata.list_installations()) == 1
        assert metadata.list_installations()[0].source["tag"] == "v2"

    def test_corrupt_metadata_file_loads_empty(self, isolated_cache):
        isolated_cache.metadata_dir.mkdir(parents=True, exist_ok=True)
        (isolated_cache.metadata_dir / "mf6.json").write_text("not json")
        metadata = InstallationMetadata("mf6")
        assert metadata.load() is False
        assert metadata.list_installations() == []


class TestRegisterAndQuery:
    def test_register_installation_is_source_agnostic(self, isolated_cache, tmp_path):
        exe = tmp_path / "mf6"
        exe.write_bytes(b"fake")
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"], source="conda-forge")

        found = get_executable("mf6")
        assert found == exe

        installed = list_installed()
        assert installed["mf6"][0].source == {"origin": "conda-forge"}

    def test_get_executable_returns_none_when_unknown(self, isolated_cache):
        assert get_executable("does-not-exist") is None

    def test_get_executable_skips_missing_files(self, isolated_cache, tmp_path):
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"])
        # file was never actually created on disk
        assert get_executable("mf6") is None

    def test_get_executable_filters_by_version(self, isolated_cache, tmp_path):
        for version in ("6.7.0", "6.8.0"):
            exe_dir = tmp_path / version
            exe_dir.mkdir()
            (exe_dir / "mf6").write_bytes(b"fake")
            register_installation("mf6", version, exe_dir, ["mf6"])

        assert get_executable("mf6", version="6.7.0") == tmp_path / "6.7.0" / "mf6"
        assert get_executable("mf6", version="6.8.0") == tmp_path / "6.8.0" / "mf6"

    def test_uninstall_removes_file_and_forgets(self, isolated_cache, tmp_path):
        exe = tmp_path / "mf6"
        exe.write_bytes(b"fake")
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"])

        uninstall_program("mf6", version="6.8.0", bindir=tmp_path)

        assert not exe.exists()
        assert list_installed("mf6") == {}

    def test_uninstall_keep_files(self, isolated_cache, tmp_path):
        exe = tmp_path / "mf6"
        exe.write_bytes(b"fake")
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"])

        uninstall_program("mf6", version="6.8.0", bindir=tmp_path, delete_files=False)

        assert exe.exists()
        assert list_installed("mf6") == {}

    def test_uninstall_requires_version_or_all(self, isolated_cache, tmp_path):
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"])
        with pytest.raises(ValueError):
            uninstall_program("mf6")

    def test_uninstall_all_versions(self, isolated_cache, tmp_path):
        for version in ("6.7.0", "6.8.0"):
            register_installation("mf6", version, tmp_path, [f"mf6-{version}"])
        uninstall_program("mf6", all_versions=True, delete_files=False)
        assert list_installed("mf6") == {}

    def test_list_installed_filters_by_program(self, isolated_cache, tmp_path):
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"])
        register_installation("mp7", "7.2.001", tmp_path, ["mp7"])
        assert set(list_installed().keys()) == {"mf6", "mp7"}
        assert set(list_installed("mf6").keys()) == {"mf6"}


class TestBindirSelection:
    def test_get_bindir_options_nonempty(self):
        assert len(get_bindir_options()) > 0

    def test_get_bindir_shortcut_map_has_python(self):
        options = get_bindir_shortcut_map()
        assert ":python" in options or ":mf" in options


class TestInstallProgramLive:
    """Live installs against real MODFLOW-ORG releases - one per distribution
    format, kept small via `subset`/`program` to avoid slow downloads."""

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_from_modflow6_repo(self, isolated_cache, tmp_path):
        bindir = tmp_path / "bin"
        installations = install_program("mf6", repo="modflow6", bindir=bindir)
        assert len(installations) == 1
        assert installations[0].executables == [_exe("mf6")]
        assert (bindir / _exe("mf6")).exists()
        assert get_executable("mf6") == bindir / _exe("mf6")

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_from_nightly_repo(self, isolated_cache, tmp_path):
        bindir = tmp_path / "bin"
        installations = install_program("mf6", repo="modflow6-nightly-build", bindir=bindir)
        assert len(installations) == 1
        assert (bindir / _exe("mf6")).exists()

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_from_executables_repo_subset(self, isolated_cache, tmp_path):
        bindir = tmp_path / "bin"
        installations = install_program(subset="mfnwt", repo="executables", bindir=bindir)
        assert len(installations) == 1
        assert installations[0].executables == [_exe("mfnwt")]
        assert (bindir / _exe("mfnwt")).exists()

    @requires_github
    def test_install_unknown_repo_rejected(self, isolated_cache, tmp_path):
        with pytest.raises(ProgramInstallationError, match="not found"):
            install_program("mf6", repo="not-a-real-repo-xyz", bindir=tmp_path)

    @requires_github
    def test_install_unknown_release_lists_available(self, isolated_cache, tmp_path):
        with pytest.raises(ProgramInstallationError, match="choose from"):
            install_program("mf6", repo="modflow6", version="not-a-real-tag", bindir=tmp_path)

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_from_arbitrary_program_repo_not_in_known_repos(self, isolated_cache, tmp_path):
        """`repo` isn't restricted to KNOWN_REPOS - individual program repos that
        publish their own releases in the same shape work directly."""
        assert "gridgen" not in KNOWN_REPOS
        bindir = tmp_path / "bin"
        installations = install_program(repo="gridgen", bindir=bindir)
        assert len(installations) == 1
        assert installations[0].executables == [_exe("gridgen")]
        assert (bindir / _exe("gridgen")).exists()


def test_known_repos_matches_get_modflow_parity():
    assert set(KNOWN_REPOS) == {"executables", "modflow6", "modflow6-nightly-build"}


class TestDownloadArchive:
    def test_uses_cached_file_without_hash(self, tmp_path):
        dest = tmp_path / "archive.zip"
        dest.write_bytes(b"cached-content")
        result = download_archive("https://example.invalid/archive.zip", dest)
        assert result == dest
        assert dest.read_bytes() == b"cached-content"

    def test_uses_cached_file_with_matching_hash(self, tmp_path):
        dest = tmp_path / "archive.zip"
        dest.write_bytes(b"cached-content")
        digest = _compute_file_hash(dest)
        result = download_archive(
            "https://example.invalid/archive.zip", dest, expected_hash=f"sha256:{digest}"
        )
        assert result == dest

    def test_redownloads_on_hash_mismatch(self, tmp_path, monkeypatch):
        import hashlib

        dest = tmp_path / "archive.zip"
        dest.write_bytes(b"stale-content")

        class _FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=8192):
                yield b"fresh-content"

        monkeypatch.setattr(
            "modflow_devtools.programs.requests.get",
            lambda *a, **k: _FakeResponse(),
        )

        fresh_digest = hashlib.sha256(b"fresh-content").hexdigest()
        result = download_archive(
            "https://example.invalid/archive.zip", dest, expected_hash=f"sha256:{fresh_digest}"
        )
        assert result.read_bytes() == b"fresh-content"

    def test_force_redownloads_even_when_cached(self, tmp_path, monkeypatch):
        dest = tmp_path / "archive.zip"
        dest.write_bytes(b"stale-content")
        calls = []

        class _FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=8192):
                calls.append(1)
                yield b"fresh-content"

        monkeypatch.setattr(
            "modflow_devtools.programs.requests.get",
            lambda *a, **k: _FakeResponse(),
        )
        download_archive("https://example.invalid/archive.zip", dest, force=True)
        assert calls == [1]
        assert dest.read_bytes() == b"fresh-content"


class TestRetryLogic:
    def test_request_json_retries_then_succeeds(self, monkeypatch):
        import requests

        from modflow_devtools.programs import _request_json

        monkeypatch.setattr("modflow_devtools.programs.time.sleep", lambda *_: None)

        class _FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"ok": True}

        calls = {"n": 0}

        def _fake_get(*a, **k):
            calls["n"] += 1
            if calls["n"] < 3:
                raise requests.exceptions.ConnectionError("transient")
            return _FakeResponse()

        monkeypatch.setattr("modflow_devtools.programs.requests.get", _fake_get)
        result = _request_json("https://example.invalid/x", tries=3, delay=0)
        assert result == {"ok": True}
        assert calls["n"] == 3

    def test_request_json_exhausts_retries(self, monkeypatch):
        import requests

        from modflow_devtools.programs import _request_json

        monkeypatch.setattr("modflow_devtools.programs.time.sleep", lambda *_: None)

        def _fake_get(*a, **k):
            raise requests.exceptions.ConnectionError("down")

        monkeypatch.setattr("modflow_devtools.programs.requests.get", _fake_get)
        with pytest.raises(ProgramInstallationError):
            _request_json("https://example.invalid/x", tries=2, delay=0)


class TestSelectBindir:
    def test_auto_select_by_prefix(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "modflow_devtools.programs.get_bindir_shortcut_map",
            lambda program=None: {":python": (tmp_path, "used by Python")},
        )
        assert select_bindir(":py") == tmp_path.resolve()

    def test_ambiguous_shortcut_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "modflow_devtools.programs.get_bindir_shortcut_map",
            lambda program=None: {
                ":prev": (tmp_path, "a"),
                ":python": (tmp_path, "b"),
            },
        )
        with pytest.raises(ProgramInstallationError, match="Ambiguous"):
            select_bindir(":p")

    def test_unknown_shortcut_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "modflow_devtools.programs.get_bindir_shortcut_map",
            lambda program=None: {":python": (tmp_path, "used by Python")},
        )
        with pytest.raises(ProgramInstallationError, match="Invalid bindir shortcut"):
            select_bindir(":nope")


class TestCLI:
    def test_main_no_command_prints_help_and_exits(self, capsys):
        sys_argv = sys.argv
        sys.argv = ["mf-programs"]
        try:
            with pytest.raises(SystemExit) as exc_info:
                main()
        finally:
            sys.argv = sys_argv
        assert exc_info.value.code == 1
        assert "usage" in capsys.readouterr().out.lower()

    def test_cmd_uninstall_requires_version_or_all(self, capsys):
        args = argparse.Namespace(program="mf6", bindir=None, all_versions=False, keep_files=False)
        with pytest.raises(SystemExit) as exc_info:
            cmd_uninstall(args)
        assert exc_info.value.code == 1
        assert "must specify version" in capsys.readouterr().err.lower()

    def test_cmd_list_no_installations(self, isolated_cache, capsys):
        args = argparse.Namespace(program=None, verbose=False)
        cmd_list(args)
        assert "no programs installed" in capsys.readouterr().out.lower()

    def test_cmd_list_shows_registered_installation(self, isolated_cache, tmp_path, capsys):
        exe = tmp_path / "mf6"
        exe.write_bytes(b"fake")
        register_installation("mf6", "6.8.0", tmp_path, ["mf6"], source="manual")

        args = argparse.Namespace(program=None, verbose=True)
        cmd_list(args)
        out = capsys.readouterr().out
        assert "mf6" in out
        assert "6.8.0" in out
        assert str(tmp_path) in out

    def test_help_smoke_test_via_subprocess(self):
        for argv in (
            [sys.executable, "-m", "modflow_devtools.programs", "--help"],
            [sys.executable, "-m", "modflow_devtools.programs", "install", "--help"],
            [sys.executable, "-m", "modflow_devtools.programs", "uninstall", "--help"],
            [sys.executable, "-m", "modflow_devtools.programs", "list", "--help"],
        ):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_cmd_install_at_version_syntax_and_list_and_uninstall(
        self, isolated_cache, tmp_path, capsys
    ):
        bindir = tmp_path / "bin"
        install_args = argparse.Namespace(
            program="mf6@6.8.0",
            repo="modflow6",
            owner="MODFLOW-ORG",
            version=None,
            bindir=str(bindir),
            platform=None,
            subset=None,
            force=False,
        )
        cmd_install(install_args)
        installed_out = capsys.readouterr().out
        assert f"{_exe('mf6')} 6.8.0" in installed_out
        assert (bindir / _exe("mf6")).exists()

        list_args = argparse.Namespace(program="mf6", verbose=False)
        cmd_list(list_args)
        assert "6.8.0" in capsys.readouterr().out

        uninstall_args = argparse.Namespace(
            program="mf6@6.8.0", bindir=str(bindir), all_versions=False, keep_files=False
        )
        cmd_uninstall(uninstall_args)
        capsys.readouterr()
        assert not (bindir / _exe("mf6")).exists()
        assert list_installed("mf6") == {}


class TestMoreCoverage:
    def test_download_archive_exhausts_retries(self, tmp_path, monkeypatch):
        import requests

        monkeypatch.setattr("modflow_devtools.programs.time.sleep", lambda *_: None)

        def _fake_get(*a, **k):
            raise requests.exceptions.ConnectionError("down")

        monkeypatch.setattr("modflow_devtools.programs.requests.get", _fake_get)
        with pytest.raises(ProgramInstallationError):
            download_archive("https://example.invalid/x.zip", tmp_path / "x.zip", tries=2, delay=0)

    def test_download_archive_hash_mismatch_after_download_raises(self, tmp_path, monkeypatch):
        class _FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=8192):
                yield b"content"

        monkeypatch.setattr(
            "modflow_devtools.programs.requests.get", lambda *a, **k: _FakeResponse()
        )
        with pytest.raises(ProgramInstallationError, match="does not match expected"):
            download_archive(
                "https://example.invalid/x.zip",
                tmp_path / "x.zip",
                expected_hash=f"sha256:{'0' * 64}",
            )

    def test_get_executable_filters_by_bindir(self, isolated_cache, tmp_path):
        dir_a, dir_b = tmp_path / "a", tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "mf6").write_bytes(b"fake")
        (dir_b / "mf6").write_bytes(b"fake")
        register_installation("mf6", "6.8.0", dir_a, ["mf6"])
        register_installation("mf6", "6.8.0", dir_b, ["mf6"])

        assert get_executable("mf6", bindir=dir_a) == dir_a / "mf6"
        assert get_executable("mf6", bindir=dir_b) == dir_b / "mf6"

    def test_uninstall_prints_when_no_metadata(self, isolated_cache, capsys):
        uninstall_program("does-not-exist", all_versions=True, verbose=True)
        assert "no installation metadata found" in capsys.readouterr().out.lower()

    def test_bindir_prev_shortcut_from_prior_installation(self, isolated_cache, tmp_path):
        exe_dir = tmp_path / "prev-bin"
        exe_dir.mkdir()
        register_installation("mf6", "6.8.0", exe_dir, ["mf6"])

        options = get_bindir_options("mf6")
        assert exe_dir in options

        shortcuts = get_bindir_shortcut_map("mf6")
        assert shortcuts[":prev"][0] == exe_dir

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_program_auto_selects_bindir(self, isolated_cache, tmp_path, monkeypatch):
        auto_dir = tmp_path / "auto-bin"
        auto_dir.mkdir()
        monkeypatch.setattr(
            "modflow_devtools.programs.get_bindir_options", lambda program=None: [auto_dir]
        )
        installations = install_program("mf6", repo="modflow6")
        assert installations[0].bindir == auto_dir
        assert (auto_dir / _exe("mf6")).exists()


class TestGetReleaseErrorWrapping:
    """No-network coverage for the 404 handling get_release/get_releases need now
    that arbitrary repos are allowed (a nonexistent repo 404s at both the
    /releases/tags/{tag} and /releases list endpoints - get_release must not let
    the inner get_releases() call's HTTPError leak out unwrapped)."""

    def test_repo_not_found_raises_program_installation_error(self, monkeypatch):
        from modflow_devtools.programs import get_release

        class _FakeResponse:
            status_code = 404

            def raise_for_status(self):
                import requests

                raise requests.exceptions.HTTPError(response=self)

        monkeypatch.setattr(
            "modflow_devtools.programs.requests.get", lambda *a, **k: _FakeResponse()
        )
        with pytest.raises(ProgramInstallationError, match="not found"):
            get_release(repo="not-a-real-repo-xyz")

    def test_tag_not_found_lists_available_releases(self, monkeypatch):
        from modflow_devtools.programs import get_release

        class _FakeResponse:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload or []

            def raise_for_status(self):
                import requests

                if self.status_code >= 400:
                    raise requests.exceptions.HTTPError(response=self)

            def json(self):
                return self._payload

        def _fake_get(url, **kwargs):
            if url.endswith("/releases/tags/not-a-real-tag"):
                return _FakeResponse(404)
            return _FakeResponse(200, [{"tag_name": "1.0.0"}, {"tag_name": "0.9.0"}])

        monkeypatch.setattr("modflow_devtools.programs.requests.get", _fake_get)
        with pytest.raises(ProgramInstallationError, match=r"1\.0\.0"):
            get_release(repo="mfnwt", tag="not-a-real-tag")
