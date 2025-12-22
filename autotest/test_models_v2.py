"""
Tests for the new models API (dynamic registry).

These tests use modflow6-testmodels/develop as the test source.
They assume a registry file has been added to that repository.
"""

import pytest

from modflow_devtools.models import cache, discovery, sync
from modflow_devtools.models.schema import Bootstrap, Registry


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

    def test_discover_registry_develop(self):
        """Test discovering registry for modflow6-testmodels/develop."""
        bootstrap = discovery.load_bootstrap()
        source = bootstrap.sources["modflow6-testmodels"]
        source_name = bootstrap.get_source_name("modflow6-testmodels")

        # This will fail until registry is added to the repo
        discovered = discovery.discover_registry(
            source=source,
            source_name=source_name,
            ref="develop",
        )

        assert isinstance(discovered, discovery.DiscoveredRegistry)
        assert discovered.source == source_name
        assert discovered.ref == "develop"
        assert discovered.mode == "version_controlled"
        assert isinstance(discovered.registry, Registry)

    def test_discover_registry_master(self):
        """Test discovering registry for modflow6-testmodels/master."""
        bootstrap = discovery.load_bootstrap()
        source = bootstrap.sources["modflow6-testmodels"]
        source_name = bootstrap.get_source_name("modflow6-testmodels")

        discovered = discovery.discover_registry(
            source=source,
            source_name=source_name,
            ref="master",
        )

        assert isinstance(discovered, discovery.DiscoveredRegistry)
        assert discovered.ref == "master"

    def test_discover_registry_nonexistent_ref(self):
        """Test that discovery fails gracefully for nonexistent ref."""
        bootstrap = discovery.load_bootstrap()
        source = bootstrap.sources["modflow6-testmodels"]
        source_name = bootstrap.get_source_name("modflow6-testmodels")

        with pytest.raises(discovery.RegistryDiscoveryError):
            discovery.discover_registry(
                source=source,
                source_name=source_name,
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
            source="modflow6-testmodels",
            ref="develop",
            verbose=True,
        )

        assert len(result.synced) == 1
        assert len(result.failed) == 0
        assert ("mf6/test", "develop") in result.synced

    def test_sync_single_source_all_refs(self):
        """Test syncing all refs for a single source."""
        result = sync.sync_registry(
            source="modflow6-testmodels",
            verbose=True,
        )

        assert len(result.synced) >= 2  # develop and master at minimum
        assert len(result.failed) == 0

    def test_sync_all_sources(self):
        """Test syncing all configured sources."""
        result = sync.sync_registry(verbose=True)

        # Should sync all configured refs for all sources
        assert len(result.synced) >= 2  # At least testmodels develop + master
        # May have failures if other sources aren't ready yet

    def test_sync_creates_cache(self):
        """Test that sync creates cached registry."""
        assert not cache.is_registry_cached("mf6/test", "develop")

        sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )

        assert cache.is_registry_cached("mf6/test", "develop")

    def test_sync_skip_cached(self):
        """Test that sync skips already-cached registries."""
        # First sync
        result1 = sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )
        assert len(result1.synced) == 1

        # Second sync should skip
        result2 = sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )
        assert len(result2.synced) == 0
        assert len(result2.skipped) == 1

    def test_sync_force(self):
        """Test that force flag re-syncs cached registries."""
        # First sync
        sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )

        # Force sync
        result = sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
            force=True,
        )
        assert len(result.synced) == 1
        assert len(result.skipped) == 0

    def test_get_sync_status(self):
        """Test getting sync status."""
        # Initially nothing cached
        status = sync.get_sync_status()
        assert "mf6/test" in status
        assert len(status["mf6/test"]["cached_refs"]) == 0

        # Sync one ref
        sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )

        # Check status again
        status = sync.get_sync_status()
        assert "develop" in status["mf6/test"]["cached_refs"]


class TestRegistry:
    """Test registry structure and operations."""

    @pytest.fixture
    def synced_registry(self):
        """Fixture that syncs and loads a registry."""
        cache.clear_registry_cache()
        sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )
        registry = cache.load_cached_registry("mf6/test", "develop")
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
        from modflow_devtools.models.__main__ import cmd_info
        import argparse

        args = argparse.Namespace()
        cmd_info(args)

        captured = capsys.readouterr()
        assert "modflow6-testmodels" in captured.out or "mf6/test" in captured.out

    def test_cli_list_empty(self, capsys):
        """Test 'list' command with no cached registries."""
        cache.clear_registry_cache()

        from modflow_devtools.models.__main__ import cmd_list
        import argparse

        args = argparse.Namespace(verbose=False)
        cmd_list(args)

        captured = capsys.readouterr()
        assert "No cached registries" in captured.out

    def test_cli_list_with_cache(self, capsys):
        """Test 'list' command with cached registries."""
        cache.clear_registry_cache()
        sync.sync_registry(source="modflow6-testmodels", ref="develop")

        from modflow_devtools.models.__main__ import cmd_list
        import argparse

        args = argparse.Namespace(verbose=True)
        cmd_list(args)

        captured = capsys.readouterr()
        assert "mf6/test@develop" in captured.out
        assert "Models:" in captured.out


class TestIntegration:
    """Integration tests for full workflows."""

    def test_full_workflow(self):
        """Test complete workflow: load bootstrap -> discover -> cache -> load."""
        # Clear cache
        cache.clear_registry_cache()

        # Load bootstrap
        bootstrap = discovery.load_bootstrap()
        assert "modflow6-testmodels" in bootstrap.sources

        # Discover registry
        source = bootstrap.sources["modflow6-testmodels"]
        source_name = bootstrap.get_source_name("modflow6-testmodels")
        discovered = discovery.discover_registry(
            source=source,
            source_name=source_name,
            ref="develop",
        )
        assert isinstance(discovered.registry, Registry)

        # Cache registry
        cache_path = cache.cache_registry(discovered.registry, source_name, "develop")
        assert cache_path.exists()

        # Load from cache
        loaded = cache.load_cached_registry(source_name, "develop")
        assert loaded is not None
        assert len(loaded.models) == len(discovered.registry.models)

    def test_sync_and_list_models(self):
        """Test syncing and listing available models."""
        cache.clear_registry_cache()

        # Sync
        result = sync.sync_registry(
            source="modflow6-testmodels",
            ref="develop",
        )
        assert len(result.synced) == 1

        # List cached registries
        cached = cache.list_cached_registries()
        assert len(cached) >= 1
        assert ("mf6/test", "develop") in cached

        # Load and check models
        registry = cache.load_cached_registry("mf6/test", "develop")
        assert len(registry.models) > 0
