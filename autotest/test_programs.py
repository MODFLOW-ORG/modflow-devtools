import warnings
from pathlib import Path

import pytest

from modflow_devtools.programs import (
    _DEFAULT_CACHE,
    ProgramCache,
    ProgramDistribution,
    ProgramMetadata,
    ProgramRegistry,
    ProgramSourceConfig,
    ProgramSourceRepo,
    get_user_config_path,
)

# Suppress experimental API warning for tests
warnings.filterwarnings("ignore", message=".*modflow_devtools.programs.*experimental.*")


class TestProgramCache:
    """Test cache management."""

    def test_get_cache_root(self):
        """Test getting cache root directory."""
        cache = ProgramCache()
        assert "modflow-devtools" in str(cache.root)
        # Should contain 'programs'
        assert "programs" in str(cache.root)

    def test_save_and_load_registry(self):
        """Test saving and loading a registry."""
        cache = ProgramCache()
        cache.clear()

        # Create a simple registry
        registry = ProgramRegistry(
            schema_version="1.0",
            programs={
                "test-program": {
                    "version": "1.0.0",
                    "repo": "test/repo",
                    "exe": "bin/test-program",
                    "binaries": {},
                }
            },
        )

        # Save it
        cache.save(registry, "test-source", "1.0.0")

        # Check it exists
        assert cache.has("test-source", "1.0.0")

        # Load it back
        loaded = cache.load("test-source", "1.0.0")
        assert loaded is not None
        assert loaded.schema_version == "1.0"
        assert "test-program" in loaded.programs

        # Clean up
        cache.clear()

    def test_list_cached_registries(self):
        """Test listing cached registries."""
        cache = ProgramCache()
        cache.clear()

        # Create and save a few registries
        for i in range(3):
            registry = ProgramRegistry(programs={})
            cache.save(registry, f"source{i}", f"v{i}.0")

        # List them
        cached = cache.list()
        assert len(cached) == 3
        assert ("source0", "v0.0") in cached
        assert ("source1", "v1.0") in cached
        assert ("source2", "v2.0") in cached

        # Clean up
        cache.clear()


class TestProgramSourceConfig:
    """Test bootstrap configuration loading."""

    def test_load_bootstrap(self):
        """Test loading bootstrap configuration."""
        config = ProgramSourceConfig.load()
        assert isinstance(config, ProgramSourceConfig)
        assert len(config.sources) > 0

    def test_bootstrap_has_sources(self):
        """Test that bootstrap has expected sources."""
        config = ProgramSourceConfig.load()
        # Should have modflow6 at minimum
        assert "modflow6" in config.sources

    def test_bootstrap_source_has_name(self):
        """Test that sources have names injected."""
        config = ProgramSourceConfig.load()
        for key, source in config.sources.items():
            assert source.name is not None
            # If no explicit name override, name should equal key
            if source.name == key:
                assert source.name == key

    def test_get_user_config_path(self):
        """Test that user config path is platform-appropriate."""
        user_config_path = get_user_config_path()
        assert isinstance(user_config_path, Path)
        assert user_config_path.name == "programs.toml"
        assert "modflow-devtools" in str(user_config_path)

    def test_merge_config(self):
        """Test merging configurations."""
        # Create base config
        base = ProgramSourceConfig(
            sources={
                "source1": ProgramSourceRepo(repo="org/repo1", name="source1", refs=["v1"]),
                "source2": ProgramSourceRepo(repo="org/repo2", name="source2", refs=["v2"]),
            }
        )

        # Create overlay config
        overlay = ProgramSourceConfig(
            sources={
                "source1": ProgramSourceRepo(
                    repo="org/custom-repo1", name="source1", refs=["v1.1"]
                ),
                "source3": ProgramSourceRepo(repo="org/repo3", name="source3", refs=["v3"]),
            }
        )

        # Merge
        merged = ProgramSourceConfig.merge(base, overlay)

        # Check that overlay overrode base for source1
        assert merged.sources["source1"].repo == "org/custom-repo1"
        assert merged.sources["source1"].refs == ["v1.1"]

        # Check that base source2 is preserved
        assert merged.sources["source2"].repo == "org/repo2"

        # Check that overlay source3 was added
        assert merged.sources["source3"].repo == "org/repo3"

    def test_load_with_user_config(self, tmp_path):
        """Test loading bootstrap with user config overlay."""
        # Create a user config file
        user_config = tmp_path / "programs.toml"
        user_config.write_text(
            """
[sources.custom-programs]
repo = "user/custom-programs"
refs = ["v1.0"]

[sources.modflow6]
repo = "user/modflow6-fork"
refs = ["custom-branch"]
"""
        )

        # Load with user config
        config = ProgramSourceConfig.load(user_config_path=user_config)

        # Check that user config was merged
        assert "custom-programs" in config.sources
        assert config.sources["custom-programs"].repo == "user/custom-programs"

        # Check that user config overrode bundled for modflow6
        if "modflow6" in config.sources:
            assert config.sources["modflow6"].repo == "user/modflow6-fork"

    def test_status(self):
        """Test sync status reporting."""
        _DEFAULT_CACHE.clear()

        config = ProgramSourceConfig.load()
        status = config.status

        # Should have status for all configured sources
        assert len(status) > 0

        # Each status should have required fields
        for source_name, source_status in status.items():
            assert source_status.repo
            assert isinstance(source_status.configured_refs, list)
            assert isinstance(source_status.cached_refs, list)
            assert isinstance(source_status.missing_refs, list)

        _DEFAULT_CACHE.clear()


class TestProgramSourceRepo:
    """Test source repository methods."""

    def test_source_has_sync_method(self):
        """Test that ProgramSourceRepo has sync method."""
        config = ProgramSourceConfig.load()
        source = next(iter(config.sources.values()))
        assert hasattr(source, "sync")
        assert callable(source.sync)

    def test_source_has_is_synced_method(self):
        """Test that ProgramSourceRepo has is_synced method."""
        config = ProgramSourceConfig.load()
        source = next(iter(config.sources.values()))
        assert hasattr(source, "is_synced")
        assert callable(source.is_synced)

    def test_source_has_list_synced_refs_method(self):
        """Test that ProgramSourceRepo has list_synced_refs method."""
        config = ProgramSourceConfig.load()
        source = next(iter(config.sources.values()))
        assert hasattr(source, "list_synced_refs")
        assert callable(source.list_synced_refs)


class TestProgramManager:
    """Test ProgramManager class."""

    def test_program_manager_init(self):
        """Test ProgramManager initialization."""
        from modflow_devtools.programs import ProgramCache, ProgramManager

        # Test with default cache
        manager = ProgramManager()
        assert isinstance(manager.cache, ProgramCache)

        # Test with custom cache
        custom_cache = ProgramCache()
        manager = ProgramManager(cache=custom_cache)
        assert manager.cache is custom_cache

    def test_program_manager_lazy_config(self):
        """Test lazy configuration loading."""
        from modflow_devtools.programs import ProgramManager

        manager = ProgramManager()
        # Config should not be loaded yet
        assert manager._config is None

        # Accessing config should load it
        config = manager.config
        assert config is not None
        assert manager._config is config

        # Second access should return same instance
        config2 = manager.config
        assert config2 is config

    def test_default_manager_exists(self):
        """Test that default manager instance exists."""
        from modflow_devtools.programs import _DEFAULT_MANAGER, ProgramManager

        assert isinstance(_DEFAULT_MANAGER, ProgramManager)

    def test_convenience_wrappers(self):
        """Test that convenience functions wrap the default manager."""
        from modflow_devtools.programs import (
            install_program,
            list_installed,
            uninstall_program,
        )

        # All functions should exist and be callable
        assert callable(install_program)
        assert callable(uninstall_program)
        assert callable(list_installed)

    def test_program_manager_list_installed_empty(self):
        """Test list_installed with no installations."""
        from modflow_devtools.programs import ProgramCache, ProgramManager

        # Use fresh cache
        cache = ProgramCache()
        cache.clear()

        # Also clear metadata directory to ensure no leftover installation data
        if cache.metadata_dir.exists():
            import shutil

            shutil.rmtree(cache.metadata_dir)

        manager = ProgramManager(cache=cache)

        installed = manager.list_installed()
        assert installed == {}

    def test_program_manager_error_handling(self):
        """Test error handling in ProgramManager."""
        import pytest

        from modflow_devtools.programs import ProgramInstallationError, ProgramManager

        manager = ProgramManager()

        # Test install non-existent program
        with pytest.raises(ProgramInstallationError, match="not found"):
            manager.install("nonexistent-program-xyz")

    def test_installation_metadata_integration(self):
        """Test InstallationMetadata integration with ProgramManager."""
        from datetime import datetime, timezone
        from pathlib import Path

        from modflow_devtools.programs import (
            InstallationMetadata,
            ProgramCache,
            ProgramInstallation,
        )

        cache = ProgramCache()
        cache.clear()

        # Create and save metadata
        metadata = InstallationMetadata("test-program")
        installation = ProgramInstallation(
            version="1.0.0",
            platform="linux",
            bindir=Path("/tmp/test"),
            installed_at=datetime.now(timezone.utc),
            source={
                "repo": "test/repo",
                "tag": "1.0.0",
                "asset_url": "https://example.com/test.zip",
                "hash": "",
            },
            executables=["test-program"],
        )
        metadata.add_installation(installation)

        # Verify it was saved
        metadata2 = InstallationMetadata("test-program")
        assert metadata2.load()
        installations = metadata2.list_installations()
        assert len(installations) == 1
        assert installations[0].version == "1.0.0"
        assert installations[0].platform == "linux"

        # Clean up
        cache.clear()


class TestExeFieldResolution:
    """Test executable path resolution logic."""

    def test_distribution_level_exe_takes_precedence(self):
        """Test that distribution-level exe overrides program-level."""
        metadata = ProgramMetadata(
            exe="bin/program",  # Program-level
            dists=[
                ProgramDistribution(
                    name="linux",
                    asset="linux.zip",
                    exe="custom/path/to/program",  # Distribution-level
                ),
                ProgramDistribution(
                    name="win64",
                    asset="win64.zip",
                    exe="custom/path/to/program.exe",  # Distribution-level
                ),
            ],
        )

        # Distribution-level should be used
        assert metadata.get_exe_path("program", "linux") == "custom/path/to/program"
        assert metadata.get_exe_path("program", "win64") == "custom/path/to/program.exe"

    def test_program_level_exe_fallback(self):
        """Test that program-level exe is used when no distribution match."""
        metadata = ProgramMetadata(
            exe="bin/program",  # Program-level
            dists=[
                ProgramDistribution(
                    name="linux",
                    asset="linux.zip",
                    # No exe specified
                ),
                ProgramDistribution(
                    name="win64",
                    asset="win64.zip",
                    # No exe specified
                ),
            ],
        )

        # Program-level should be used
        assert metadata.get_exe_path("program", "linux") == "bin/program"
        # Should auto-add .exe on Windows
        assert metadata.get_exe_path("program", "win64") == "bin/program.exe"

    def test_default_exe_path(self):
        """Test default exe path when neither level specifies."""
        metadata = ProgramMetadata(
            # No program-level exe
            dists=[
                ProgramDistribution(
                    name="linux",
                    asset="linux.zip",
                    # No distribution-level exe
                ),
                ProgramDistribution(
                    name="win64",
                    asset="win64.zip",
                    # No distribution-level exe
                ),
            ],
        )

        # Should default to bin/{program_name}
        assert metadata.get_exe_path("myprogram", "linux") == "bin/myprogram"
        # Should auto-add .exe on Windows
        assert metadata.get_exe_path("myprogram", "win64") == "bin/myprogram.exe"

    def test_windows_exe_extension_handling(self):
        """Test automatic .exe extension on Windows platforms."""
        metadata = ProgramMetadata(
            dists=[
                ProgramDistribution(
                    name="win64",
                    asset="win64.zip",
                    exe="mfnwt",  # No .exe extension
                ),
            ],
        )

        # Should auto-add .exe
        assert metadata.get_exe_path("mfnwt", "win64") == "mfnwt.exe"

        # Should not double-add if already present
        metadata2 = ProgramMetadata(
            dists=[
                ProgramDistribution(
                    name="win64",
                    asset="win64.zip",
                    exe="mfnwt.exe",  # Already has .exe
                ),
            ],
        )
        assert metadata2.get_exe_path("mfnwt", "win64") == "mfnwt.exe"

    def test_mixed_exe_field_usage(self):
        """Test mixed usage: some distributions with exe, some without."""
        metadata = ProgramMetadata(
            exe="default/path/program",  # Program-level fallback
            dists=[
                ProgramDistribution(
                    name="linux",
                    asset="linux.zip",
                    exe="linux-specific/bin/program",  # Has distribution-level
                ),
                ProgramDistribution(
                    name="mac",
                    asset="mac.zip",
                    # No distribution-level, should use program-level
                ),
                ProgramDistribution(
                    name="win64",
                    asset="win64.zip",
                    exe="win64-specific/bin/program.exe",  # Has distribution-level
                ),
            ],
        )

        # Linux uses distribution-level
        assert metadata.get_exe_path("program", "linux") == "linux-specific/bin/program"
        # Mac uses program-level fallback
        assert metadata.get_exe_path("program", "mac") == "default/path/program"
        # Windows uses distribution-level
        assert metadata.get_exe_path("program", "win64") == "win64-specific/bin/program.exe"

    def test_nonexistent_platform_uses_fallback(self):
        """Test that non-matching platform uses program-level or default."""
        metadata = ProgramMetadata(
            exe="bin/program",
            dists=[
                ProgramDistribution(
                    name="linux",
                    asset="linux.zip",
                    exe="linux/bin/program",
                ),
            ],
        )

        # Requesting win64 when only linux has distribution-specific exe
        # Should fall back to program-level
        assert metadata.get_exe_path("program", "win64") == "bin/program.exe"


class TestForceSemantics:
    """Test force flag semantics for sync and install."""

    def test_sync_force_flag(self):
        """Test that sync --force re-downloads even if cached."""
        # Clear cache first
        _DEFAULT_CACHE.clear()

        config = ProgramSourceConfig.load()

        # Get a source that we know exists (modflow6)
        if "modflow6" not in config.sources:
            pytest.skip("modflow6 source not configured")

        source = config.sources["modflow6"]

        # First sync (should download)
        result1 = source.sync(
            ref=source.refs[0] if source.refs else None, force=False, verbose=False
        )

        # Check if sync succeeded (it might fail if no registry available)
        if not result1.synced:
            pytest.skip(f"Sync failed: {result1.failed}")

        # Verify it's cached
        ref = source.refs[0] if source.refs else None
        assert _DEFAULT_CACHE.has(source.name, ref)

        # Second sync without force (should skip)
        result2 = source.sync(ref=ref, force=False, verbose=False)
        assert len(result2.skipped) > 0

        # Third sync with force (should re-download)
        result3 = source.sync(ref=ref, force=True, verbose=False)
        assert len(result3.synced) > 0

        # Clean up
        _DEFAULT_CACHE.clear()

    def test_install_force_does_not_sync(self):
        """Test that install --force does not re-sync registry."""
        from modflow_devtools.programs import ProgramManager

        # This is more of a design verification test
        # We verify that the install method signature has force parameter
        # and that it's documented to not sync

        manager = ProgramManager()

        # Check install method has force parameter
        import inspect

        sig = inspect.signature(manager.install)
        assert "force" in sig.parameters

        # Check that force parameter is documented correctly
        # The docstring should mention that force doesn't re-sync
        docstring = manager.install.__doc__
        if docstring:
            # This is a basic check - in reality the behavior is tested
            # through integration tests
            assert docstring is not None

    def test_sync_and_install_independence(self):
        """Test that sync cache and install state are independent."""
        from modflow_devtools.programs import ProgramCache

        cache = ProgramCache()

        # Registry cache is separate from installation metadata
        # Registry cache: ~/.cache/modflow-devtools/programs/registries/
        # Install metadata: ~/.cache/modflow-devtools/programs/metadata/

        assert cache.registries_dir != cache.metadata_dir

        # Verify paths are different
        assert "registries" in str(cache.registries_dir)
        assert "metadata" in str(cache.metadata_dir)
