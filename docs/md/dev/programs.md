# Programs API Design

This document describes the design of the Programs API ([GitHub issue #263](https://github.com/MODFLOW-ORG/modflow-devtools/issues/263)). It is intended to be developer-facing, not user-facing, though users may also find it informative.

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
  - [Registry files](#registry-files)
    - [Registry file format](#registry-file-format)
    - [Sample registry file](#sample-registry-file)
  - [Registry discovery](#registry-discovery)
    - [Registry as release asset](#registry-as-release-asset)
    - [Registry discovery procedure](#registry-discovery-procedure)
  - [Registry/program metadata caching](#registryprogram-metadata-caching)
  - [Registry synchronization](#registry-synchronization)
    - [Manual sync](#manual-sync)
    - [Automatic sync](#automatic-sync)
  - [Program installation](#program-installation)
  - [Source program integration](#source-program-integration)
  - [Program addressing](#program-addressing)
  - [Registry classes](#registry-classes)
  - [Module-level API](#module-level-api)
- [Migration path](#migration-path)
  - [Transitioning from pymake](#transitioning-from-pymake)
  - [Implementation plan](#implementation-plan)
    - [Phase 1: Foundation (v2.x)](#phase-1-foundation-v2x)
    - [Phase 2: Registry & Discovery (v2.x)](#phase-2-registry--discovery-v2x)
    - [Phase 3: Installation System (v2.x)](#phase-3-installation-system-v2x)
    - [Phase 4: Upstream Integration (concurrent)](#phase-4-upstream-integration-concurrent)
    - [Phase 5: Testing & Documentation (v2.x)](#phase-5-testing--documentation-v2x)
    - [Phase 6: Deprecate pymake (v3.x)](#phase-6-deprecate-pymake-v3x)
- [Relationship to Models API](#relationship-to-models-api)
- [Open Questions / Future Enhancements](#open-questions--future-enhancements)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Background

Currently, program information is maintained in `pymake`, which serves dual purposes: (1) maintaining a database of program metadata (download URLs, versions, build configuration), and (2) providing build capabilities. This tight coupling means pymake must be updated whenever any program is released, creating a maintenance bottleneck.

The existing `modflow_devtools.programs` module provides a minimal read-only interface to a static CSV database (`programs.csv`) containing metadata for MODFLOW-family programs. This database includes information like:
- Program target name
- Version
- Download URL
- Build metadata (for legacy source building)

This approach has several limitations:
1. **Static coupling**: Every program update requires a new devtools release
2. **pymake dependency**: Program metadata is duplicated between pymake and devtools
3. **No introspection**: Limited ability to query available versions or builds
4. **Manual maintenance**: Developers must manually update the CSV file
5. **No installation support**: The API only provides metadata, not installation capabilities

## Objective

Create a Programs API that:
1. **Decouples** program releases from devtools releases
2. **Enables** individual programs to maintain their own metadata in their repositories
3. **Provides** discovery and synchronization of program metadata from remote sources
4. **Supports** installation and management of pre-built program binaries
5. **Facilitates** the eventual retirement of pymake by consolidating program database responsibilities in devtools
6. **Mirrors** the architectural patterns established by the Models API for consistency

## Motivation

- **Decouple releases**: Allow programs to evolve independently of devtools
- **Reduce maintenance burden**: Eliminate manual CSV updates and registry regeneration
- **Improve user experience**: Provide access to latest program releases without waiting for devtools updates
- **Enable pymake retirement**: Consolidate program metadata in devtools, eliminating the need for pymake's program database
- **Provide installation capabilities**: Extend beyond metadata to actual program installation and management
- **Consistency**: Align with Models API patterns for familiar developer and user experience

## Overview

Make program repositories responsible for publishing their own program metadata.

Make `modflow-devtools` responsible for:
- Defining the program registry publication contract
- Providing registry-creation machinery
- Storing bootstrap information locating program repositories
- Discovering remote registries at install time or on demand
- Caching registry metadata locally
- Exposing a synchronized view of available programs
- Installing pre-built program binaries

Program repository developers can publish program metadata as release assets or in special branches, either manually or in CI.

## Architecture

The Programs API will mirror the Models API architecture with adaptations for program-specific concerns like platform-specific binary distributions.

### Bootstrap file

The **bootstrap** file tells `modflow-devtools` where to look for program registries. This file will be checked into the repository at `modflow_devtools/programs/bootstrap.toml` and distributed with the package.

#### Bootstrap file contents

At the top level, the bootstrap file consists of a table of `sources`, each describing a program repository or collection.

Each source has:
- `repo`: Repository identifier (owner/name)
- `refs`: List of release tags to sync by default

#### Sample bootstrap file

```toml
[sources.modflow6]
repo = "MODFLOW-ORG/modflow6"
refs = ["6.6.3"]
# Provides mf6, zbud6, mf5to6, libmf6

[sources.modpath7]
repo = "MODFLOW-ORG/modpath7"
refs = ["7.2.001"]

[sources.mt3d-usgs]
repo = "MODFLOW-ORG/mt3d-usgs"
refs = ["1.1.0"]

[sources.executables]
repo = "MODFLOW-ORG/executables"
refs = ["latest"]
# Consolidated repo for legacy programs (mf2005, mfnwt, etc.)
```

**Note**: The bootstrap file can reference both individual program repositories (e.g., `modflow6` providing mf6, zbud6, mf5to6) and consolidated repositories that provide multiple unrelated programs. The source names in the bootstrap file are internal - users just use program names when installing.

### Registry files

Program registries describe available program builds and metadata needed for installation.

#### Registry file format

A consolidated `registry.toml` file with the following structure:

```toml
# Metadata
generated_at = "2025-12-29T10:30:00Z"
devtools_version = "2.0.0"
schema_version = "1.0"

# Program definitions
[programs.mf6]
version = "6.6.3"
description = "MODFLOW 6 groundwater flow model"
repo = "MODFLOW-ORG/modflow6"
license = "CC0-1.0"

# Binary distributions (platform-specific)
[programs.mf6.binaries.linux]
url = "https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/mf6.6.3_linux.zip"
hash = "sha256:..."
executables = ["bin/mf6"]

[programs.mf6.binaries.darwin]
url = "https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/mf6.6.3_mac.zip"
hash = "sha256:..."
executables = ["bin/mf6"]

[programs.mf6.binaries.win32]
url = "https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/mf6.6.3_win64.zip"
hash = "sha256:..."
executables = ["bin/mf6.exe"]

# Additional programs in same registry
[programs.zbud6]
version = "6.6.3"
description = "MODFLOW 6 Zonebudget utility"
repo = "MODFLOW-ORG/modflow6"
license = "CC0-1.0"

[programs.zbud6.binaries.linux]
url = "https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/mf6.6.3_linux.zip"
hash = "sha256:..."
executables = ["bin/zbud6"]
```

**Platform identifiers**: Use `sys.platform` values: `linux`, `darwin`, `win32`

#### Sample registry file

For a legacy program repository that consolidates multiple programs:

```toml
generated_at = "2025-12-29T10:30:00Z"
devtools_version = "2.0.0"
schema_version = "1.0"

[programs.mf2005]
version = "1.12.00"
description = "MODFLOW-2005"
repo = "MODFLOW-ORG/mf2005"
license = "CC0-1.0"

[programs.mf2005.binaries.linux]
url = "https://github.com/MODFLOW-ORG/mf2005/releases/download/v.1.12.00/MF2005.1_12u_linux.zip"
hash = "sha256:..."
executables = ["bin/mf2005"]
```

### Registry discovery

Program registries are published as GitHub release assets alongside binary distributions.

#### Registry as release asset

Registry files are published as release assets named `registry.toml`. This couples the registry metadata directly with the binary distributions.

Registry discovery URL pattern:
```
https://github.com/{org}/{repo}/releases/download/{tag}/registry.toml
```

Examples:
```
https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/registry.toml
https://github.com/MODFLOW-ORG/modpath7/releases/download/7.2.001/registry.toml
```

Benefits:
- Strongly couples registry with released binaries
- No version control overhead for registry files
- Natural alignment with binary distribution workflow
- Generated automatically in release CI
- Users always get metadata for released, tested binaries

#### Registry discovery procedure

At sync time, `modflow-devtools` discovers remote registries for each configured source and release tag:

1. **Check for release tag**: Look for a GitHub release with the specified tag
2. **Fetch registry asset**: Download `registry.toml` from the release assets
3. **Failure cases**:
   - If release tag doesn't exist:
     ```python
     RegistryDiscoveryError(
         f"Release tag '{tag}' not found for {repo}"
     )
     ```
   - If release exists but lacks `registry.toml` asset:
     ```python
     RegistryDiscoveryError(
         f"Registry file 'registry.toml' not found as release asset "
         f"for {repo}@{tag}"
     )
     ```

### Registry/program metadata caching

Cache structure:

```
~/.cache/modflow-devtools/
├── programs/
│   ├── registries/
│   │   ├── modflow6/              # by source repo
│   │   │   └── 6.6.3/
│   │   │       └── registry.toml
│   │   ├── modpath7/
│   │   │   └── 7.2.001/
│   │   │       └── registry.toml
│   │   └── executables/
│   │       └── latest/
│   │           └── registry.toml
│   └── binaries/
│       ├── mf6/                    # by program name
│       │   └── 6.6.3/
│       │       └── linux/
│       │           ├── bin/
│       │           │   └── mf6
│       │           └── .metadata
│       ├── zbud6/
│       │   └── 6.6.3/
│       │       └── linux/
│       │           └── ...
│       └── mp7/
│           └── 7.2.001/
│               └── ...
```

**Cache management**:
- Registry files are cached per source repository and release tag
- Binary distributions are cached per program name, version, and platform
- Cache can be cleared with `programs clean` command
- Users can list cached programs with `programs list --cached`

### Registry synchronization

Synchronization updates the local registry cache with remote program metadata.

#### Manual sync

Exposed as a CLI command and Python API:

```bash
# Sync all configured sources and release tags
python -m modflow_devtools.programs sync

# Sync specific source to specific release tag
python -m modflow_devtools.programs sync --repo MODFLOW-ORG/modflow6 --tag 6.6.3

# Force re-download
python -m modflow_devtools.programs sync --force

# Show sync status
python -m modflow_devtools.programs info

# List available programs
python -m modflow_devtools.programs list
```

Or via Python API:

```python
from modflow_devtools.programs import sync_registries, get_sync_status

# Sync all
sync_registries()

# Sync specific
sync_registries(repo="MODFLOW-ORG/modflow6", tag="6.6.3")

# Check status
status = get_sync_status()
```

#### Automatic sync

- **At install time**: Best-effort sync during package installation (fail silently on network errors)
- **On first use**: If registry cache is empty, attempt to sync before raising errors
- **Configurable**: Users can disable auto-sync via environment variable: `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`

### Program installation

Installation extends beyond metadata to actually providing program executables by downloading and managing pre-built platform-specific binaries.

```bash
# Install from binary (auto-detects platform)
python -m modflow_devtools.programs install mf6

# Install specific version
python -m modflow_devtools.programs install mf6@6.6.3

# Install related programs from same release
python -m modflow_devtools.programs install zbud6@6.6.3

# List installed programs
python -m modflow_devtools.programs list --installed

# Uninstall
python -m modflow_devtools.programs uninstall mf6
```

Python API:

```python
from modflow_devtools.programs import install_program, list_installed

# Install
install_program("mf6", version="6.6.3", platform="linux")

# Get executable path
import modflow_devtools.programs as programs
mf6_path = programs.get_executable("mf6")
```

**Installation process**:
1. Resolve program name to registry entry
2. Detect platform (or use specified platform)
3. Check if binary distribution available for platform
4. Download and extract binary distribution to cache
5. Make executables executable (chmod +x on Unix)
6. Return paths to installed executables

**Note**: Programs are expected to publish pre-built binaries for all supported platforms. Building from source is not supported - program repositories are responsible for releasing platform-specific binaries.

### Source program integration

For program repositories to integrate:

1. **Generate registry metadata**:
   ```bash
   # In program repository
   python -m modflow_devtools.make_program_registry \
     --version 6.6.3 \
     --platforms linux darwin win32 \
     --binary-url "https://github.com/MODFLOW-ORG/modflow6/releases/download/{version}/mf6.{version}_{platform}.zip" \
     --output .registry/registry.toml
   ```

2. **Publish registry**: Attach `registry.toml` as a release asset

3. **Example CI integration** (GitHub Actions):
   ```yaml
   - name: Generate program registry
     run: |
       python -m modflow_devtools.make_program_registry \
         --version ${{ github.ref_name }} \
         --platforms linux darwin win32 \
         --output registry.toml

   - name: Upload registry to release
     uses: actions/upload-release-asset@v1
     with:
       asset_path: registry.toml
       asset_name: registry.toml
   ```

### Program addressing

**Format**: `{program}@{version}`

Examples:
- `mf6@6.6.3` - MODFLOW 6 version 6.6.3
- `zbud6@6.6.3` - MODFLOW 6 Zonebudget version 6.6.3
- `mf5to6@6.6.3` - MODFLOW 5 to 6 converter version 6.6.3
- `mp7@7.2.001` - MODPATH 7 version 7.2.001
- `mf2005@1.12.00` - MODFLOW-2005 version 1.12.00

**Benefits**:
- Simple, intuitive addressing
- Explicit versioning
- Prevents version conflicts
- Enables side-by-side installations

**Note**: Program names are assumed to be globally unique across all sources. The source repository is an implementation detail of registry discovery - users just need to know the program name and version. All versions correspond to GitHub release tags.

### Registry classes

#### ProgramRegistry (abstract base)

Similar to `ModelRegistry`, defines the contract:

```python
class ProgramRegistry(ABC):
    @property
    @abstractmethod
    def programs(self) -> dict[str, Program]:
        """Get all programs in registry."""
        pass

    @abstractmethod
    def get_program(self, name: str) -> Program:
        """Get a specific program."""
        pass

    @abstractmethod
    def install(self, name: str, **kwargs) -> Path:
        """Install a program and return executable path."""
        pass
```

#### RemoteRegistry

Handles remote registry discovery and caching:

```python
class RemoteRegistry(ProgramRegistry):
    def __init__(self, source: str, ref: str):
        self.source = source
        self.ref = ref
        self._load()

    def _load(self):
        # Check cache first
        if cached := self._load_from_cache():
            return cached
        # Otherwise sync from remote
        self._sync()
```

#### MergedRegistry

Compositor for multiple registries:

```python
class MergedRegistry(ProgramRegistry):
    def __init__(self, registries: list[ProgramRegistry]):
        self.registries = registries

    @property
    def programs(self) -> dict[str, Program]:
        # Merge programs from all registries
        # Later registries override earlier ones
        merged = {}
        for registry in self.registries:
            merged.update(registry.programs)
        return merged
```

#### LocalRegistry

For development/testing with local program metadata:

```python
class LocalRegistry(ProgramRegistry):
    def __init__(self, path: Path):
        self.path = path
        self._load()
```

### Module-level API

Convenient module-level functions:

```python
# Default merged registry from bootstrap config
from modflow_devtools.programs import (
    DEFAULT_REGISTRY,
    get_programs,
    get_program,
    install_program,
    list_installed,
    sync_registries,
    get_executable,
)

# Usage
programs = get_programs()
mf6 = get_program("mf6", version="6.6.3")
install_program("mf6", version="6.6.3")
exe_path = get_executable("mf6")
```

Backwards compatibility with existing API:

```python
# Old API (still works, uses bundled CSV)
from modflow_devtools.programs import PROGRAMS, get_program

# New API
from modflow_devtools.programs import get_programs, get_program

programs = get_programs()  # dict[str, Program]
mf6 = get_program("mf6")   # Program instance
```

## Migration path

### Transitioning from pymake

Since programs will publish pre-built binaries, pymake is no longer needed for building or for maintaining the program database:

1. **Phase 1**: Programs API provides read-only access to program metadata
2. **Phase 2**: Add installation capabilities, users can install programs via devtools
3. **Phase 3**: Program repositories begin publishing their own registries with pre-built binaries
4. **Phase 4**: devtools becomes the authoritative source for program metadata
5. **Phase 5**: pymake deprecated entirely (no longer needed)

### Implementation plan

#### Phase 1: Foundation (v2.x)

1. Create bootstrap file (`modflow_devtools/programs/bootstrap.toml`)
2. Define registry schema with Pydantic validation (`modflow_devtools/programs/schema.py`)
3. Implement cache directory utilities (`modflow_devtools/programs/cache.py`)
4. Add release asset discovery logic (`modflow_devtools/programs/discovery.py`)
5. Implement sync functionality (`modflow_devtools/programs/sync.py`)
6. Create CLI commands (`modflow_devtools/programs/__main__.py` - sync, info, list)

**Deliverables**:
- Bootstrap file defining initial sources (release tags only)
- Registry schema validation
- Release asset discovery mechanism
- Sync mechanism with caching
- CLI for manual sync and introspection

#### Phase 2: Registry & Discovery (v2.x)

1. Implement `ProgramRegistry` abstract base class
2. Create `RemoteRegistry` for remote discovery and caching
3. Implement `MergedRegistry` compositor
4. Add `LocalRegistry` for development
5. Update module-level API to use registries
6. Add registry generation utilities (`make_program_registry.py`)

**Deliverables**:
- Registry class hierarchy
- Remote discovery working
- Module API using new registries
- Fallback to bundled CSV for backwards compatibility

#### Phase 3: Installation System (v2.x)

1. Implement binary distribution download and extraction
2. Add platform detection and binary selection
3. Create installation management (install/uninstall/list)
4. Add `get_executable()` function
5. Handle executable permissions on Unix systems
6. Add verification/validation of downloaded binaries

**Deliverables**:
- `install` CLI command
- Binary installation working for all programs
- Executable path resolution
- Platform detection and appropriate binary selection

#### Phase 4: Upstream Integration (concurrent)

1. Add registry generation to modflow6 CI
2. Publish registries as release assets
3. Test discovery and installation
4. Document registry publication workflow
5. Gradually migrate other programs

**Deliverables**:
- modflow6 publishing registries
- Other programs beginning to publish
- Documentation for program maintainers

#### Phase 5: Testing & Documentation (v2.x)

1. Comprehensive test suite for sync mechanism
2. Test network failure scenarios
3. Test multi-platform installation
4. Test registry merging and precedence
5. Document new workflow in `programs.md`
6. Create migration guide for pymake users

**Deliverables**:
- Full test coverage
- User documentation
- Migration guides
- Examples

#### Phase 6: Deprecate pymake (v3.x)

1. Remove bundled CSV file
2. Make sync required (no fallback)
3. Deprecate pymake for metadata
4. Update documentation
5. Release notes with clear migration path

**Deliverables**:
- devtools is authoritative for program metadata and installation
- pymake fully deprecated
- Clear communication to users about migration

## Relationship to Models API

The Programs API deliberately mirrors the Models API architecture:

| Aspect | Models API | Programs API |
|--------|-----------|--------------|
| **Bootstrap file** | `models/bootstrap.toml` | `programs/bootstrap.toml` |
| **Registry format** | TOML with files/models/examples | TOML with programs/binaries |
| **Discovery** | Release assets or version control | Release assets only |
| **Caching** | `~/.cache/modflow-devtools/models` | `~/.cache/modflow-devtools/programs` |
| **Addressing** | `source@ref/path/to/model` | `program@version` |
| **CLI** | `models sync/info/list` | `programs sync/info/list/install` |
| **Registries** | `PoochRegistry`, `MergedRegistry` | `RemoteRegistry`, `MergedRegistry` |

**Key differences**:
- Programs API adds installation capabilities (Models API just provides file access)
- Programs API handles platform-specific binaries (no building from source)
- Programs have simpler addressing (just `program@version`, no source or path components)
- Programs only use release asset discovery (no version-controlled registries)

**Shared patterns**:
- Bootstrap-driven discovery
- Remote sync with caching
- Registry merging and composition
- CLI command structure
- Fallback to bundled data during migration

This consistency benefits both developers and users with a familiar experience across both APIs.

## Open Questions / Future Enhancements

1. **Platform detection**: Should we support cross-platform installations (e.g., install Windows binaries on Linux for testing)?

2. **Executable discovery**: Should we provide a `which` command to locate installed executables?

3. **Version resolution**: Should we support semantic version ranges (e.g., `mf6@^6.6`)?

4. **Dependency handling**: If programs depend on each other (e.g., utilities requiring main programs), should we model dependencies?

5. **Update notifications**: Should we notify users when newer versions are available?

6. **Multiple versions**: Should users be able to install multiple versions side-by-side?

7. **Aliases**: Should we support aliasing (e.g., `mf6-latest` → `mf6@6.6.3`)? Or special version identifiers like `mf6@latest`, `mf6@stable`?

8. **Verification**: Should we verify signatures or checksums on binary distributions for security?

9. **Mirrors**: Should we support mirror URLs for binary distributions (for reliability/speed)?

10. **Integration with flopy**: How does this relate to flopy's `get-modflow`? Should they share code or remain separate?

11. **Fallback platforms**: If a platform-specific binary isn't available, should we provide helpful error messages about which platforms are supported?

12. **PATH management**: Should we provide utilities to add installed programs to PATH, or leave that to users?
