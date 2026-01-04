# DFNs API Design

This document describes the design of the DFNs (Definition Files) API ([GitHub issue #262](https://github.com/MODFLOW-ORG/modflow-devtools/issues/262)). It is intended to be developer-facing, not user-facing, though users may also find it informative.

This is a living document which will be updated as development proceeds.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Background](#background)
- [Objective](#objective)
- [Motivation](#motivation)
- [Overview](#overview)
- [Architecture](#architecture)
  - [Bootstrap file](#bootstrap-file)
    - [Bootstrap file contents](#bootstrap-file-contents)
    - [Sample bootstrap file](#sample-bootstrap-file)
  - [DFN index and registry files](#dfn-index-and-registry-files)
    - [Specification index file](#specification-index-file)
    - [Registry file format](#registry-file-format)
    - [Sample files](#sample-files)
  - [Registry discovery](#registry-discovery)
    - [Discovery modes](#discovery-modes)
    - [Registry discovery procedure](#registry-discovery-procedure)
  - [Registry/DFN caching](#registrydfn-caching)
  - [Registry synchronization](#registry-synchronization)
    - [Manual sync](#manual-sync)
    - [Automatic sync](#automatic-sync)
  - [Source repository integration](#source-repository-integration)
  - [DFN addressing](#dfn-addressing)
  - [Registry classes](#registry-classes)
    - [DfnRegistry (abstract base)](#dfnregistry-abstract-base)
    - [RemoteDfnRegistry](#remotedfnregistry)
    - [LocalDfnRegistry](#localdfnregistry)
  - [Module-level API](#module-level-api)
- [Schema Versioning](#schema-versioning)
  - [Separating format from schema](#separating-format-from-schema)
  - [Schema evolution](#schema-evolution)
  - [Tentative v2 schema design](#tentative-v2-schema-design)
- [Component Hierarchy](#component-hierarchy)
- [Backwards Compatibility Strategy](#backwards-compatibility-strategy)
  - [Development approach](#development-approach)
  - [Schema version support](#schema-version-support)
  - [API compatibility](#api-compatibility)
  - [Migration timeline](#migration-timeline)
- [Implementation Dependencies](#implementation-dependencies)
  - [Existing work on dfn branch](#existing-work-on-dfn-branch)
  - [Core components](#core-components)
  - [MODFLOW 6 repository integration](#modflow-6-repository-integration)
  - [Testing and documentation](#testing-and-documentation)
- [Relationship to Models and Programs APIs](#relationship-to-models-and-programs-apis)
- [Design Decisions](#design-decisions)
  - [Use Pooch for fetching](#use-pooch-for-fetching)
  - [Schema versioning strategy](#schema-versioning-strategy)
  - [Future enhancements](#future-enhancements)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Background

The `modflow_devtools.dfn` module currently provides utilities for parsing and working with MODFLOW 6 definition files. On the `dfn` branch, significant work has been done including:

- Object models for DFN components (`Dfn`, `Block`, `Field` classes)
- Schema definitions for both v1 (legacy) and v2 (in development)
- Parsers for the old DFN format
- Schema mapping capabilities including utilities for converting between flat and hierarchical component representations
- A `fetch_dfns()` function for manually downloading DFN files from the MODFLOW 6 repository
- Validation tools

However, there is currently no registry-based API for:
- Automatically discovering and synchronizing DFN files from remote sources
- Managing multiple versions of definition files simultaneously
- Caching definition files locally for offline use

Users must manually download definition files or rely on whatever happens to be bundled with their installation. This creates similar problems to what the Models API addressed:
1. **Version coupling**: Users are locked to whatever DFN version is bundled
2. **Manual management**: Users must manually track and download DFN updates
3. **No multi-version support**: Difficult to work with multiple MODFLOW 6 versions simultaneously
4. **Maintenance burden**: Developers must manually update bundled DFNs

## Objective

Create a DFNs API that:
1. **Mirrors Models/Programs API patterns** for consistency and familiarity
2. **Leverages existing dfn module work** (parsers, schemas, object models)
3. **Provides automated discovery** of definition files from MODFLOW 6 repository
4. **Supports multiple versions** simultaneously with explicit version addressing
5. **Uses Pooch** for fetching and caching (avoiding custom HTTP client code)
6. **Handles schema evolution** with proper separation of file format vs schema version
7. **Maintains loose coupling** between devtools and remote DFN sources

## Overview

Make the MODFLOW 6 repository responsible for publishing a definition file registry.

Make `modflow-devtools` responsible for:
- Defining the DFN registry publication contract
- Providing registry-creation machinery
- Storing bootstrap information locating the MODFLOW 6 repository
- Discovering remote registries at install time or on demand
- Caching registry metadata and definition files
- Exposing a synchronized view of available definition files
- Parsing and validating definition files
- Mapping between schema versions

MODFLOW 6 is currently the only repository using the DFN specification system, but this leaves the door open for other repositories to begin using it.

## Architecture

The DFNs API will mirror the Models and Programs API architecture, adapted for definition file-specific concerns.

### Bootstrap file

The **bootstrap** file tells `modflow-devtools` where to look for DFN registries. This file will be checked into the repository at `modflow_devtools/dfn/bootstrap.toml` and distributed with the package.

#### Bootstrap file contents

At the top level, the bootstrap file consists of a table of `sources`, each describing a repository that publishes definition files.

Each source has:
- `repo`: Repository identifier (owner/name)
- `dfn_path`: Path within the repository to the directory containing DFN files (defaults to `doc/mf6io/mf6ivar/dfn`)
- `registry_path`: Path within the repository to the registry metadata file (defaults to `.registry/dfns.toml`)
- `refs`: List of git refs (branches, tags, or commit hashes) to sync by default

#### Sample bootstrap file

```toml
[sources.modflow6]
repo = "MODFLOW-ORG/modflow6"
dfn_path = "doc/mf6io/mf6ivar/dfn"
registry_path = ".registry/dfns.toml"
refs = [
    "6.6.0",
    "6.5.0",
    "6.4.4",
    "develop",
]
```

### DFN spec and registry files

Two types of metadata files support the DFNs API:

1. **Specification file** (`spec.toml`): Part of the DFN set, describes the specification itself
2. **Registry file** (`dfns.toml`): Infrastructure for discovery and distribution

#### Specification file

A `spec.toml` file lives **in the DFN directory** alongside the DFN files. It describes the specification:

```toml
# MODFLOW 6 input specification
schema_version = "1.1"

[components]
# Component organization by type
simulation = ["sim-nam", "sim-tdis"]
models = ["gwf-nam", "gwt-nam", "gwe-nam"]
packages = ["gwf-chd", "gwf-drn", "gwf-wel", ...]
exchanges = ["exg-gwfgwf", "exg-gwfgwt", ...]
solutions = ["sln-ims"]
```

**Notes**:
- The spec file is **part of the DFN set**, not registry infrastructure
- **Handwritten** by MODFLOW 6 developers, not generated
- Describes the specification as a whole (schema version, component organization)
- Lives in the DFN directory: `doc/mf6io/mf6ivar/dfn/spec.toml`
- Component parent-child relationships are in individual DFN files (see Component Hierarchy section)
- **v1/v1.1**: Spec file is **optional** - can be inferred if not present:
  - `schema_version` can be inferred from DFN content or defaulted
  - `components` section can be inferred from DFN filenames
  - Hierarchy inferred from naming conventions (e.g., `gwf-chd` → parent is `gwf-nam`)
- **v2**: Spec file is **required** for clarity and correctness:
  - Explicit `schema_version = "2.0"` declaration
  - Can be a single file containing everything, or a spec file pointing to separate component files
  - Ensures clean structural/format separation
- **Correspondence**: `spec.toml` (on disk) ↔ `DfnSpec` (in Python)

**Minimal handwritten spec file (v1/v1.1)**:
```toml
schema_version = "1.1"
```

Or for v1/v1.1, no spec file needed - everything inferred.

#### Registry file format

A `dfns.toml` registry file for **discovery and distribution**:

```toml
# Registry metadata (optional)
generated_at = "2025-01-02T10:30:00Z"
devtools_version = "1.9.0"
registry_schema_version = "1.0"

[metadata]
ref = "6.6.0"  # Optional, known from discovery context

# File listings (filenames and hashes, URLs constructed as needed)
[files]
"spec.toml" = {hash = "sha256:..."}  # Specification file
"sim-nam.dfn" = {hash = "sha256:..."}
"sim-tdis.dfn" = {hash = "sha256:..."}
"gwf-nam.dfn" = {hash = "sha256:..."}
"gwf-chd.dfn" = {hash = "sha256:..."}
# ... all DFN files
```

**Notes**:
- Registry is purely **infrastructure** for discovery and distribution
- The `files` section maps filenames to hashes for verification
- URLs are constructed dynamically from bootstrap metadata (repo, ref, dfn_path) + filename
- This allows using personal forks by changing the bootstrap file
- **All registry metadata is optional** - registries can be handwritten minimally
- The specification file is listed alongside DFN files

**Minimal handwritten registry**:
```toml
[files]
"spec.toml" = {hash = "sha256:abc123..."}
"sim-nam.dfn" = {hash = "sha256:def456..."}
"gwf-nam.dfn" = {hash = "sha256:789abc..."}
```

#### Sample files

**For TOML-format DFNs (future v2 schema)**:

**Option A**: Separate component files with spec file

Spec file (`spec.toml`):
```toml
schema_version = "2.0"

[components]
simulation = ["sim-nam", "sim-tdis"]
models = ["gwf-nam", "gwt-nam", "gwe-nam"]
# ...
```

Registry (`dfns.toml`):
```toml
[files]
"spec.toml" = {hash = "sha256:..."}
"sim-nam.toml" = {hash = "sha256:..."}
"gwf-nam.toml" = {hash = "sha256:..."}
# ...
```

**Option B**: Single specification file

`spec.toml` contains everything:
```toml
schema_version = "2.0"

[sim-nam]
parent = null
# ... all sim-nam fields

[gwf-nam]
parent = "sim-nam"
# ... all gwf-nam fields

# ... all other components
```

Registry just points to the one file:
```toml
[files]
"spec.toml" = {hash = "sha256:..."}
```

### Registry discovery

DFN registries can be discovered in two modes, similar to the Models API.

#### Discovery modes

**1. Registry as version-controlled file** (primary mode):

Registry files are versioned in the MODFLOW 6 repository at a conventional path (e.g., `.registry/dfns.toml`). Discovery uses GitHub raw content URLs:

```
https://raw.githubusercontent.com/{org}/{repo}/{ref}/.registry/dfns.toml
```

This mode supports:
- Any git ref (branches, tags, commit hashes)
- Tight coupling between registry and actual DFN files
- Easy manual inspection of registry contents

**2. Registry as release asset** (future mode):

For MODFLOW 6 releases, registry files can also be published as release assets:

```
https://github.com/{org}/{repo}/releases/download/{tag}/dfns.toml
```

This mode:
- Requires release tags only
- Allows registry generation in CI without committing to repo
- Provides faster discovery (no need to check multiple ref types)

**Discovery precedence**: Release asset mode takes precedence if both exist (same as Models API).

#### Registry discovery procedure

At sync time, `modflow-devtools` discovers remote registries for each configured ref:

1. **Check for release tag** (if release asset mode enabled):
   - Look for a GitHub release with the specified tag
   - Try to fetch `dfns.toml` from release assets
   - If found, use it and skip step 2
   - If release exists but lacks registry asset, fall through to step 2

2. **Check for version-controlled registry**:
   - Look for a commit hash, tag, or branch matching the ref
   - Try to fetch registry from `{registry_path}` via raw content URL
   - If found, use it
   - If ref exists but lacks registry file, raise error:
     ```python
     RegistryDiscoveryError(
         f"Registry file not found in {registry_path} for 'modflow6@{ref}'"
     )
     ```

3. **Failure case**:
   - If no matching ref found at all, raise error:
     ```python
     RegistryDiscoveryError(
         f"Registry discovery failed, ref 'modflow6@{ref}' does not exist"
     )
     ```

**Note**: For initial implementation, focus on version-controlled mode. Release asset mode requires MODFLOW 6 to start distributing DFN files with releases (currently they don't), but would be a natural addition once that happens.

### Registry/DFN caching

Cache structure mirrors the Models API pattern:

```
~/.cache/modflow-devtools/
├── dfn/
│   ├── registries/
│   │   └── modflow6/              # by source repo
│   │       ├── 6.6.0/
│   │       │   └── dfns.toml
│   │       ├── 6.5.0/
│   │       │   └── dfns.toml
│   │       └── develop/
│   │           └── dfns.toml
│   └── files/                     # Actual DFN files, managed by Pooch
│       └── modflow6/
│           ├── 6.6.0/
│           │   ├── sim-nam.dfn
│           │   ├── gwf-nam.dfn
│           │   └── ...
│           ├── 6.5.0/
│           │   └── ...
│           └── develop/
│               └── ...
```

**Cache management**:
- Registry files cached per source repository and ref
- DFN files fetched and cached individually by Pooch, verified against registry hashes
- Cache persists across Python sessions for offline use
- Cache can be cleared with `dfn clean` command
- Users can check cache status with `dfn info`

### Registry synchronization

Synchronization updates the local registry cache with remote metadata.

#### Manual sync

Exposed as a CLI command and Python API:

```bash
# Sync all configured refs
python -m modflow_devtools.dfn sync

# Sync specific ref
python -m modflow_devtools.dfn sync --ref 6.6.0

# Sync to any git ref (branch, tag, commit hash)
python -m modflow_devtools.dfn sync --ref develop
python -m modflow_devtools.dfn sync --ref f3df630a

# Force re-download
python -m modflow_devtools.dfn sync --force

# Show sync status
python -m modflow_devtools.dfn info

# List available DFNs for a ref
python -m modflow_devtools.dfn list --ref 6.6.0

# List all synced refs
python -m modflow_devtools.dfn list
```

Or via Python API:

```python
from modflow_devtools.dfn import sync_dfns, get_sync_status

# Sync all configured refs
sync_dfns()

# Sync specific ref
sync_dfns(ref="6.6.0")

# Check sync status
status = get_sync_status()
```

#### Automatic sync

- **At install time**: Best-effort sync to default refs during package installation (fail silently on network errors)
- **On first use**: If registry cache is empty for requested ref, attempt to sync before raising errors
- **Lazy loading**: Don't sync until DFN access is actually requested
- **Configurable**: Users can disable auto-sync via environment variable: `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`

### Source repository integration

For the MODFLOW 6 repository to integrate:

1. **Optionally handwrite `spec.toml`** in the DFN directory (if not present, everything is inferred):
   ```toml
   # doc/mf6io/mf6ivar/dfn/spec.toml
   schema_version = "1.1"

   [components]
   simulation = ["sim-nam", "sim-tdis"]
   models = ["gwf-nam", "gwt-nam", "gwe-nam"]
   # ...
   ```

   If `spec.toml` is absent (v1/v1.1 only), `DfnSpec.load()` will:
   - Scan the directory for `.dfn` and `.toml` files
   - Infer schema version from DFN content
   - Infer component organization from filenames
   - Build hierarchy using naming conventions

   **Note**: For v2 schema, `spec.toml` is required and must declare `schema_version = "2.0"`

2. **Generate registry** in CI:
   ```bash
   # In MODFLOW 6 repository CI
   python -m modflow_devtools.dfn.make_registry \
     --dfn-path doc/mf6io/mf6ivar/dfn \
     --output .registry/dfns.toml \
     --ref ${{ github.ref_name }}
   ```

3. **Commit registry** to `.registry/dfns.toml`

4. **Example CI integration** (GitHub Actions):
   ```yaml
   - name: Generate DFN registry
     run: |
       pip install modflow-devtools
       python -m modflow_devtools.dfn.make_registry \
         --dfn-path doc/mf6io/mf6ivar/dfn \
         --output .registry/dfns.toml \
         --ref ${{ github.ref_name }}

   - name: Commit registry
     run: |
       git config user.name "github-actions[bot]"
       git config user.email "github-actions[bot]@users.noreply.github.com"
       git add .registry/dfns.toml
       git diff-index --quiet HEAD || git commit -m "chore: update DFN registry"
       git push
   ```

**Note**: Initially generate registries for version-controlled mode. Release asset mode would require MODFLOW 6 to start distributing DFNs with releases.

### DFN addressing

**Format**: `mf6@{ref}/{component}`

Components include:
- `ref`: Git ref (branch, tag, or commit hash) corresponding to a MODFLOW 6 version
- `component`: DFN component name (without file extension)

Examples:
- `mf6@6.6.0/sim-nam` - Simulation name file definition for MODFLOW 6 v6.6.0
- `mf6@6.6.0/gwf-chd` - GWF CHD package definition for v6.6.0
- `mf6@develop/gwf-wel` - GWF WEL package definition from develop branch
- `mf6@f3df630a/gwt-adv` - GWT ADV package definition from specific commit

**Benefits**:
- Explicit versioning prevents confusion
- Supports multiple MODFLOW 6 versions simultaneously
- Enables comparison between versions
- Works with any git ref (not just releases)

**Note**: The source is always "mf6" (MODFLOW 6), but the addressing scheme allows for future sources if needed.

### Registry classes

#### DfnRegistry (abstract base)

Similar to `ModelRegistry` and `ProgramRegistry`, defines the contract:

```python
class DfnRegistry(ABC):
    @property
    @abstractmethod
    def spec(self) -> DfnSpec:
        """Get the full DFN specification."""
        pass

    @property
    @abstractmethod
    def ref(self) -> str:
        """Get the git ref for this registry."""
        pass

    def get_dfn(self, component: str) -> Dfn:
        """
        Get a parsed DFN for the specified component.
        Convenience method for spec[component].
        """
        return self.spec[component]

    @abstractmethod
    def get_dfn_path(self, component: str) -> Path:
        """Get the local path to a DFN file (fetching if needed)."""
        pass

    @property
    def schema_version(self) -> str:
        """Get the schema version. Convenience for spec.schema_version."""
        return self.spec.schema_version

    @property
    def components(self) -> dict[str, Dfn]:
        """Get all components. Convenience for dict(spec.items())."""
        return dict(self.spec.items())
```

#### RemoteDfnRegistry

Handles remote registry discovery, caching, and DFN fetching:

```python
class RemoteDfnRegistry(DfnRegistry):
    def __init__(self, source: str = "modflow6", ref: str = "develop"):
        self.source = source
        self._ref = ref
        self._spec = None
        self._registry_meta = None
        self._bootstrap_meta = None
        self._pooch = None
        self._cache_dir = None
        self._load()

    def _load(self):
        # Load bootstrap metadata for this source
        self._bootstrap_meta = self._load_bootstrap(self.source)

        # Check cache for registry
        if cached := self._load_from_cache():
            self._registry_meta = cached
        else:
            # Sync from remote
            self._sync()

        # Set up Pooch for file fetching
        self._setup_pooch()

        # Ensure all files are cached (lazy fetching on access)
        # Don't load spec until needed

    @property
    def spec(self) -> DfnSpec:
        """Lazy-load the DfnSpec from cached files."""
        if self._spec is None:
            # Ensure all DFN files are cached
            self._ensure_cached()
            # Load spec from cache directory
            self._spec = DfnSpec.load(self._cache_dir)
        return self._spec

    def _ensure_cached(self):
        """Ensure all DFN files are fetched and cached."""
        for filename in self._registry_meta["files"]:
            self._pooch.fetch(filename)

    def _setup_pooch(self):
        # Create Pooch instance with dynamically constructed URLs
        import pooch

        self._cache_dir = self._get_cache_dir()

        # Construct base URL from bootstrap metadata
        repo = self._bootstrap_meta["repo"]
        dfn_path = self._bootstrap_meta.get("dfn_path", "doc/mf6io/mf6ivar/dfn")
        base_url = f"https://raw.githubusercontent.com/{repo}/{self._ref}/{dfn_path}/"

        self._pooch = pooch.create(
            path=self._cache_dir,
            base_url=base_url,
            registry=self._registry_meta["files"],  # Just filename -> hash
        )

    def get_dfn_path(self, component: str) -> Path:
        # Use Pooch to fetch file (from cache or remote)
        # Pooch constructs full URL from base_url + filename
        filename = self._get_filename(component)
        return Path(self._pooch.fetch(filename))
```

**Benefits of dynamic URL construction**:
- Registry files are smaller and simpler
- Users can substitute personal forks by modifying bootstrap file
- Single source of truth for repository location
- URLs adapt automatically when repo/path changes

#### LocalDfnRegistry

For developers working with local DFN files:

```python
class LocalDfnRegistry(DfnRegistry):
    def __init__(self, path: str | PathLike, ref: str = "local"):
        self.path = Path(path).expanduser().resolve()
        self._ref = ref
        self._spec = None

    @property
    def spec(self) -> DfnSpec:
        """Lazy-load the DfnSpec from local directory."""
        if self._spec is None:
            self._spec = DfnSpec.load(self.path)
        return self._spec

    def get_dfn_path(self, component: str) -> Path:
        # Return local file path directly
        # Look for both .dfn and .toml extensions
        for ext in [".dfn", ".toml"]:
            p = self.path / f"{component}{ext}"
            if p.exists():
                return p
        raise ValueError(f"Component {component} not found in {self.path}")
```

### Module-level API

Convenient module-level functions:

```python
# Default registry for latest stable MODFLOW 6 version
from modflow_devtools.dfn import (
    DEFAULT_REGISTRY,
    DfnSpec,
    get_dfn,
    get_dfn_path,
    list_components,
    sync_dfns,
    get_registry,
    map,
)

# Get individual DFNs
dfn = get_dfn("gwf-chd")  # Uses DEFAULT_REGISTRY
dfn = get_dfn("gwf-chd", ref="6.5.0")  # Specific version

# Get file path
path = get_dfn_path("gwf-wel", ref="6.6.0")

# List available components
components = list_components(ref="6.6.0")

# Work with specific registry
registry = get_registry(ref="6.6.0")
gwf_nam = registry.get_dfn("gwf-nam")

# Load full specification - single canonical hierarchical representation
spec = DfnSpec.load("/path/to/dfns")  # Load from directory

# Hierarchical access
spec.schema_version  # "1.1"
spec.root  # Root Dfn (simulation component)
spec.root.children["gwf-nam"]  # Navigate hierarchy
spec.root.children["gwf-nam"].children["gwf-chd"]

# Flat dict-like access via Mapping protocol
gwf_chd = spec["gwf-chd"]  # Get component by name
for name, dfn in spec.items():  # Iterate all components
    print(name)
len(spec)  # Total number of components

# Access spec through registry (registry provides the spec)
registry = get_registry(ref="6.6.0")
spec = registry.spec  # Registry wraps a DfnSpec
gwf_chd = registry.spec["gwf-chd"]

# Map between schema versions
dfn_v1 = get_dfn("gwf-chd", ref="6.4.4")  # Older version in v1 schema
dfn_v2 = map(dfn_v1, schema_version="2")  # Convert to v2 schema
```

**`DfnSpec` class**:

The `DfnSpec` dataclass represents the full specification with a single canonical hierarchical representation:

```python
from collections.abc import Mapping
from dataclasses import dataclass

@dataclass
class DfnSpec(Mapping):
    """Full DFN specification with hierarchical structure and flat dict access."""

    schema_version: str
    root: Dfn  # Hierarchical canonical representation (simulation component)

    # Mapping protocol - provides flat dict-like access
    def __getitem__(self, name: str) -> Dfn:
        """Get component by name (flattened lookup)."""
        ...

    def __iter__(self):
        """Iterate over all component names."""
        ...

    def __len__(self):
        """Total number of components in the spec."""
        ...

    @classmethod
    def load(cls, path: Path | str) -> "DfnSpec":
        """
        Load specification from a directory of DFN files.

        The specification is always loaded as a hierarchical tree,
        with flat access available via the Mapping protocol.
        """
        ...
```

**Design benefits**:
- **Single canonical representation**: Hierarchical tree is the source of truth
- **Flat access when needed**: Mapping protocol provides dict-like interface
- **Simple, focused responsibility**: `DfnSpec` only knows how to load from a directory
- **Clean layering**: Registries built on top of `DfnSpec`, not intertwined
- **Clean semantics**: `DfnSpec` = full specification, `Dfn` = individual component
- **Pythonic**: Implements standard `Mapping` protocol

**Separation of concerns**:
- **`DfnSpec`**: Canonical representation of the full specification (foundation)
  - Loads from a directory of DFN files via `load()` classmethod
  - Hierarchical tree via `.root` property
  - Flat dict access via `Mapping` protocol
  - No knowledge of registries, caching, or remote sources
- **Registries**: Handle discovery, distribution, and caching (built on DfnSpec)
  - Fetch and cache DFN files from remote sources
  - Internally use `DfnSpec` to represent the loaded specification
  - Provide access via `.spec` property
  - `get_dfn(component)` → convenience for `spec[component]`
  - `get_dfn_path(component)` → returns cached file path

Backwards compatibility with existing `fetch_dfns()`:

```python
# Old API (still works for manual downloads)
from modflow_devtools.dfn import fetch_dfns
fetch_dfns("MODFLOW-ORG", "modflow6", "6.6.0", "/tmp/dfns")

# New API (preferred - uses registry and caching)
from modflow_devtools.dfn import sync_dfns, get_registry, DfnSpec
sync_dfns(ref="6.6.0")
registry = get_registry(ref="6.6.0")
spec = registry.spec  # Registry wraps a DfnSpec
```

## Schema Versioning

A key design consideration is properly handling schema evolution while separating file format from schema version.

### Separating format from schema

As discussed in [issue #259](https://github.com/MODFLOW-ORG/modflow-devtools/issues/259), **file format and schema version are orthogonal concerns**:

**File format** (serialization):
- `dfn` - Legacy DFN text format
- `toml` - Modern TOML format (or potentially YAML, see below)

The format is simply how the data is serialized to disk. Any schema version can be serialized in any supported format.

**Schema version** (structural specification):
- Defines what components exist and how they relate to each other
- Defines which variables each component contains
- Defines variable types, shapes, and constraints
- Separates structural specification from input format representation concerns

The schema describes the semantic structure and meaning of the specification, independent of how it's serialized.

**Key distinction**: The schema migration is about separating structural specification (components, relationships, variables, types) from input format representation. This is discussed in detail in [pyphoenix-project issue #246](https://github.com/modflowpy/pyphoenix-project/issues/246).

For example:
- **Input format issue** (v1): Period data defined as recarrays with artificial dimensions like `maxbound`
- **Structural reality** (v2): Each column is actually a variable living on (a subset of) the grid, using semantically meaningful dimensions

The v1 schema conflates:
- **Structural information**: Components, their relationships, and variables within each component
- **Format information**: How MF6 allows arrays to be provided, when keywords like `FILEIN`/`FILEOUT` are necessary

The v2 schema should treat these as **separate layers**, where consumers can selectively apply formatting details atop a canonical data model.

**Current state** (on dfn branch):
- The code supports loading both `dfn` and `toml` formats
- The `Dfn.load()` function accepts a `format` parameter
- Schema version is determined independently of file format
- V1→V1.1 and V1→V2 schema mapping is implemented

**Implications for DFNs API**:
- Registry metadata includes both `format` and `schema_version` fields
- Registries can have different formats at different refs (some refs: dfn, others: toml)
- The same schema version can be serialized in different formats
- Schema mapping happens after loading, independent of file format
- Users can request specific schema versions via `map()` function

### Schema evolution

**v1 schema** (original):
- Current MODFLOW 6 releases through 6.6.x
- Flat structure with `in_record`, `tagged`, `preserve_case`, etc. attributes
- Mixes structural specification with input format representation (recarray/maxbound issue)
- Can be serialized as `.dfn` (original) or `.toml`

**v1.1 schema** (intermediate - current mainline on dfn branch):
- Cleaned-up v1 with data normalization
- Removed unnecessary attributes (`in_record`, `tagged`, etc.)
- Structural improvements (period block arrays separated into individual variables)
- Better parent-child relationships inferred from naming conventions
- Can be serialized as `.dfn` or `.toml`
- **Recommendation from issue #259**: Use this as the mainline, not jump to v2

**v2 schema** (future - comprehensive redesign):
- For devtools 2.x / FloPy 4.x / eventually MF6
- **Requires explicit `spec.toml` file** - no inference for v2 (ensures clarity and correctness)
- **Complete separation of structural specification from input format concerns** (see [pyphoenix-project #246](https://github.com/modflowpy/pyphoenix-project/issues/246))
  - Structural layer: components, relationships, variables, data models
  - Format layer: how MF6 allows arrays to be provided, FILEIN/FILEOUT keywords, etc.
  - Consumers can selectively apply formatting details atop canonical data model
- **Explicit parent-child relationships in DFN files** (see Component Hierarchy section)
- Modern type system with proper array types and semantically meaningful dimensions
- Consolidated attribute representation (see Tentative v2 schema design)
- Likely serialized as TOML or YAML (with JSON-Schema validation via Pydantic)

**DFNs API strategy**:
- Support all schema versions via registry metadata
- Provide transparent schema mapping where needed
- Default to native schema version from registry
- Allow explicit schema version selection via API
- Maintain backwards compatibility during transitions

### Tentative v2 schema design

Based on feedback from mwtoews in [PR #229](https://github.com/MODFLOW-ORG/modflow-devtools/pull/229) and the structural/format separation discussed in [pyphoenix-project #246](https://github.com/modflowpy/pyphoenix-project/issues/246):

**Structural vs format separation**:
The v2 schema should cleanly separate:
- **Structural specification**: Component definitions, relationships, variable data models
  - Generated classes encode only structure and data models
  - Use semantically meaningful dimensions (grid dimensions, time periods)
- **Format specification**: How MF6 reads/writes the data (separate layer)
  - I/O layers exclusively handle input format concerns
  - FILEIN/FILEOUT keywords, array input methods, etc.

**Consolidated attributes**: Replace individual boolean fields with an `attrs` list:
```toml
# Instead of this (v1/v1.1):
optional = true
time_series = true
layered = false

# Use this (v2):
attrs = ["optional", "time_series"]
```

**Array syntax for shapes**: Use actual arrays instead of string representations:
```toml
# Instead of this (v1/v1.1):
shape = "(nper, nnodes)"

# Use this (v2):
shape = ["nper", "nnodes"]
```

**Format considerations**:
- **TOML vs YAML**: YAML's more forgiving whitespace better accommodates long descriptions (common for scientific parameters)
- **Validation approach**: Use Pydantic for both schema definition and validation
  - Pydantic provides rigorous validation (addresses pyphoenix-project #246 requirement for formal specification)
  - Built-in validation after parsing TOML/YAML to dict (no custom parsing logic)
  - Automatic JSON-Schema generation for documentation and external tooling
  - More Pythonic than using `python-jsonschema` directly

**Pydantic integration**:
```python
from pydantic import BaseModel, Field
from typing import Any

class FieldV2(BaseModel):
    name: str
    type: str
    block: str | None = None
    shape: list[str] | None = None
    attrs: list[str] = Field(default_factory=list)
    description: str = ""
    default: Any = None
    children: dict[str, "FieldV2"] | None = None

# Usage:
# 1. Parse TOML/YAML to dict (using tomli/pyyaml/etc)
# 2. Validate with Pydantic (built-in)
parsed = tomli.load(f)
field = FieldV2(**parsed)  # Validates automatically

# 3. Export JSON-Schema if needed (for docs, external tools)
schema = FieldV2.model_json_schema()
```

Benefits:
- **Validation and schema in one**: Pydantic handles both, no separate validation library needed
- **Type safety**: Full Python type hints and IDE support
- **JSON-Schema export**: Available for documentation and external tooling
- **Widely adopted**: Well-maintained, used throughout Python ecosystem
- **Better UX**: Clear error messages, better handling of multi-line descriptions (if using YAML)

## Component Hierarchy

**Design decision**: Component parent-child relationships should be defined **in the DFN files themselves**, not in the registry file.

The registry file's purpose is to tell devtools what it needs to know to consume the DFNs and make them available to users (file locations, hashes, basic organization). The DFN files are the single source of truth for the specification itself, including component relationships.

**v2 schema approach**:
```toml
# In gwf-chd.toml
name = "gwf-chd"
parent = "gwf-nam"
schema_version = "2.0"

[options]
# ... field definitions
```

Benefits:
- Single source of truth - specification is self-contained
- No risk of registry and DFN content getting out of sync
- Registry remains focused on discovery/distribution, not specification
- Hierarchy is intrinsic to the specification, not metadata about it

**Current state (v1/v1.1)**:
- Hierarchy is **implicit** in naming conventions: `gwf-dis` → parent is `gwf-nam`
- `to_tree()` function infers relationships from component names
- Works but fragile (relies on naming conventions being followed)

**Registry file role**:
- The registry's `[components]` section can still organize components by type (simulation, models, packages, exchanges, solutions) for easier discovery
- But parent-child relationships belong in the DFN files themselves
- Registry generation can validate that the inferred/explicit hierarchy is consistent

## Backwards Compatibility Strategy

Since FloPy 3 is already consuming the v1.1 schema and we need to develop v2 schema in parallel, careful planning is needed to avoid breaking existing consumers.

### Development approach

**Mainline (develop branch)**:
- Keep v1.1 schema stable on mainline
- Implement DFNs API with full v1/v1.1 support
- All v1.1 schema changes are **additive only** (no breaking changes)
- FloPy 3 continues consuming from mainline without disruption

**V2 development (dfn-v2 branch)**:
- Create separate `dfn-v2` branch for v2 schema development
- Develop v2 schema, Pydantic models, and structural/format separation
- Test v2 schema with experimental FloPy 4 development
- Iterate on v2 design without affecting mainline stability

**Integration approach**:
1. **Phase 1**: DFNs API on mainline supports v1/v1.1 only
2. **Phase 2**: Add v2 schema support to mainline (v1, v1.1, and v2 all supported)
3. **Phase 3**: Merge dfn-v2 branch, deprecate v1 (but keep it working)
4. **Phase 4**: Eventually remove v1 support in devtools 3.x (v1.1 and v2 only)

### Schema version support

The DFNs API will support **multiple schema versions simultaneously**:

```python
# Schema version is tracked per registry/ref
registry_v1 = get_registry(ref="6.4.4")  # MODFLOW 6.4.4 uses v1 schema
registry_v11 = get_registry(ref="6.6.0")  # MODFLOW 6.6.0 uses v1.1 schema
registry_v2 = get_registry(ref="develop")  # Future: develop uses v2 schema

# Get DFN in native schema version
dfn_v1 = registry_v1.get_dfn("gwf-chd")  # Returns v1 schema
dfn_v11 = registry_v11.get_dfn("gwf-chd")  # Returns v1.1 schema

# Transparently map to desired schema version
from modflow_devtools.dfn import map
dfn_v2 = map(dfn_v1, schema_version="2")  # v1 → v2
dfn_v2 = map(dfn_v11, schema_version="2")  # v1.1 → v2
```

**Registry support**:
- Each registry metadata includes `schema_version` (from `spec.toml` or inferred)
- Different refs can have different schema versions
- `RemoteDfnRegistry` loads appropriate schema version for each ref
- `load()` function detects schema version and uses appropriate parser/validator

**Schema detection**:
```python
# In RemoteDfnRegistry or DfnSpec.load()
def _detect_schema_version(self) -> Version:
    # 1. Check spec.toml if present
    if spec_file := self._load_spec_file():
        return spec_file.schema_version

    # 2. Infer from DFN content
    sample_dfn = self._load_sample_dfn()
    return infer_schema_version(sample_dfn)

    # 3. Default to latest stable
    return Version("1.1")
```

### API compatibility

**Backwards compatible API design**:

```python
# Existing dfn branch API (continue to work)
from modflow_devtools.dfn import load, fetch_dfns

# Works exactly as before
dfn = load("/path/to/dfn/file.dfn")
fetch_dfns("MODFLOW-ORG", "modflow6", "6.6.0", "/tmp/dfns")

# New DFNs API (additive, doesn't break existing)
from modflow_devtools.dfn import DfnSpec, get_dfn, get_registry, sync_dfns

# New functionality
sync_dfns(ref="6.6.0")
dfn = get_dfn("gwf-chd", ref="6.6.0")
registry = get_registry(ref="6.6.0")
spec = DfnSpec.load(registry)
```

**No breaking changes to existing classes**:
- `Dfn`, `Block`, `Field` dataclasses remain compatible
- `FieldV1`, `FieldV2` continue to work
- `MapV1To2` schema mapping continues to work
- Add `MapV1To11` and `MapV11To2` as needed
- `load()` function continues to work (loads individual DFN files)
- New `DfnSpec` class is additive (doesn't break existing code)

**Deprecation strategy**:
- Mark old APIs as deprecated with clear migration path
- Deprecation warnings point to new equivalent functionality
- Keep deprecated APIs working for at least one major version
- Document migration in release notes and migration guide

### Migration timeline

**devtools 1.x** (current):
- ✅ Merge dfn branch with v1.1 schema (stable, no breaking changes)
- ✅ Implement DFNs API with v1/v1.1 support
- ✅ FloPy 3 continues using v1.1 schema from mainline
- ✅ All existing APIs remain unchanged and supported
- ⚠️ Deprecate `fetch_dfns()` in favor of DFNs API (but keep working)

**devtools 2.0** (future):
- ✅ Add v2 schema support (v1, v1.1, and v2 all work)
- ✅ Merge dfn-v2 branch to mainline
- ✅ FloPy 4 begins using v2 schema
- ✅ FloPy 3 continues using v1.1 schema (no changes needed)
- ⚠️ Deprecate v1 schema support (but keep working for one more major version)

**devtools 3.0** (distant future):
- ✅ v1.1 and v2 schema both fully supported
- ❌ Remove v1 schema support (deprecated in 2.0)
- ⚠️ Final deprecation warnings for any legacy APIs

**Key principles**:
1. **Additive changes only** on mainline during 1.x
2. **Multi-version support** - DFNs API works with v1, v1.1, and v2 simultaneously
3. **No forced upgrades** - FloPy 3 never has to migrate off v1.1
4. **Explicit migration** - Users opt-in to v2 via schema mapping
5. **Long deprecation** - At least one major version warning before removal

**Testing strategy**:
- Test suite covers all schema versions (v1, v1.1, v2)
- Test schema mapping in all directions (v1↔v1.1↔v2)
- Test FloPy 3 integration continuously (don't break existing consumers)
- Test mixed-version scenarios (different refs with different schemas)

**Documentation**:
- Clear migration guides for each transition
- Document which MODFLOW 6 versions use which schema versions
- Examples showing multi-version usage
- Deprecation timeline clearly communicated

## Implementation Dependencies

### Existing work on dfn branch

The `dfn` branch already includes substantial infrastructure:

**Completed**:
- ✅ `Dfn`, `Block`, `Field` dataclasses
- ✅ Schema definitions (`FieldV1`, `FieldV2`)
- ✅ Parsers for both DFN and TOML formats
- ✅ Schema mapping (V1 → V2) with `MapV1To2`
- ✅ Flat/tree conversion utilities (`load_flat()`, `load_tree()`, `to_tree()`)
- ✅ `fetch_dfns()` function for manual downloads
- ✅ Validation utilities
- ✅ `dfn2toml` conversion tool

**Integration with `DfnSpec` design**:

The `dfn` branch currently has:
```python
# Returns dict[str, Dfn] - flat representation
dfns = load_flat("/path/to/dfns")

# Returns root Dfn with children - hierarchical representation
root = load_tree("/path/to/dfns")
```

The new `DfnSpec` class will consolidate these:
```python
# Single load, both representations available
spec = DfnSpec.load("/path/to/dfns")
spec.root  # Hierarchical (same as old load_tree)
spec["gwf-chd"]  # Flat dict access (same as old load_flat)
```

**Migration path**:
1. **Add `DfnSpec` class** - wraps existing `to_tree()` logic and implements `Mapping`
2. **Keep `load_flat()` and `load_tree()`** - mark as internal/deprecated but maintain for compatibility
3. **`DfnSpec.load()` implementation** - uses existing functions internally:
   ```python
   @classmethod
   def load(cls, path: Path | str) -> "DfnSpec":
       # Use existing load_flat for paths
       dfns = load_flat(path)

       # Use existing to_tree to build hierarchy
       root = to_tree(dfns)
       schema_version = root.schema_version  # or load from spec.toml
       return cls(schema_version=schema_version, root=root)
   ```
4. **Update registries** - make them wrap `DfnSpec`:
   ```python
   class RemoteDfnRegistry(DfnRegistry):
       @property
       def spec(self) -> DfnSpec:
           if self._spec is None:
               self._ensure_cached()  # Fetch all files
               self._spec = DfnSpec.load(self._cache_dir)  # Load from cache
           return self._spec
   ```
5. **Future**: Eventually remove `load_flat()` and `load_tree()` from public API

This approach:
- Reuses all existing parsing/conversion logic
- Provides cleaner API without breaking existing code
- Smooth transition: old functions work, new class preferred

**Note**: FloPy 3 is already generating code from an early version of this schema (per [pyphoenix-project #246](https://github.com/modflowpy/pyphoenix-project/issues/246)), which creates some stability requirements for the v1.1/v2 transition.

**Choreography with develop branch**:

Currently:
- **develop branch** has `modflow_devtools/dfn.py` (single file, basic utilities)
- **dfn branch** has `modflow_devtools/dfn/` (package with full implementation)
- **dfns-api branch** (current) just adds planning docs

Merge sequence:
1. **First**: Merge `dfns-api` branch → `develop` (adds planning docs)
2. **Then**: Merge `dfn` branch → `develop` (replaces `dfn.py` with `dfn/` package)
   - This replaces the single file with the package
   - Maintains API compatibility: `from modflow_devtools.dfn import ...` still works
   - Adds substantial new functionality (schema classes, parsers, etc.)
3. **Finally**: Implement DFNs API features on `develop` (registries, sync, CLI, `DfnSpec`)

API compatibility during merge:
```python
# Old dfn.py API (on develop now) - uses TypedDicts
from modflow_devtools.dfn import get_dfns, Field, Dfn

# New dfn/ package API (after dfn branch merge) - upgrades to dataclasses
from modflow_devtools.dfn import get_dfns  # Aliased to fetch_dfns, still works
from modflow_devtools.dfn import fetch_dfns  # New preferred name
from modflow_devtools.dfn import load, Dfn, Block, Field  # Upgraded to dataclasses
from modflow_devtools.dfn import DfnSpec, get_registry, sync_dfns  # New additions

# The import path stays the same, functionality expands
# get_dfns() kept as alias for backwards compatibility
```

Breaking changes (justified):
- `Field`, `Dfn`, etc. change from `TypedDict` to `dataclass` - more powerful, better typing
- This is acceptable since only internal dogfooding currently (FloPy uses schema, not these classes directly)

**Needed for DFNs API**:
- ❌ Bootstrap file and registry schema
- ❌ Registry discovery and synchronization
- ❌ Pooch integration for file caching
- ❌ Registry classes (`DfnRegistry`, `RemoteDfnRegistry`, `LocalDfnRegistry`)
- ❌ CLI commands (sync, info, list, clean)
- ❌ Module-level convenience API
- ❌ Registry generation tool (`make_registry.py`)
- ❌ Integration with MODFLOW 6 CI

### Core components

**Foundation** (no dependencies):
1. Merge dfn branch work (schema, parser, utility code)
2. Add bootstrap file (`modflow_devtools/dfn/bootstrap.toml`)
3. Define registry schema with Pydantic (handles validation and provides JSON-Schema export)
4. Implement registry discovery logic
5. Create cache directory structure utilities

**Registry infrastructure** (depends on Foundation):
1. Add Pooch as dependency
2. Implement `DfnRegistry` abstract base class
3. Implement `RemoteDfnRegistry` with Pooch for file fetching
4. Refactor existing code into `LocalDfnRegistry`
5. Implement `sync_dfns()` function
6. Add registry metadata caching with hash verification
7. Implement version-controlled registry discovery
8. Add auto-sync on first use (with opt-out via `MODFLOW_DEVTOOLS_NO_AUTO_SYNC`)
9. **Implement `DfnSpec` dataclass** with `Mapping` protocol for single canonical hierarchical representation with flat dict access

**CLI and module API** (depends on Registry infrastructure):
1. Create `modflow_devtools/dfn/__main__.py`
2. Add commands: `sync`, `info`, `list`, `clean`
3. Add `--ref` flag for version selection
4. Add `--force` flag for re-download
5. Add convenience functions (`get_dfn`, `get_dfn_path`, `list_components`, etc.)
6. Create `DEFAULT_REGISTRY` for latest stable version
7. Maintain backwards compatibility with `fetch_dfns()`

**Registry generation tool** (depends on Foundation):
1. Implement `modflow_devtools/dfn/make_registry.py`
2. Scan DFN directory and generate **registry file** (`dfns.toml`): file listings with hashes
3. Compute file hashes (SHA256) for all files (including `spec.toml` if present)
4. Registry output: just filename -> hash mapping (no URLs - constructed dynamically)
5. Support both full output (for CI) and minimal output (for handwriting)
6. **Do NOT generate `spec.toml`** - that's handwritten by MODFLOW 6 developers
7. Optionally validate `spec.toml` against DFN set for consistency if it exists
8. For v1/v1.1: infer hierarchy from naming conventions for validation
9. For v2: read explicit parent relationships from DFN files for validation

### MODFLOW 6 repository integration

**CI workflow** (depends on Registry generation tool):
1. Install modflow-devtools in MODFLOW 6 CI
2. Generate registry on push to develop and release tags
3. Commit registry to `.registry/dfns.toml`
4. Test registry discovery and sync
5. **Note**: `spec.toml` is handwritten by developers (optional), checked into repo like DFN files

**Bootstrap configuration** (depends on MODFLOW 6 CI):
1. Add stable MODFLOW 6 releases to bootstrap refs (6.6.0, 6.5.0, etc.)
2. Include `develop` branch for latest definitions
3. Test multi-ref discovery and sync

### Testing and documentation

**Testing** (depends on all core components):
1. Unit tests for registry classes
2. Integration tests for sync mechanism
3. Network failure scenarios
4. Multi-version scenarios
5. Schema mapping tests (v1 → v1.1 → v2)
6. Both file format tests (dfn and toml)
7. Backwards compatibility tests with existing FloPy usage

**Documentation** (can be done concurrently with implementation):
1. Update `docs/md/dfn.md` with API examples
2. Document format vs schema separation clearly
3. Document schema evolution roadmap (v1 → v1.1 → v2)
4. Document component hierarchy approach (explicit in DFN files for v2)
5. Add migration guide for existing code
6. CLI usage examples
7. MODFLOW 6 CI integration guide

## Relationship to Models and Programs APIs

The DFNs API deliberately mirrors the Models and Programs API architecture for consistency:

| Aspect | Models API | Programs API | **DFNs API** |
|--------|-----------|--------------|--------------|
| **Bootstrap file** | `models/bootstrap.toml` | `programs/bootstrap.toml` | `dfn/bootstrap.toml` |
| **Registry format** | TOML with files/models/examples | TOML with programs/binaries | TOML with files/components/hierarchy |
| **Discovery** | Release assets or version control | Release assets only | Version control (+ release assets future) |
| **Caching** | `~/.cache/.../models` | `~/.cache/.../programs` | `~/.cache/.../dfn` |
| **Addressing** | `source@ref/path/to/model` | `program@version` | `mf6@ref/component` |
| **CLI** | `models sync/info/list` | `programs sync/info/install` | `dfn sync/info/list/clean` |
| **Primary use** | Access model input files | Install program binaries | Parse definition files |

**Key differences**:
- DFNs API focuses on metadata/parsing, not installation
- DFNs API leverages existing parser infrastructure (Dfn, Block, Field classes)
- DFNs API handles schema versioning/mapping (format vs schema separation)
- DFNs API supports both flat and hierarchical representations

**Shared patterns**:
- Bootstrap-driven discovery
- Remote sync with Pooch caching
- Ref-based versioning (branches, tags, commits)
- CLI command structure
- Lazy loading / auto-sync on first use
- Environment variable opt-out for auto-sync

This consistency benefits both developers and users with a familiar experience across all three APIs.

## Design Decisions

### Use Pooch for fetching

Following the recommendation in [issue #262](https://github.com/MODFLOW-ORG/modflow-devtools/issues/262), the DFNs API will use Pooch for fetching to avoid maintaining custom HTTP client code. This provides:

- **Automatic caching**: Pooch handles local caching with verification
- **Hash verification**: Ensures file integrity
- **Progress bars**: Better user experience for downloads
- **Well-tested**: Pooch is mature and widely used
- **Consistency**: Same approach as Models API

### Use Pydantic for schema validation

Pydantic will be used for defining and validating DFN schemas (both registry schemas and DFN content schemas):

- **Built-in validation**: No need for separate validation libraries like `python-jsonschema`
- **Type safety**: Full Python type hints and IDE support
- **JSON-Schema export**: Can generate JSON-Schema for documentation and external tooling
- **Developer experience**: Clear error messages, good Python integration
- **Justification**: Widely adopted, well-maintained, addresses the formal specification requirement from [pyphoenix-project #246](https://github.com/modflowpy/pyphoenix-project/issues/246)

### Schema versioning strategy

Based on [issue #259](https://github.com/MODFLOW-ORG/modflow-devtools/issues/259):

- **Separate format from schema**: Registry metadata includes both
- **Support v1.1 as mainline**: Don't jump straight to v2
- **Backwards compatible**: Continue supporting v1 for existing MODFLOW 6 releases
- **Schema mapping**: Provide transparent conversion via `map()` function
- **Future-proof**: Design allows for v2 when ready (devtools 2.x / FloPy 4.x)

### Future enhancements

1. **Release asset mode**: Add support for registries as release assets (in addition to version control)
2. **Registry compression**: Compress registry files for faster downloads
3. **Partial updates**: Diff-based registry synchronization
4. **Offline mode**: Explicit offline mode that never attempts sync
5. **Conda integration**: Coordinate with conda-forge for bundled DFN packages
6. **Multi-source support**: Support definition files from sources other than MODFLOW 6
7. **Validation API**: Expose validation functionality for user-provided input files
8. **Diff/compare API**: Compare DFNs across versions to identify changes
