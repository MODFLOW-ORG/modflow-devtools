"""
Tests for the DFNs API registry infrastructure.

Tests can be configured via environment variables (loaded from .env file).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from packaging.version import Version

from modflow_devtools.dfns.fetch import fetch_dfns
from modflow_devtools.markers import requires_pkg

PROJ_ROOT = Path(__file__).parents[1]
DFN_DIR = PROJ_ROOT / "autotest" / "temp" / "dfn"

# Test configuration (loaded from .env file via pytest-dotenv plugin)
TEST_DFN_REPO = os.getenv("TEST_DFNS_REPO", "MODFLOW-ORG/modflow6")
TEST_DFN_REF = os.getenv("TEST_DFNS_REF", "develop")
TEST_DFN_SOURCE = os.getenv("TEST_DFNS_SOURCE", "modflow6")

# For fetching DFN files directly (legacy tests)
MF6_OWNER = TEST_DFN_REPO.split("/")[0]
MF6_REPO = TEST_DFN_REPO.split("/")[1]
MF6_REF = TEST_DFN_REF


@pytest.fixture(scope="module")
def dfn_dir():
    """Ensure DFN files are downloaded for testing."""
    if not any(DFN_DIR.glob("*.dfn")):
        fetch_dfns(MF6_OWNER, MF6_REPO, MF6_REF, DFN_DIR, verbose=True)
    return DFN_DIR


@requires_pkg("boltons")
class TestDfnSpec:
    """Tests for the DfnSpec class."""

    def test_load_from_directory(self, dfn_dir):
        """Test loading a DfnSpec from a directory of DFN files."""
        from modflow_devtools.dfns import DfnSpec

        spec = DfnSpec.load(dfn_dir)

        # Should have loaded and mapped to v2
        assert spec.schema_version == Version("2")
        assert spec.root is not None
        assert spec.root.name == "sim-nam"

    def test_load_with_explicit_schema_version(self, dfn_dir):
        """Test loading with explicit schema version."""
        from modflow_devtools.dfns import DfnSpec

        spec = DfnSpec.load(dfn_dir, schema_version="2")

        assert spec.schema_version == Version("2")

    def test_mapping_protocol(self, dfn_dir):
        """Test that DfnSpec implements the Mapping protocol."""
        from modflow_devtools.dfns import DfnSpec

        spec = DfnSpec.load(dfn_dir)

        # Test __len__
        assert len(spec) > 100  # Should have many components

        # Test __iter__
        names = list(spec)
        assert "sim-nam" in names
        assert "gwf-nam" in names
        assert "gwf-chd" in names

        # Test __getitem__
        gwf_chd = spec["gwf-chd"]
        assert gwf_chd.name == "gwf-chd"
        assert gwf_chd.parent == "gwf-nam"

        # Test __contains__
        assert "gwf-chd" in spec
        assert "nonexistent" not in spec

        # Test keys(), values(), items()
        assert "gwf-wel" in spec.keys()
        assert any(d.name == "gwf-wel" for d in spec.values())
        assert any(n == "gwf-wel" for n, d in spec.items())

    def test_getitem_raises_keyerror(self, dfn_dir):
        """Test that __getitem__ raises KeyError for missing components."""
        from modflow_devtools.dfns import DfnSpec

        spec = DfnSpec.load(dfn_dir)

        with pytest.raises(KeyError, match="nonexistent"):
            _ = spec["nonexistent"]

    def test_hierarchical_access(self, dfn_dir):
        """Test accessing components through the hierarchical tree."""
        from modflow_devtools.dfns import DfnSpec

        spec = DfnSpec.load(dfn_dir)

        # Root should be sim-nam
        assert spec.root.name == "sim-nam"

        # Root should have children
        assert spec.root.children is not None
        assert "gwf-nam" in spec.root.children

        # gwf-nam should have its own children
        gwf_nam = spec.root.children["gwf-nam"]
        assert gwf_nam.children is not None
        assert "gwf-chd" in gwf_nam.children

    def test_load_empty_directory_raises(self, tmp_path):
        """Test that loading from empty directory raises ValueError."""
        from modflow_devtools.dfns import DfnSpec

        with pytest.raises(ValueError, match="No DFN files found"):
            DfnSpec.load(tmp_path)


@requires_pkg("pydantic")
class TestBootstrapConfig:
    """Tests for bootstrap configuration schemas."""

    def test_source_config_defaults(self):
        """Test SourceConfig default values."""
        from modflow_devtools.dfns.registry import SourceConfig

        config = SourceConfig(repo="owner/repo")

        assert config.repo == "owner/repo"
        assert config.dfn_path == "doc/mf6io/mf6ivar/dfn"
        assert config.registry_path == ".registry/dfns.toml"
        assert config.refs == []

    def test_source_config_custom_values(self):
        """Test SourceConfig with custom values."""
        from modflow_devtools.dfns.registry import SourceConfig

        config = SourceConfig(
            repo="custom/repo",
            dfn_path="custom/path",
            registry_path="custom/registry.toml",
            refs=["main", "v1.0"],
        )

        assert config.repo == "custom/repo"
        assert config.dfn_path == "custom/path"
        assert config.registry_path == "custom/registry.toml"
        assert config.refs == ["main", "v1.0"]

    def test_bootstrap_config_load(self, tmp_path):
        """Test loading BootstrapConfig from TOML file."""
        from modflow_devtools.dfns.registry import BootstrapConfig

        config_file = tmp_path / "dfns.toml"
        config_file.write_text("""
[sources.test]
repo = "test/repo"
refs = ["main"]
""")

        config = BootstrapConfig.load(config_file)

        assert "test" in config.sources
        assert config.sources["test"].repo == "test/repo"
        assert config.sources["test"].refs == ["main"]

    def test_bootstrap_config_load_nonexistent(self, tmp_path):
        """Test loading from nonexistent file returns empty config."""
        from modflow_devtools.dfns.registry import BootstrapConfig

        config = BootstrapConfig.load(tmp_path / "nonexistent.toml")

        assert config.sources == {}

    def test_bootstrap_config_merge(self):
        """Test merging two bootstrap configs."""
        from modflow_devtools.dfns.registry import BootstrapConfig, SourceConfig

        base = BootstrapConfig(
            sources={
                "source1": SourceConfig(repo="base/source1", refs=["v1"]),
                "source2": SourceConfig(repo="base/source2"),
            }
        )
        overlay = BootstrapConfig(
            sources={
                "source1": SourceConfig(repo="overlay/source1", refs=["v2"]),
                "source3": SourceConfig(repo="overlay/source3"),
            }
        )

        merged = BootstrapConfig.merge(base, overlay)

        # overlay overrides base for source1
        assert merged.sources["source1"].repo == "overlay/source1"
        assert merged.sources["source1"].refs == ["v2"]
        # source2 from base preserved
        assert merged.sources["source2"].repo == "base/source2"
        # source3 from overlay added
        assert merged.sources["source3"].repo == "overlay/source3"

    def test_get_bootstrap_config(self):
        """Test loading bundled bootstrap config."""
        from modflow_devtools.dfns.registry import get_bootstrap_config

        config = get_bootstrap_config()

        assert "modflow6" in config.sources
        assert config.sources["modflow6"].repo == "MODFLOW-ORG/modflow6"


@requires_pkg("pydantic")
class TestRegistryMeta:
    """Tests for registry metadata schemas."""

    def test_dfn_registry_meta_load(self, tmp_path):
        """Test loading DfnRegistryMeta from TOML file."""
        from modflow_devtools.dfns.registry import DfnRegistryMeta

        registry_file = tmp_path / "dfns.toml"
        registry_file.write_text("""
schema_version = "1.0"

[metadata]
ref = "6.6.0"

[files."gwf-chd.dfn"]
hash = "sha256:abc123"

[files."gwf-wel.dfn"]
hash = "sha256:def456"
""")

        meta = DfnRegistryMeta.load(registry_file)

        assert meta.schema_version == "1.0"
        assert meta.ref == "6.6.0"
        assert len(meta.files) == 2
        assert meta.files["gwf-chd.dfn"].hash == "sha256:abc123"
        assert meta.files["gwf-wel.dfn"].hash == "sha256:def456"

    def test_dfn_registry_meta_save(self, tmp_path):
        """Test saving DfnRegistryMeta to TOML file."""
        import tomli

        from modflow_devtools.dfns.registry import DfnRegistryFile, DfnRegistryMeta

        meta = DfnRegistryMeta(
            schema_version="1.0",
            ref="test-ref",
            files={
                "test.dfn": DfnRegistryFile(hash="sha256:abc123"),
            },
        )

        output_path = tmp_path / "output.toml"
        meta.save(output_path)

        assert output_path.exists()

        with output_path.open("rb") as f:
            data = tomli.load(f)

        assert data["schema_version"] == "1.0"
        assert data["metadata"]["ref"] == "test-ref"
        assert data["files"]["test.dfn"]["hash"] == "sha256:abc123"


@requires_pkg("boltons", "pydantic")
class TestLocalDfnRegistry:
    """Tests for LocalDfnRegistry class."""

    def test_init(self, dfn_dir):
        """Test LocalDfnRegistry initialization."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir, ref="local")

        assert registry.source == "modflow6"
        assert registry.ref == "local"
        assert registry.path == dfn_dir.resolve()

    def test_spec_property(self, dfn_dir):
        """Test accessing spec through registry."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)

        spec = registry.spec

        assert spec.schema_version == Version("2")
        assert len(spec) > 100

    def test_get_dfn(self, dfn_dir):
        """Test getting a DFN by name."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)

        dfn = registry.get_dfn("gwf-chd")

        assert dfn.name == "gwf-chd"
        assert dfn.parent == "gwf-nam"

    def test_get_dfn_path(self, dfn_dir):
        """Test getting file path for a component."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)

        path = registry.get_dfn_path("gwf-chd")

        assert path.exists()
        assert path.name == "gwf-chd.dfn"

    def test_get_dfn_path_not_found(self, dfn_dir):
        """Test getting path for nonexistent component raises FileNotFoundError."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)

        with pytest.raises(FileNotFoundError, match="nonexistent"):
            registry.get_dfn_path("nonexistent")

    def test_schema_version_property(self, dfn_dir):
        """Test schema_version property."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)

        assert registry.schema_version == Version("2")

    def test_components_property(self, dfn_dir):
        """Test components property returns flat dict."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)

        components = registry.components

        assert isinstance(components, dict)
        assert "gwf-chd" in components
        assert components["gwf-chd"].name == "gwf-chd"


@requires_pkg("pydantic")
class TestCacheUtilities:
    """Tests for cache and config utilities."""

    def test_get_cache_dir(self):
        """Test getting cache directory path."""
        from modflow_devtools.dfns.registry import get_cache_dir

        cache_dir = get_cache_dir("dfn")

        assert cache_dir.name == "dfn"
        assert "modflow-devtools" in str(cache_dir)

    def test_get_user_config_path(self):
        """Test getting user config path."""
        from modflow_devtools.dfns.registry import get_user_config_path

        config_path = get_user_config_path("dfn")

        assert config_path.name == "dfns.toml"
        assert "modflow-devtools" in str(config_path)

    def test_get_cache_dir_custom_subdir(self):
        """Test cache dir with custom subdirectory."""
        from modflow_devtools.dfns.registry import get_cache_dir

        cache_dir = get_cache_dir("custom")

        assert cache_dir.name == "custom"


@requires_pkg("tomli", "tomli_w")
class TestMakeRegistry:
    """Tests for the registry generation tool."""

    def test_compute_file_hash(self, tmp_path):
        """Test computing file hash."""
        from modflow_devtools.dfn.make_registry import compute_file_hash

        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        hash_value = compute_file_hash(test_file)

        assert hash_value.startswith("sha256:")
        # Known hash for "hello world"
        assert "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9" in hash_value

    def test_scan_dfn_directory(self, dfn_dir):
        """Test scanning a DFN directory."""
        from modflow_devtools.dfn.make_registry import scan_dfn_directory

        files = scan_dfn_directory(dfn_dir)

        assert len(files) > 100
        assert "gwf-chd.dfn" in files
        assert "common.dfn" in files
        assert all(h.startswith("sha256:") for h in files.values())

    def test_generate_registry(self, dfn_dir, tmp_path):
        """Test generating a registry file."""
        import tomli

        from modflow_devtools.dfn.make_registry import generate_registry

        output_path = tmp_path / "dfns.toml"

        generate_registry(
            dfn_path=dfn_dir,
            output_path=output_path,
            ref="test-ref",
        )

        assert output_path.exists()

        with output_path.open("rb") as f:
            data = tomli.load(f)

        assert data["schema_version"] == "1.0"
        assert "generated_at" in data
        assert data["metadata"]["ref"] == "test-ref"
        assert "gwf-chd.dfn" in data["files"]

    def test_generate_registry_empty_dir(self, tmp_path):
        """Test generating registry from empty directory raises ValueError."""
        from modflow_devtools.dfn.make_registry import generate_registry

        with pytest.raises(ValueError, match="No DFN files found"):
            generate_registry(
                dfn_path=tmp_path,
                output_path=tmp_path / "dfns.toml",
            )

    def test_cli_help(self):
        """Test CLI help output."""
        from modflow_devtools.dfn.make_registry import main

        # --help should exit with 0
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_cli_generate(self, dfn_dir, tmp_path):
        """Test CLI generate command."""
        from modflow_devtools.dfn.make_registry import main

        output_path = tmp_path / "dfns.toml"

        result = main(
            [
                "--dfn-path",
                str(dfn_dir),
                "--output",
                str(output_path),
                "--ref",
                "test-ref",
            ]
        )

        assert result == 0
        assert output_path.exists()


@requires_pkg("pydantic")
class TestCLI:
    """Tests for the DFNs CLI."""

    def test_main_help(self):
        """Test CLI help output."""
        from modflow_devtools.dfn.__main__ import main

        result = main([])
        assert result == 0

    def test_info_command(self):
        """Test info command."""
        from modflow_devtools.dfn.__main__ import main

        result = main(["info"])
        assert result == 0

    def test_clean_command_no_cache(self, tmp_path):
        """Test clean command when cache doesn't exist."""
        from modflow_devtools.dfn.__main__ import main

        # Patch get_cache_dir to return nonexistent directory
        with patch("modflow_devtools.dfn.__main__.get_cache_dir") as mock_cache_dir:
            mock_cache_dir.return_value = tmp_path / "nonexistent"
            result = main(["clean"])

        assert result == 0

    def test_sync_command_no_registry(self):
        """Test sync command when registry doesn't exist (expected to fail)."""
        from modflow_devtools.dfn.__main__ import main

        # This should fail because MODFLOW 6 repo doesn't have the registry yet
        result = main(["sync", "--ref", "nonexistent-ref"])
        assert result == 1


@requires_pkg("pydantic", "pooch", "boltons")
class TestRemoteDfnRegistry:
    """Tests for RemoteDfnRegistry with mocked network calls."""

    def test_init(self):
        """Test RemoteDfnRegistry initialization."""
        from modflow_devtools.dfn import RemoteDfnRegistry

        registry = RemoteDfnRegistry(source="modflow6", ref="develop")

        assert registry.source == "modflow6"
        assert registry.ref == "develop"

    def test_unknown_source_raises(self):
        """Test that unknown source raises ValueError."""
        from modflow_devtools.dfn import RemoteDfnRegistry

        with pytest.raises(ValueError, match="Unknown source"):
            RemoteDfnRegistry(source="nonexistent", ref="develop")

    def test_construct_raw_url(self):
        """Test URL construction."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(source="modflow6", ref="6.6.0")

        url = registry._construct_raw_url("doc/mf6io/mf6ivar/dfn")

        assert "raw.githubusercontent.com" in url
        assert "MODFLOW-ORG/modflow6" in url
        assert "6.6.0" in url

    def test_get_registry_cache_path(self):
        """Test getting registry cache path."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(source="modflow6", ref="6.6.0")

        path = registry._get_registry_cache_path()

        assert "registries" in str(path)
        assert "modflow6" in str(path)
        assert "6.6.0" in str(path)
        assert path.name == "dfns.toml"

    def test_get_files_cache_dir(self):
        """Test getting files cache directory."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(source="modflow6", ref="6.6.0")

        path = registry._get_files_cache_dir()

        assert "files" in str(path)
        assert "modflow6" in str(path)
        assert "6.6.0" in str(path)

    def test_fetch_registry_not_found(self):
        """Test that fetching nonexistent registry raises appropriate error."""
        from modflow_devtools.dfns.registry import (
            DfnRegistryNotFoundError,
            RemoteDfnRegistry,
        )

        registry = RemoteDfnRegistry(source="modflow6", ref="nonexistent-ref-12345")

        with pytest.raises(DfnRegistryNotFoundError):
            registry._fetch_registry(force=True)

    def test_init_with_repo_override(self):
        """Test RemoteDfnRegistry with repo override."""
        from modflow_devtools.dfn import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        assert registry.source == TEST_DFN_SOURCE
        assert registry.ref == TEST_DFN_REF
        assert registry.repo == TEST_DFN_REPO

    def test_construct_raw_url_with_repo_override(self):
        """Test URL construction with repo override."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        url = registry._construct_raw_url("doc/mf6io/mf6ivar/dfn")

        assert "raw.githubusercontent.com" in url
        assert TEST_DFN_REPO in url
        assert TEST_DFN_REF in url

    def test_fetch_registry(self):
        """Test fetching registry from the test repository."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        meta = registry._fetch_registry(force=True)

        assert meta is not None
        assert len(meta.files) > 0
        # Registry file may have a different ref than what we requested
        # (e.g., generated from develop branch but accessed on registry branch)
        assert meta.ref is not None

    def test_sync_files(self):
        """Test syncing DFN files from the test repository."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        # Sync should succeed (fetches registry and sets up pooch)
        registry.sync(force=True)

        # Should be able to fetch a DFN file
        path = registry.get_dfn_path("gwf-chd")
        assert path.exists()

    def test_get_dfn(self):
        """Test getting a DFN from the test repository."""
        from modflow_devtools.dfn import Dfn
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        # Ensure synced
        registry.sync()

        dfn = registry.get_dfn("gwf-chd")

        assert isinstance(dfn, Dfn)
        assert dfn.name == "gwf-chd"

    def test_get_spec(self):
        """Test getting the full spec from the test repository."""
        from modflow_devtools.dfns import DfnSpec
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        # Ensure synced
        registry.sync()

        spec = registry.spec

        assert isinstance(spec, DfnSpec)
        assert "gwf-chd" in spec
        assert "sim-nam" in spec

    def test_list_components(self):
        """Test listing available components from the test repository."""
        from modflow_devtools.dfns.registry import RemoteDfnRegistry

        registry = RemoteDfnRegistry(
            source=TEST_DFN_SOURCE,
            ref=TEST_DFN_REF,
            repo=TEST_DFN_REPO,
        )

        # Ensure synced
        registry.sync()

        # Use spec.keys() to list components
        components = list(registry.spec.keys())

        assert len(components) > 100
        assert "gwf-chd" in components
        assert "sim-nam" in components


@requires_pkg("boltons", "pydantic")
class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_list_components_local(self, dfn_dir):
        """Test list_components with local registry."""
        from modflow_devtools.dfn import LocalDfnRegistry

        registry = LocalDfnRegistry(path=dfn_dir)
        components = list(registry.spec.keys())

        assert len(components) > 100
        assert "gwf-chd" in components
        assert "sim-nam" in components

    def test_get_sync_status(self):
        """Test get_sync_status function."""
        from modflow_devtools.dfns.registry import get_sync_status

        status = get_sync_status()

        assert isinstance(status, dict)
        # All refs should be either True or False
        assert all(isinstance(v, bool) for v in status.values())
