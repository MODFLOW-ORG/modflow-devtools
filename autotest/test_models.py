"""
Tests for the models API.

Includes tests for both v1 (bundled registry) and v2 (dynamic registry).
V2 tests can be configured via environment variables (loaded from .env file).
"""

import os
from itertools import islice
from pathlib import Path

import pytest
import tomli

import modflow_devtools.models as models
from modflow_devtools.misc import is_in_ci
from modflow_devtools.models import cache, discovery, sync
from modflow_devtools.models.schema import Bootstrap, BootstrapSource, Registry

# V1 test configuration (bundled registry)
TAKE = 5 if is_in_ci() else None
PROJ_ROOT = Path(__file__).parents[1]
MODELS_PATH = PROJ_ROOT / "modflow_devtools" / "registry" / "models.toml"
MODELS = tomli.load(MODELS_PATH.open("rb"))
REGISTRY = models.DEFAULT_REGISTRY

# V2 test configuration (dynamic registry)
# Loaded from .env file via pytest-dotenv plugin
TEST_REPO = os.getenv("TEST_REPO", "wpbonelli/modflow6-testmodels")
TEST_REF = os.getenv("TEST_REF", "registry")
TEST_SOURCE = os.getenv("TEST_SOURCE", "modflow6-testmodels")
TEST_SOURCE_NAME = os.getenv("TEST_SOURCE_NAME", "mf6/test")


# ============================================================================
# V1 Tests (Bundled Registry - Backward Compatibility)
# ============================================================================


def test_files():
    files = models.get_files()
    assert files is not None, "Files not loaded"
    assert files is REGISTRY.files
    assert any(files), "Registry is empty"


@pytest.mark.parametrize("model_name, files", MODELS.items(), ids=list(MODELS.keys()))
def test_models(model_name, files):
    model_names = list(models.get_models().keys())
    assert model_name in model_names, f"Model {model_name} not found in model map"
    assert files == REGISTRY.models[model_name], (
        f"Files for model {model_name} do not match"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)


@pytest.mark.parametrize(
    "example_name, model_names",
    models.get_examples().items(),
    ids=list(models.get_examples().keys()),
)
def test_examples(example_name, model_names):
    assert example_name in models.get_examples()
    for model_name in model_names:
        assert model_name in REGISTRY.models


@pytest.mark.parametrize(
    "model_name, files",
    list(islice(MODELS.items(), TAKE)),
    ids=list(MODELS.keys())[:TAKE],
)
def test_copy_to(model_name, files, tmp_path):
    workspace = models.copy_to(tmp_path, model_name, verbose=True)
    assert workspace.exists(), f"Model {model_name} was not copied to {tmp_path}"
    assert workspace.is_dir(), f"Model {model_name} is not a directory"
    found = [p for p in workspace.rglob("*") if p.is_file()]
    assert len(found) == len(files), (
        f"Model {model_name} does not have the correct number of files, "
        f"expected {len(files)}, got {len(found)}"
    )
    if "mf6" in model_name:
        assert any(Path(f).name == "mfsim.nam" for f in files)


# ============================================================================
# V2 Tests (Dynamic Registry)
# ============================================================================


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
        assert TEST_SOURCE in bootstrap.sources

    def test_bootstrap_testmodels_config(self):
        """Test testmodels configuration."""
        bootstrap = discovery.load_bootstrap()
        testmodels = bootstrap.sources[TEST_SOURCE]
        # Note: bundled config points to MODFLOW-ORG, not the test fork
        assert "MODFLOW-ORG/modflow6-testmodels" in testmodels.repo
        assert "develop" in testmodels.refs or "master" in testmodels.refs

    def test_bootstrap_source_has_name(self):
        """Test that bootstrap sources have name injected."""
        bootstrap = discovery.load_bootstrap()
        for key, source in bootstrap.sources.items():
            assert source.name is not None
            # If no explicit name override, name should equal key
            if not source.name:
                assert source.name == key

    def test_get_user_config_path(self):
        """Test that user config path is platform-appropriate."""
        user_config_path = discovery.get_user_config_path()
        assert isinstance(user_config_path, Path)
        assert "bootstrap.toml" in user_config_path.name
        assert "modflow-devtools" in str(user_config_path)
        # Should be in .config or AppData depending on platform
        assert ".config" in str(user_config_path) or "AppData" in str(user_config_path)

    def test_merge_bootstrap(self):
        """Test merging bundled and user bootstrap configs."""
        # Create bundled config
        bundled = Bootstrap(
            sources={
                "source1": BootstrapSource(
                    repo="org/repo1", name="source1", refs=["main"]
                ),
                "source2": BootstrapSource(
                    repo="org/repo2", name="source2", refs=["develop"]
                ),
            }
        )

        # Create user config that overrides source1 and adds source3
        user = Bootstrap(
            sources={
                "source1": BootstrapSource(
                    repo="user/custom-repo1", name="source1", refs=["feature"]
                ),
                "source3": BootstrapSource(
                    repo="user/repo3", name="source3", refs=["master"]
                ),
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
        if TEST_SOURCE in bootstrap.sources:
            assert (
                bootstrap.sources[TEST_SOURCE].repo == "user/modflow6-testmodels-fork"
            )

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
        bootstrap = discovery.load_bootstrap(explicit_config)

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
        bootstrap = discovery.load_bootstrap(
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
        """Test that BootstrapSource has sync method."""
        bootstrap = discovery.load_bootstrap()
        source = bootstrap.sources[TEST_SOURCE]
        assert hasattr(source, "sync")
        assert callable(source.sync)

    def test_source_has_is_synced_method(self):
        """Test that BootstrapSource has is_synced method."""
        bootstrap = discovery.load_bootstrap()
        source = bootstrap.sources[TEST_SOURCE]
        assert hasattr(source, "is_synced")
        assert callable(source.is_synced)

    def test_source_has_list_synced_refs_method(self):
        """Test that BootstrapSource has list_synced_refs method."""
        bootstrap = discovery.load_bootstrap()
        source = bootstrap.sources[TEST_SOURCE]
        assert hasattr(source, "list_synced_refs")
        assert callable(source.list_synced_refs)


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
        cache_dir = cache.get_registry_cache_dir(TEST_SOURCE_NAME, TEST_REF)
        assert TEST_SOURCE_NAME.replace("/", "-") in str(cache_dir)
        assert TEST_REF in str(cache_dir)
        assert "registries" in str(cache_dir)

    def test_get_models_cache_dir(self):
        """Test getting models cache directory."""
        models_dir = cache.get_models_cache_dir()
        assert models_dir.name == "models"


class TestDiscovery:
    """Test registry discovery."""

    def test_discover_registry(self):
        """Test discovering registry for test repo."""
        # Use test repo/ref from environment
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )

        discovered = discovery.discover_registry(
            source=source,
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

    def test_sync_via_source_method(self):
        """Test syncing via BootstrapSource.sync() method."""
        cache.clear_registry_cache()

        # Create source with test repo override
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )

        # Sync via source method
        result = source.sync(ref=TEST_REF, verbose=True)

        assert len(result.synced) == 1
        assert (TEST_SOURCE_NAME, TEST_REF) in result.synced

    def test_source_is_synced_method(self):
        """Test BootstrapSource.is_synced() method."""
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )

        # Should not be synced initially
        assert not source.is_synced(TEST_REF)

        # Sync
        source.sync(ref=TEST_REF)

        # Should be synced now
        assert source.is_synced(TEST_REF)

    def test_source_list_synced_refs_method(self):
        """Test BootstrapSource.list_synced_refs() method."""
        source = BootstrapSource(
            repo=TEST_REPO,
            name=TEST_SOURCE_NAME,
            refs=[TEST_REF],
        )

        # Should have no synced refs initially
        assert TEST_REF not in source.list_synced_refs()

        # Sync
        source.sync(ref=TEST_REF)

        # Should show in synced refs
        assert TEST_REF in source.list_synced_refs()


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
        assert hasattr(first_file, "hash")
        # Note: url field removed in v2 (dynamic URL construction)

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


class TestCLI:
    """Test CLI commands."""

    def test_cli_info(self, capsys):
        """Test 'info' command."""
        import argparse

        from modflow_devtools.models.__main__ import cmd_info

        args = argparse.Namespace()
        cmd_info(args)

        captured = capsys.readouterr()
        assert TEST_SOURCE in captured.out or TEST_SOURCE_NAME in captured.out

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
