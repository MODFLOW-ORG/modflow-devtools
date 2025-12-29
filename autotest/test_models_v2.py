"""
Tests for the new models API (dynamic registry).

These tests use wpbonelli/modflow6-testmodels@registry as the test source.
Once the registry is merged upstream, these can be updated to use MODFLOW-ORG.
"""

from pathlib import Path

import pytest

from modflow_devtools.models import cache, discovery, sync
from modflow_devtools.models.schema import Bootstrap, BootstrapSource, Registry

# Test configuration - using fork until registry is merged upstream
TEST_REPO = "wpbonelli/modflow6-testmodels"
TEST_REF = "registry"
TEST_SOURCE = "modflow6-testmodels"
TEST_SOURCE_NAME = "mf6/test"


class TestBootstrap:
    """Test bootstrap file loading and parsing."""

    def test_load_bootstrap(self):
        """Test loading the bootstrap file."""
        bootstrap = discovery.load_bootstrap()
        assert isinstance(bootstrap, Bootstrap)
        assert len(bootstrap.sources) > 0

    def test_bootstrap_has_testmodels(self):
        """Test that testmodels is configured."""
        bootstrap = discovery.load_bootstrap()
        assert "modflow6-testmodels" in bootstrap.sources

    def test_bootstrap_testmodels_config(self):
        """Test testmodels configuration."""
        bootstrap = discovery.load_bootstrap()
        testmodels = bootstrap.sources["modflow6-testmodels"]
        assert testmodels.repo == "MODFLOW-ORG/modflow6-testmodels"
        assert "develop" in testmodels.refs
        assert "master" in testmodels.refs

    def test_get_user_config_path(self):
        """Test that user config path is platform-appropriate."""
        user_config_path = discovery.get_user_config_path()
        assert isinstance(user_config_path, Path)
        assert user_config_path.name == "bootstrap.toml"
        assert "modflow-devtools" in str(user_config_path)
        # Should be in .config or AppData depending on platform
        assert ".config" in str(user_config_path) or "AppData" in str(user_config_path)

    def test_merge_bootstrap(self):
        """Test merging bundled and user bootstrap configs."""
        # Create bundled config
        bundled = Bootstrap(
            sources={
                "source1": BootstrapSource(repo="org/repo1", refs=["main"]),
                "source2": BootstrapSource(repo="org/repo2", refs=["develop"]),
            }
        )

        # Create user config that overrides source1 and adds source3
        user = Bootstrap(
            sources={
                "source1": BootstrapSource(
                    repo="user/custom-repo1", refs=["feature"]
                ),
                "source3": BootstrapSource(repo="user/repo3", refs=["master"]),
            }
        )

        # Merge
        merged = discovery.merge_bootstrap(bundled, user)

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
        bootstrap = discovery.load_bootstrap(user_config_path=user_config)

        # Check that user config was merged
        assert "custom-models" in bootstrap.sources
        assert bootstrap.sources["custom-models"].repo == "user/custom-models"

        # Check that user config overrode bundled config for testmodels
        if "modflow6-testmodels" in bootstrap.sources:
            assert (
                bootstrap.sources["modflow6-testmodels"].repo
                == "user/modflow6-testmodels-fork"
            )

    def test_load_bootstrap_explicit_path_no_overlay(self, tmp_path):
        """Test that explicit bootstrap path doesn't use user config overlay by default."""
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
        bootstrap = discovery.load_bootstrap(explicit_config)

        # Should only have explicit source, not user source
        assert "explicit-source" in bootstrap.sources
        assert "user-source" not in bootstrap.sources

    def test_load_bootstrap_explicit_path_with_overlay(self, tmp_path):
        """Test that explicit bootstrap path can use user config overlay when specified."""
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
        bootstrap = discovery.load_bootstrap(
            bootstrap_path=explicit_config, user_config_path=user_config
        )

        # Should have both sources
        assert "explicit-source" in bootstrap.sources
        assert "user-source" in bootstrap.sources
        assert bootstrap.sources["explicit-source"].repo == "org/explicit-repo"
        assert bootstrap.sources["user-source"].repo == "user/user-repo"


class TestCache:
    """Test caching utilities."""

    def test_get_cache_root(self):
        """Test getting cache root directory."""
        cache_root = cache.get_cache_root()
        assert cache_root.name == "modflow-devtools"
        # Should be in user's cache directory (platform-specific)
        assert "cache" in str(cache_root).lower() or "caches" in str(cache_root).lower()

    def test_get_registry_cache_dir(self):
        """Test getting registry cache directory for a source/ref."""
        cache_dir = cache.get_registry_cache_dir("modflow6-testmodels", "develop")
        assert "modflow6-testmodels" in str(cache_dir)
        assert "develop" in str(cache_dir)
        assert "registries" in str(cache_dir)

    def test_get_models_cache_dir(self):
        """Test getting models cache directory."""
        models_dir = cache.get_models_cache_dir()
        assert models_dir.name == "models"


class TestDiscovery:
    """Test registry discovery."""

    def test_discover_registry(self):
        """Test discovering registry for test fork."""
        # Use test fork with registry
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )

        discovered = discovery.discover_registry(
            source=source,
            source_name=TEST_SOURCE_NAME,
            ref=TEST_REF,
        )

        assert isinstance(discovered, discovery.DiscoveredRegistry)
        assert discovered.source == TEST_SOURCE_NAME
        assert discovered.ref == TEST_REF
        assert discovered.mode == "version_controlled"
        assert isinstance(discovered.registry, Registry)

    def test_discover_registry_nonexistent_ref(self):
        """Test that discovery fails gracefully for nonexistent ref."""
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=["nonexistent-branch-12345"],
        )

        with pytest.raises(discovery.RegistryDiscoveryError):
            discovery.discover_registry(
                source=source,
                source_name=TEST_SOURCE_NAME,
                ref="nonexistent-branch-12345",
            )


class TestSync:
    """Test registry synchronization."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        cache.clear_registry_cache()
        yield
        # Optionally clear after as well
        # cache.clear_registry_cache()

    def test_sync_single_source_single_ref(self):
        """Test syncing a single source/ref."""
        result = sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
            verbose=True,
        )

        assert len(result.synced) == 1
        assert len(result.failed) == 0
        assert (TEST_SOURCE_NAME, TEST_REF) in result.synced

    def test_sync_creates_cache(self):
        """Test that sync creates cached registry."""
        assert not cache.is_registry_cached(TEST_SOURCE_NAME, TEST_REF)

        sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )

        assert cache.is_registry_cached(TEST_SOURCE_NAME, TEST_REF)

    def test_sync_skip_cached(self):
        """Test that sync skips already-cached registries."""
        # First sync
        result1 = sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )
        assert len(result1.synced) == 1

        # Second sync should skip
        result2 = sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )
        assert len(result2.synced) == 0
        assert len(result2.skipped) == 1

    def test_sync_force(self):
        """Test that force flag re-syncs cached registries."""
        # First sync
        sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )

        # Force sync
        result = sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
            force=True,
        )
        assert len(result.synced) == 1
        assert len(result.skipped) == 0


class TestRegistry:
    """Test registry structure and operations."""

    @pytest.fixture
    def synced_registry(self):
        """Fixture that syncs and loads a registry."""
        cache.clear_registry_cache()
        sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )
        registry = cache.load_cached_registry(TEST_SOURCE_NAME, TEST_REF)
        return registry

    def test_registry_has_metadata(self, synced_registry):
        """Test that registry has required metadata."""
        assert hasattr(synced_registry.meta, "schema_version")
        assert hasattr(synced_registry.meta, "generated_at")
        assert hasattr(synced_registry.meta, "devtools_version")

    def test_registry_has_files(self, synced_registry):
        """Test that registry has files."""
        assert len(synced_registry.files) > 0
        # Check file structure
        first_file = next(iter(synced_registry.files.values()))
        assert hasattr(first_file, "url")
        assert hasattr(first_file, "hash")

    def test_registry_has_models(self, synced_registry):
        """Test that registry has models."""
        assert len(synced_registry.models) > 0
        # Check model structure
        first_model_files = next(iter(synced_registry.models.values()))
        assert isinstance(first_model_files, list)
        assert len(first_model_files) > 0

    def test_registry_to_pooch_format(self, synced_registry):
        """Test converting registry to Pooch format."""
        pooch_registry = synced_registry.to_pooch_registry()
        assert isinstance(pooch_registry, dict)
        assert len(pooch_registry) == len(synced_registry.files)

        pooch_urls = synced_registry.to_pooch_urls()
        assert isinstance(pooch_urls, dict)


class TestCLI:
    """Test CLI commands."""

    def test_cli_info(self, capsys):
        """Test 'info' command."""
        import argparse

        from modflow_devtools.models.__main__ import cmd_info

        args = argparse.Namespace()
        cmd_info(args)

        captured = capsys.readouterr()
        assert "modflow6-testmodels" in captured.out or "mf6/test" in captured.out

    def test_cli_list_empty(self, capsys):
        """Test 'list' command with no cached registries."""
        cache.clear_registry_cache()

        import argparse

        from modflow_devtools.models.__main__ import cmd_list

        args = argparse.Namespace(verbose=False)
        cmd_list(args)

        captured = capsys.readouterr()
        assert "No cached registries" in captured.out

    def test_cli_list_with_cache(self, capsys):
        """Test 'list' command with cached registries."""
        cache.clear_registry_cache()
        sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )

        import argparse

        from modflow_devtools.models.__main__ import cmd_list

        args = argparse.Namespace(verbose=True)
        cmd_list(args)

        captured = capsys.readouterr()
        assert f"{TEST_SOURCE_NAME}@{TEST_REF}" in captured.out
        assert "Models:" in captured.out


class TestIntegration:
    """Integration tests for full workflows."""

    def test_full_workflow(self):
        """Test complete workflow: discover -> cache -> load."""
        # Clear cache
        cache.clear_registry_cache()

        # Create test source
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )

        # Discover registry
        discovered = discovery.discover_registry(
            source=source,
            source_name=TEST_SOURCE_NAME,
            ref=TEST_REF,
        )
        assert isinstance(discovered.registry, Registry)

        # Cache registry
        cache_path = cache.cache_registry(
            discovered.registry, TEST_SOURCE_NAME, TEST_REF
        )
        assert cache_path.exists()

        # Load from cache
        loaded = cache.load_cached_registry(TEST_SOURCE_NAME, TEST_REF)
        assert loaded is not None
        assert len(loaded.models) == len(discovered.registry.models)

    def test_sync_and_list_models(self):
        """Test syncing and listing available models."""
        cache.clear_registry_cache()

        # Sync
        result = sync.sync_registry(
            source=TEST_SOURCE,
            ref=TEST_REF,
            repo=TEST_REPO,
        )
        assert len(result.synced) == 1

        # List cached registries
        cached = cache.list_cached_registries()
        assert len(cached) >= 1
        assert (TEST_SOURCE_NAME, TEST_REF) in cached

        # Load and check models
        registry = cache.load_cached_registry(TEST_SOURCE_NAME, TEST_REF)
        assert len(registry.models) > 0
