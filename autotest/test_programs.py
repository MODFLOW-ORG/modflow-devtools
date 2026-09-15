"""
Tests for the programs API.

Unlike the models/DFNs APIs, there is no registry to sync - installation is
driven directly by GitHub releases from one of the three real MODFLOW-ORG
distributions (`executables`, `modflow6`, `modflow6-nightly-build`), and a
local per-program ledger tracks what's installed where.
"""

import json
import warnings
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from flaky import flaky

from modflow_devtools.markers import requires_github
from modflow_devtools.programs import (
    AVAILABLE_REPOS,
    InstallationMetadata,
    ProgramCache,
    ProgramInstallation,
    ProgramInstallationError,
    _compute_file_hash,
    _select_asset,
    _verify_hash,
    extract_release_archive,
    get_bindir_options,
    get_bindir_shortcut_map,
    get_executable,
    get_platform,
    install_program,
    list_installed,
    register_installation,
    uninstall_program,
)

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
        assert installations[0].executables == ["mf6"]
        assert (bindir / "mf6").exists()
        assert get_executable("mf6") == bindir / "mf6"

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_from_nightly_repo(self, isolated_cache, tmp_path):
        bindir = tmp_path / "bin"
        installations = install_program("mf6", repo="modflow6-nightly-build", bindir=bindir)
        assert len(installations) == 1
        assert (bindir / "mf6").exists()

    @requires_github
    @flaky(max_runs=3, min_passes=1)
    def test_install_from_executables_repo_subset(self, isolated_cache, tmp_path):
        bindir = tmp_path / "bin"
        installations = install_program(subset="mfnwt", repo="executables", bindir=bindir)
        assert len(installations) == 1
        assert installations[0].executables == ["mfnwt"]
        assert (bindir / "mfnwt").exists()

    @requires_github
    def test_install_unknown_repo_rejected(self, isolated_cache, tmp_path):
        with pytest.raises(ProgramInstallationError):
            install_program("mf6", repo="not-a-real-repo", bindir=tmp_path)

    @requires_github
    def test_install_unknown_release_lists_available(self, isolated_cache, tmp_path):
        with pytest.raises(ProgramInstallationError, match="choose from"):
            install_program("mf6", repo="modflow6", version="not-a-real-tag", bindir=tmp_path)


def test_available_repos_matches_get_modflow_parity():
    assert set(AVAILABLE_REPOS) == {"executables", "modflow6", "modflow6-nightly-build"}
