"""
Tests for the models API (dynamic registry).

Tests can be configured via environment variables (loaded from .env file).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from modflow_devtools.models import (
    _DEFAULT_CACHE,
    DiscoveredModelRegistry,
    ModelRegistry,
    ModelRegistryDiscoveryError,
    ModelSourceConfig,
    ModelSourceRepo,
    get_user_config_path,
)

TEST_MODELS_REPO = os.getenv("TEST_MODELS_REPO", "wpbonelli/modflow6-testmodels")
TEST_MODELS_REF = os.getenv("TEST_MODELS_REF", "registry")
TEST_MODELS_SOURCE = os.getenv("TEST_MODELS_SOURCE", "modflow6-testmodels")
TEST_MODELS_SOURCE_NAME = os.getenv("TEST_MODELS_SOURCE_NAME", "mf6/test")


class TestBootstrap:
    """Test bootstrap file loading and parsing."""

    def test_load_bootstrap(self):
        """Test loading the bootstrap file."""
        bootstrap = ModelSourceConfig.load()
        assert isinstance(bootstrap, ModelSourceConfig)
        assert len(bootstrap.sources) > 0

    def test_bootstrap_has_testmodels(self):
        """Test that testmodels is configured."""
        bootstrap = ModelSourceConfig.load()
        assert TEST_MODELS_SOURCE in bootstrap.sources

    def test_bootstrap_testmodels_config(self):
        """Test testmodels configuration in bundled config (without user overlay)."""
        bundled_path = Path(__file__).parent.parent / "modflow_devtools" / "models" / "models.toml"
        bootstrap = ModelSourceConfig.load(bootstrap_path=bundled_path)
        testmodels = bootstrap.sources[TEST_MODELS_SOURCE]

        assert "MODFLOW-ORG/modflow6-testmodels" in testmodels.repo
        assert "develop" in testmodels.refs or "master" in testmodels.refs

    def test_bootstrap_source_has_name(self):
        """Test that bootstrap sources have name injected."""
        bootstrap = ModelSourceConfig.load()
        for key, source in bootstrap.sources.items():
            assert source.name is not None
            # If no explicit name override, name should equal key
            if not source.name:
                assert source.name == key

    def test_get_user_config_path(self):
        """Test that user config path is platform-appropriate."""
        user_config_path = get_user_config_path()
        assert isinstance(user_config_path, Path)
        assert user_config_path.name == "models.toml"
        assert "modflow-devtools" in str(user_config_path)
        # Should be in .config or AppData depending on platform
        assert ".config" in str(user_config_path) or "AppData" in str(user_config_path)

    def test_merge_bootstrap(self):
        """Test merging bundled and user bootstrap configs."""
        # Create bundled config
        bundled = ModelSourceConfig(
            sources={
                "source1": ModelSourceRepo(repo="org/repo1", name="source1", refs=["main"]),
                "source2": ModelSourceRepo(repo="org/repo2", name="source2", refs=["develop"]),
            }
        )

        # Create user config that overrides source1 and adds source3
        user = ModelSourceConfig(
            sources={
                "source1": ModelSourceRepo(
                    repo="user/custom-repo1", name="source1", refs=["feature"]
                ),
                "source3": ModelSourceRepo(repo="user/repo3", name="source3", refs=["master"]),
            }
        )

        # Merge
        merged = ModelSourceConfig.merge(bundled, user)

        # Check that user source1 overrode bundled source1
        assert merged.sources["source1"].repo == "user/custom-repo1"
        assert merged.sources["source1"].refs == ["feature"]

        # Check that bundled source2 is preserved
        assert merged.sources["source2"].repo == "org/repo2"
        assert merged.sources["source2"].refs == ["develop"]

        # Check that user source3 was added
        assert merged.sources["source3"].repo == "user/repo3"
        assert merged.sources["source3"].refs == ["master"]

    def test_load_bootstrap_with_user_config(self, tmp_path):
        """Test loading bootstrap with user config overlay."""
        # Create a user config file
        user_config = tmp_path / "bootstrap.toml"
        user_config.write_text(
            """
[sources.custom-models]
repo = "user/custom-models"
refs = ["main"]

[sources.modflow6-testmodels]
repo = "user/modflow6-testmodels-fork"
refs = ["custom-branch"]
"""
        )

        # Load bootstrap with user config path specified
        bootstrap = ModelSourceConfig.load(user_config_path=user_config)

        # Check that user config was merged
        assert "custom-models" in bootstrap.sources
        assert bootstrap.sources["custom-models"].repo == "user/custom-models"

        # Check that user config overrode bundled config for testmodels
        if TEST_MODELS_SOURCE in bootstrap.sources:
            assert bootstrap.sources[TEST_MODELS_SOURCE].repo == "user/modflow6-testmodels-fork"

    def test_load_bootstrap_explicit_path_no_overlay(self, tmp_path):
        """Test that explicit bootstrap path doesn't default to user config overlay."""
        # Create an explicit bootstrap file
        explicit_config = tmp_path / "explicit-bootstrap.toml"
        explicit_config.write_text(
            """
[sources.explicit-source]
repo = "org/explicit-repo"
refs = ["main"]
"""
        )

        # Create a user config that shouldn't be used
        user_config = tmp_path / "user-bootstrap.toml"
        user_config.write_text(
            """
[sources.user-source]
repo = "user/user-repo"
refs = ["develop"]
"""
        )

        # Load with explicit path only (no user_config_path)
        bootstrap = ModelSourceConfig.load(explicit_config)

        # Should only have explicit source, not user source
        assert "explicit-source" in bootstrap.sources
        assert "user-source" not in bootstrap.sources

    def test_load_bootstrap_explicit_path_with_overlay(self, tmp_path):
        """Test that explicit bootstrap path can use user config overlay."""
        # Create an explicit bootstrap file
        explicit_config = tmp_path / "explicit-bootstrap.toml"
        explicit_config.write_text(
            """
[sources.explicit-source]
repo = "org/explicit-repo"
refs = ["main"]
"""
        )

        # Create a user config
        user_config = tmp_path / "user-bootstrap.toml"
        user_config.write_text(
            """
[sources.user-source]
repo = "user/user-repo"
refs = ["develop"]
"""
        )

        # Load with both explicit paths
        bootstrap = ModelSourceConfig.load(
            bootstrap_path=explicit_config, user_config_path=user_config
        )

        # Should have both sources
        assert "explicit-source" in bootstrap.sources
        assert "user-source" in bootstrap.sources
        assert bootstrap.sources["explicit-source"].repo == "org/explicit-repo"
        assert bootstrap.sources["user-source"].repo == "user/user-repo"


class TestBootstrapSourceMethods:
    """Test BootstrapSource sync methods."""

    def test_source_has_sync_method(self):
        """Test that ModelSourceRepo has sync method."""
        bootstrap = ModelSourceConfig.load()
        source = bootstrap.sources[TEST_MODELS_SOURCE]
        assert hasattr(source, "sync")
        assert callable(source.sync)


class TestCache:
    """Test caching utilities."""

    def test_get_cache_root(self):
        """Test getting cache root directory."""
        cache_root = _DEFAULT_CACHE.root
        # Should contain modflow-devtools somewhere in the path
        assert "modflow-devtools" in str(cache_root)
        # Should be in user's cache directory (platform-specific)
        assert "cache" in str(cache_root).lower() or "caches" in str(cache_root).lower()

    def test_get_registry_cache_dir(self):
        """Test getting registry cache directory for a source/ref."""
        cache_dir = _DEFAULT_CACHE.get_registry_cache_dir(TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF)
        # Normalize path separators for comparison (Windows uses \, Unix uses /)
        cache_dir_str = str(cache_dir).replace("\\", "/")
        assert (
            TEST_MODELS_SOURCE_NAME in cache_dir_str
            or TEST_MODELS_SOURCE_NAME.replace("/", "-") in cache_dir_str
        )
        assert TEST_MODELS_REF in str(cache_dir)
        assert "registries" in str(cache_dir)


class TestDiscovery:
    """Test registry discovery."""

    def test_discover_registry(self):
        """Test discovering registry for test repo."""
        # Use test repo/ref from environment
        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        discovered = source.discover(ref=TEST_MODELS_REF)

        assert isinstance(discovered, DiscoveredModelRegistry)
        assert discovered.source == TEST_MODELS_SOURCE_NAME
        assert discovered.ref == TEST_MODELS_REF
        assert discovered.mode == "version_controlled"
        assert isinstance(discovered.registry, ModelRegistry)

    def test_discover_registry_nonexistent_ref(self):
        """Test that discovery fails gracefully for nonexistent ref."""
        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=["nonexistent-branch-12345"],
        )

        with pytest.raises(ModelRegistryDiscoveryError):
            source.discover(ref="nonexistent-branch-12345")


@pytest.mark.xdist_group("registry_cache")
class TestSync:
    """Test registry synchronization."""

    def test_sync_single_source_single_ref(self):
        """Test syncing a single source/ref."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
            verbose=True,
        )
        result = source.sync(ref=TEST_MODELS_REF, verbose=True)

        assert len(result.synced) == 1
        assert len(result.failed) == 0
        assert (TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF) in result.synced

    def test_sync_creates_cache(self):
        """Test that sync creates cached registry."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)
        assert not _DEFAULT_CACHE.has(TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )
        source.sync(ref=TEST_MODELS_REF)
        assert _DEFAULT_CACHE.has(TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF)

    def test_sync_skip_cached(self):
        """Test that sync skips already-cached registries."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        # First sync
        result1 = source.sync(ref=TEST_MODELS_REF)
        assert len(result1.synced) == 1

        # Second sync should skip
        result2 = source.sync(ref=TEST_MODELS_REF)
        assert len(result2.synced) == 0
        assert len(result2.skipped) == 1

    def test_sync_force(self):
        """Test that force flag re-syncs cached registries."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        # First sync
        result_initial = source.sync(ref=TEST_MODELS_REF)
        assert len(result_initial.failed) == 0, f"Initial sync failed: {result_initial.failed}"

        # Force sync
        result = source.sync(ref=TEST_MODELS_REF, force=True)
        assert len(result.synced) == 1
        assert len(result.skipped) == 0

    def test_sync_via_source_method(self):
        """Test syncing via ModelSourceRepo.sync() method."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        # Create source with test repo override
        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        # Sync via source method
        result = source.sync(ref=TEST_MODELS_REF, verbose=True)

        assert len(result.synced) == 1
        assert (TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF) in result.synced

    def test_source_is_synced_method(self):
        """Test ModelSourceRepo.is_synced() method."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        assert not source.is_synced(TEST_MODELS_REF)
        source.sync(ref=TEST_MODELS_REF)
        assert source.is_synced(TEST_MODELS_REF)

    def test_source_list_synced_refs_method(self):
        """Test ModelSourceRepo.list_synced_refs() method."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        assert TEST_MODELS_REF not in source.list_synced_refs()
        source.sync(ref=TEST_MODELS_REF)
        assert TEST_MODELS_REF in source.list_synced_refs()


@pytest.mark.xdist_group("registry_cache")
class TestRegistry:
    """Test registry structure and operations."""

    @pytest.fixture(scope="class")
    def synced_registry(self):
        """Fixture that syncs and loads a registry once for all tests."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)
        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )
        result = source.sync(ref=TEST_MODELS_REF)
        assert len(result.failed) == 0, f"Fixture sync failed: {result.failed}"
        registry = _DEFAULT_CACHE.load(TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF)
        return registry

    def test_registry_has_metadata(self, synced_registry):
        """Test that registry has required metadata."""
        assert hasattr(synced_registry, "schema_version")
        assert synced_registry.schema_version is not None

    def test_registry_has_files(self, synced_registry):
        """Test that registry has files."""
        assert len(synced_registry.files) > 0
        first_file = next(iter(synced_registry.files.values()))
        assert hasattr(first_file, "hash")

    def test_registry_has_models(self, synced_registry):
        """Test that registry has models."""
        assert len(synced_registry.models) > 0
        first_model_files = next(iter(synced_registry.models.values()))
        assert isinstance(first_model_files, list)
        assert len(first_model_files) > 0

    def test_registry_to_pooch_format(self, synced_registry):
        """Test converting registry to Pooch format."""
        pooch_registry = synced_registry.to_pooch_registry()
        assert isinstance(pooch_registry, dict)
        assert len(pooch_registry) == len(synced_registry.files)


class TestCLI:
    """Test CLI commands."""

    def test_cli_info(self, capsys):
        """Test 'info' command."""
        import argparse

        from modflow_devtools.models.__main__ import cmd_info

        args = argparse.Namespace()
        cmd_info(args)

        captured = capsys.readouterr()
        assert TEST_MODELS_SOURCE in captured.out or TEST_MODELS_SOURCE_NAME in captured.out

    def test_cli_list_empty(self, capsys):
        """Test 'list' command with no cached registries."""
        _DEFAULT_CACHE.clear()

        import argparse

        from modflow_devtools.models.__main__ import cmd_list

        args = argparse.Namespace(verbose=False)
        cmd_list(args)

        captured = capsys.readouterr()
        assert "No cached registries" in captured.out

    def test_cli_list_with_cache(self, capsys):
        """Test 'list' command with cached registries."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)
        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )
        result = source.sync(ref=TEST_MODELS_REF)

        # Verify sync succeeded before testing list command
        assert len(result.failed) == 0, f"Sync failed: {result.failed}"
        assert len(result.synced) == 1, f"Expected 1 synced registry, got {len(result.synced)}"
        assert (TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF) in result.synced

        import argparse

        from modflow_devtools.models.__main__ import cmd_list

        args = argparse.Namespace(verbose=True, source=None, ref=None)
        cmd_list(args)

        captured = capsys.readouterr()
        assert f"{TEST_MODELS_SOURCE_NAME}@{TEST_MODELS_REF}" in captured.out
        assert "Models:" in captured.out

    def test_cli_clear(self, capsys):
        """Test 'clear' command."""
        # Sync a registry first
        _DEFAULT_CACHE.clear(source=TEST_SOURCE_NAME, ref=TEST_REF)
        source = ModelSourceRepo(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )
        result = source.sync(ref=TEST_REF)
        assert len(result.synced) == 1

        # Verify it's cached
        assert _DEFAULT_CACHE.has(TEST_SOURCE_NAME, TEST_REF)

        # Clear with force flag
        import argparse

        from modflow_devtools.models.__main__ import cmd_clear

        args = argparse.Namespace(source=TEST_SOURCE_NAME, ref=TEST_REF, force=True)
        cmd_clear(args)

        # Verify it was cleared
        assert not _DEFAULT_CACHE.has(TEST_SOURCE_NAME, TEST_REF)

        captured = capsys.readouterr()
        assert "Cleared 1 cached registry" in captured.out


@pytest.mark.xdist_group("registry_cache")
class TestIntegration:
    """Integration tests for full workflows."""

    def test_full_workflow(self):
        """Test complete workflow: discover -> cache -> load."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )

        discovered = source.discover(ref=TEST_MODELS_REF)
        assert isinstance(discovered.registry, ModelRegistry)

        cache_path = _DEFAULT_CACHE.save(
            discovered.registry, TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF
        )
        assert cache_path.exists()

        loaded = _DEFAULT_CACHE.load(TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF)
        assert loaded is not None
        assert len(loaded.models) == len(discovered.registry.models)

    def test_sync_and_list_models(self):
        """Test syncing and listing available models."""
        _DEFAULT_CACHE.clear(source=TEST_MODELS_SOURCE_NAME, ref=TEST_MODELS_REF)

        source = ModelSourceRepo(
            repo=TEST_MODELS_REPO,
            name=TEST_MODELS_SOURCE_NAME,
            refs=[TEST_MODELS_REF],
        )
        result = source.sync(ref=TEST_MODELS_REF)
        assert len(result.synced) == 1

        cached = _DEFAULT_CACHE.list()
        assert len(cached) >= 1
        assert (TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF) in cached

        registry = _DEFAULT_CACHE.load(TEST_MODELS_SOURCE_NAME, TEST_MODELS_REF)
        assert len(registry.models) > 0


class TestMakeRegistry:
    """Test registry creation tool (make_registry.py)."""

    def _get_constructed_url(self, repo, ref, **kwargs):
        """Helper to extract constructed URL from make_registry verbose output.

        Mode is now inferred from presence of asset_file in kwargs.
        """
        import tempfile

        # Create a temporary directory to use as dummy path
        # This prevents the tool from trying to download (which would fail for fake repos)
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable,
                "-m",
                "modflow_devtools.models.make_registry",
                "--repo",
                repo,
                "--ref",
                ref,
                "--path",
                tmpdir,  # Provide dummy path to test URL construction without downloading
                "--verbose",
            ]

            for key, value in kwargs.items():
                cmd.extend([f"--{key.replace('_', '-')}", value])

            result = subprocess.run(cmd, capture_output=True, text=True)

            # Extract constructed URL from output
            for line in result.stdout.split("\n"):
                if "Constructed URL:" in line:
                    return line.split("Constructed URL: ")[1].strip()

            return None

    def test_url_construction_version(self):
        """Test URL construction for version mode (auto-detects path from directory)."""
        url = self._get_constructed_url(
            repo="MODFLOW-ORG/modflow6-testmodels",
            ref="master",
            name="mf6/test",
        )
        # Should be repo root (no path, or auto-detected)
        assert url.startswith(
            "https://raw.githubusercontent.com/MODFLOW-ORG/modflow6-testmodels/master"
        )

    def test_url_construction_version_different_ref(self):
        """Test URL construction for version mode with different ref."""
        url = self._get_constructed_url(
            repo="MODFLOW-ORG/modflow6-largetestmodels",
            ref="develop",
            name="mf6/large",
        )
        assert url.startswith(
            "https://raw.githubusercontent.com/MODFLOW-ORG/modflow6-largetestmodels/develop"
        )

    def test_url_construction_release(self):
        """Test URL construction for release mode."""
        url = self._get_constructed_url(
            repo="MODFLOW-ORG/modflow6-examples",
            ref="current",
            asset_file="mf6examples.zip",
            name="mf6/example",
        )
        assert (
            url
            == "https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip"
        )

    def test_url_construction_release_custom(self):
        """Test URL construction for release mode with custom repo/tag."""
        url = self._get_constructed_url(
            repo="username/my-models",
            ref="v1.0.0",
            asset_file="models.zip",
            name="custom/models",
        )
        assert url == "https://github.com/username/my-models/releases/download/v1.0.0/models.zip"
