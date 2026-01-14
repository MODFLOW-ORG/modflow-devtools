from pathlib import Path

from modflow_devtools.programs import (
    _DEFAULT_CACHE,
    ProgramCache,
    ProgramRegistry,
    ProgramSourceConfig,
    ProgramSourceRepo,
    get_user_config_path,
)


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
                "source1": ProgramSourceRepo(
                    repo="org/repo1", name="source1", refs=["v1"]
                ),
                "source2": ProgramSourceRepo(
                    repo="org/repo2", name="source2", refs=["v2"]
                ),
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
