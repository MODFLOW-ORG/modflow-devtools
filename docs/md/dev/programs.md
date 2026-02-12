# Programs API Design

This document describes the design of the Programs API ([GitHub issue #263](https://github.com/MODFLOW-ORG/modflow-devtools/issues/263)). It is intended to be developer-facing, not user-facing, though users may also find it informative.

This is a living document which will be updated as development proceeds.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->


- [Background](#background)
- [Objective](#objective)
- [Overview](#overview)
- [Architecture](#architecture)
  - [Bootstrap file](#bootstrap-file)
    - [Bootstrap file contents](#bootstrap-file-contents)
    - [Sample bootstrap file](#sample-bootstrap-file)
  - [Registry files](#registry-files)
    - [Registry file format](#registry-file-format)
    - [Registries vs. installation metadata](#registries-vs-installation-metadata)
  - [Registry discovery](#registry-discovery)
    - [Registry discovery procedure](#registry-discovery-procedure)
  - [Registry/program metadata caching](#registryprogram-metadata-caching)
  - [Registry synchronization](#registry-synchronization)
    - [Manual sync](#manual-sync)
    - [Automatic sync](#automatic-sync)
    - [Force semantics](#force-semantics)
  - [Program installation](#program-installation)
  - [Source program integration](#source-program-integration)
  - [Program addressing](#program-addressing)
  - [Registry classes](#registry-classes)
    - [ProgramBinary](#programbinary)
    - [ProgramMetadata](#programmetadata)
    - [ProgramRegistry](#programregistry)
    - [ProgramCache](#programcache)
    - [ProgramSourceRepo](#programsourcerepo)
    - [ProgramSourceConfig](#programsourceconfig)
    - [ProgramInstallation](#programinstallation)
    - [InstallationMetadata](#installationmetadata)
    - [ProgramManager](#programmanager)
  - [Python API](#python-api)
- [Migration path](#migration-path)
  - [Transitioning from pymake](#transitioning-from-pymake)
  - [Implementation Summary](#implementation-summary)
- [Relationship to Models API](#relationship-to-models-api)
- [Relationship to get-modflow](#relationship-to-get-modflow)
  - [Reusable patterns from get-modflow](#reusable-patterns-from-get-modflow)
    - [1. Platform detection](#1-platform-detection)
    - [2. Installation metadata tracking](#2-installation-metadata-tracking)
    - [3. Bindir selection and writable directory discovery](#3-bindir-selection-and-writable-directory-discovery)
    - [4. Executable extraction and installation](#4-executable-extraction-and-installation)
    - [5. GitHub API interactions](#5-github-api-interactions)
    - [6. Archive caching](#6-archive-caching)
  - [Key enhancements over get-modflow](#key-enhancements-over-get-modflow)
  - [Migration path](#migration-path-1)
- [Design Decisions](#design-decisions)
  - [Initial implementation](#initial-implementation)
  - [Explicitly out of scope](#explicitly-out-of-scope)
  - [Future enhancements](#future-enhancements)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Background

Currently, program information is maintained in `pymake`, which serves dual purposes: (1) maintaining a database of program metadata (download URLs, versions, build configuration), and (2) providing build capabilities. The latter is pymake's explicit responsibility, the former accidental and located in pymake just for convenience.

Some preliminary work has begun to transfer program metadata responsibilities to `modflow-devtools`. The existing `modflow_devtools.programs` module provides a minimal read-only interface to a database (`programs.csv`) copied more or less directly from the pymake database, including information like each program's:

- name
- version
- source code download URL
- build information (e.g. double precision)

This approach has several limitations:

1. **Static coupling**: Pymake (or any other project containing such a program database, like `modflow-devtools`) must be updated whenever any program is released, creating a maintenance bottleneck.

2. **No introspection**: Limited ability to query available program versions or builds

3. **Manual maintenance**: Developers must manually update the CSV file

4. **No install support**: The API only provides metadata, not installation capabilities

## Objective

Create a Programs API that:

1. Decouples program releases from devtools releases
3. Discovers and synchronizes program metadata from remote sources
4. Supports installation and management of program binaries
5. Facilitates the eventual retirement of pymake by consolidating program database responsibilities in devtools
6. Mirrors Models API and DFNs API architecture/UX for consistency

## Overview

Make MODFLOW ecosystem repositories responsible for publishing their own metadata.

Make `modflow-devtools` responsible for:
- Defining the program registry publication contract
- Providing registry-creation machinery
- Storing bootstrap information locating program repositories
- Discovering remote registries at install time or on demand
- Caching registry metadata locally
- Exposing a synchronized view of available programs
- Installing program binaries

Program maintainers can publish registries as release assets, either manually or in CI.

## Architecture

The Programs API mirrors the Models API architecture with adaptations for program-specific concerns like platform-specific binary distributions.

### Bootstrap file

The **bootstrap** file tells `modflow-devtools` where to look for programs. This file will be checked into the repository at `modflow_devtools/programs/programs.toml` and distributed with the package.

#### Bootstrap file contents

At the top level, the bootstrap file consists of a table of `sources`, each describing a repository distributing one or more programs.

Each source entry has:
- `repo`: Repository identifier (owner/name)
- `refs`: List of release tags to sync by default

#### User config overlay

Users can customize or extend the bundled bootstrap configuration by creating a user config file at:
- Linux/macOS: `~/.config/modflow-devtools/programs.toml` (respects `$XDG_CONFIG_HOME`)
- Windows: `%APPDATA%/modflow-devtools/programs.toml`

The user config follows the same format as the bundled bootstrap file. Sources defined in the user config will override or extend those in the bundled config, allowing users to:
- Add custom program repositories
- Point to forks of existing repositories (useful for testing)
- Override default refs for existing sources

**Implementation note**: The user config path logic (`get_user_config_path("programs")`) is shared across all three APIs (Models, Programs, DFNs) via `modflow_devtools.config`, but each API implements its own `merge_bootstrap()` function using API-specific bootstrap schemas.

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
# Consolidated repo for legacy programs (mf2005, mfnwt, etc).
# TODO: replace with separate repos as they become available.
```

**Note**: A source repository described in the bootstrap file may provide a single program or multiple programs. E.g., the `modflow6` repository provides `mf6`, `zbud6`, and `mf5to6`).

### Registry files

Each source repository must make a **program registry** file available. Program registries describe available programs and metadata needed for installation.

#### Registry file format

Registry files shall be named **`programs.toml`** (not `registry.toml` - the specific naming distinguishes it from the Models and DFNs registries) and contain, at minimum, a dictionary `programs` enumerating programs provided by the source repository. For instance:

```toml
schema_version = "1.0"

# Example 1: Distribution-specific exe paths (when archive structures differ)
[programs.mf6]
description = "MODFLOW 6 groundwater flow model"
license = "CC0-1.0"

[[programs.mf6.dists]]
name = "linux"
asset = "mf6.7.0_linux.zip"
exe = "mf6.7.0_linux/bin/mf6"       # Each platform has different top-level dir
hash = "sha256:..."

[[programs.mf6.dists]]
name = "mac"
asset = "mf6.7.0_mac.zip"
exe = "mf6.7.0_mac/bin/mf6"
hash = "sha256:..."

[[programs.mf6.dists]]
name = "win64"
asset = "mf6.7.0_win64.zip"
exe = "mf6.7.0_win64/bin/mf6.exe"   # Note: .exe extension required
hash = "sha256:..."

# Example 2: Program-level exe path (when all platforms share same structure)
[programs.mfnwt]
exe = "bin/mfnwt"  # Same relative path for all platforms (.exe auto-added on Windows)
description = "MODFLOW-NWT with Newton formulation"
license = "CC0-1.0"

[[programs.mfnwt.dists]]
name = "linux"
asset = "linux.zip"     # Contains bin/mfnwt
hash = "sha256:..."

[[programs.mfnwt.dists]]
name = "win64"
asset = "win64.zip"     # Contains bin/mfnwt.exe (extension auto-added)
hash = "sha256:..."

# Example 3: Default exe path (when executable is at bin/{program})
[programs.zbud6]
# No exe specified - defaults to "bin/zbud6" (or "bin/zbud6.exe" on Windows)
description = "MODFLOW 6 Zonebudget utility"
license = "CC0-1.0"

[[programs.zbud6.dists]]
name = "linux"
asset = "mf6.7.0_linux.zip"
hash = "sha256:..."

[[programs.zbud6.dists]]
name = "win64"
asset = "mf6.7.0_win64.zip"
hash = "sha256:..."
```

**Executable path resolution**:

The `exe` field can be specified at three levels, checked in this order:

1. **Distribution-level** (`[[programs.{name}.dists]]` entry with `exe` field)
   - Use when different platforms have different archive structures
   - Most specific - overrides program-level and default
   - Example: `exe = "mf6.7.0_win64/bin/mf6.exe"`

2. **Program-level** (`[programs.{name}]` section with `exe` field)
   - Use when all platforms share the same relative path structure
   - Example: `exe = "bin/mfnwt"`

3. **Default** (neither specified)
   - Automatically detects executable location when installing
   - Tries common patterns in order:
     - **Nested with bin/**: `{archive_name}/bin/{program}`
     - **Nested without bin/**: `{archive_name}/{program}`
     - **Flat with bin/**: `bin/{program}`
     - **Flat without bin/**: `{program}`
   - Example: For `mf6`, automatically finds binary whether in `mf6.7.0_linux/bin/mf6`, `bin/mf6`, or other common layouts

**Archive structure patterns**:

The API supports four common archive layouts:

1. **Nested with bin/** (e.g., MODFLOW 6):
   ```
   mf6.7.0_linux.zip
   └── mf6.7.0_linux/
       └── bin/
           └── mf6
   ```

2. **Nested without bin/**:
   ```
   program.1.0_linux.zip
   └── program.1.0_linux/
       └── program
   ```

3. **Flat with bin/**:
   ```
   program.zip
   └── bin/
       └── program
   ```

4. **Flat without bin/**:
   ```
   program.zip
   └── program
   ```

The `make_registry` tool automatically detects which pattern each archive uses and only stores non-default exe paths in the registry.

**Windows .exe extension handling**:
- The `.exe` extension is automatically added on Windows platforms if not present
- You can specify `exe = "mfnwt"` and it becomes `mfnwt.exe` on Windows
- Or explicitly include it: `exe = "path/to/mfnwt.exe"`

**Format notes**:
- Version and repository information come from the release tag and bootstrap configuration, not from the registry file
- The `schema_version` field is optional but recommended for future compatibility

Platform identifiers are as defined in the [modflow-devtools OS tag specification](https://modflow-devtools.readthedocs.io/en/latest/md/ostags.html): `linux`, `mac`, `win64`.

**Binary asset URLs**: The `asset` field contains just the filename (no full URL stored). Full download URLs are constructed dynamically at runtime from bootstrap metadata as:
```
https://github.com/{repo}/releases/download/{tag}/{asset}
```
For example: `https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/mf6.6.3_linux.zip`

This dynamic URL construction allows users to test against forks by simply changing the bootstrap configuration.

#### Registries vs. installation metadata

The Programs API maintains two distinct layers of metadata:

**Registry files** (`registry.toml`) - Published by program maintainers:
- Describe what's available from a release
- GitHub-coupled by design (asset names, not full URLs)
- Controlled by program repositories
- Cached locally after sync

**Installation metadata** (`{program}.json`) - Maintained by modflow-devtools:
- Track what's installed locally and where
- Source-agnostic (store full `asset_url`, not just asset name)
- Enable executable discovery and version management
- Support any installation source

This separation provides architectural flexibility:

1. **Future extensibility**: Installation metadata format doesn't change if we add support for:
   - Mirror sites (different URLs, same metadata structure)
   - Direct binary URLs (no GitHub release required)
   - Local builds (user-compiled binaries)
   - Import from get-modflow or other tools

2. **Clean responsibilities**: Registry files describe "what exists", metadata tracks "what I installed from where"

3. **Portability**: Users could theoretically register manually-installed binaries using the same metadata format

While registries are currently tied to GitHub releases (which is pragmatic and appropriate for the MODFLOW ecosystem), the installation metadata layer remains flexible for future needs.

### Registry discovery

Program registries are published as GitHub release assets alongside binary distributions. Registry file assets must be named **`programs.toml`**.

Registry discovery URL pattern:
```
https://github.com/{org}/{repo}/releases/download/{tag}/programs.toml
```

Examples:
```
https://github.com/MODFLOW-ORG/modflow6/releases/download/6.6.3/programs.toml
https://github.com/MODFLOW-ORG/modpath7/releases/download/7.2.001/programs.toml
```

#### Registry discovery procedure

At sync time, `modflow-devtools` discovers remote registries for each configured source and release tag:

1. **Check for release tag**: Look for a GitHub release with the specified tag
2. **Fetch registry asset**: Download `programs.toml` from the release assets
3. **Failure cases**:
   - If release tag doesn't exist:
     ```python
     ProgramRegistryDiscoveryError(
         f"Release tag '{tag}' not found for {repo}"
     )
     ```
   - If release exists but lacks `programs.toml` asset:
     ```python
     ProgramRegistryDiscoveryError(
         f"Program registry file 'programs.toml' not found as release asset "
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
│   ├── archives/
│   │   ├── mf6/                    # downloaded archives
│   │   │   └── 6.6.3/
│   │   │       └── linux/
│   │   │           └── mf6.6.6.3_linux.zip
│   │   └── mp7/
│   │       └── 7.2.001/
│   │           └── linux/
│   │               └── mp7.7.2.001_linux.zip
│   ├── binaries/
│   │   ├── mf6/                    # extracted binaries (all versions)
│   │   │   ├── 6.6.3/
│   │   │   │   └── linux/
│   │   │   │       └── bin/
│   │   │   │           └── mf6
│   │   │   └── 6.5.0/
│   │   │       └── linux/
│   │   │           └── bin/
│   │   │               └── mf6
│   │   ├── zbud6/
│   │   │   └── 6.6.3/
│   │   │       └── linux/
│   │   │           └── ...
│   │   └── mp7/
│   │       └── 7.2.001/
│   │           └── ...
│   └── metadata/
│       ├── mf6.json                # installation tracking per program
│       ├── zbud6.json
│       └── mp7.json
```

**Metadata tracking** (inspired by get-modflow):
- Each program has a metadata JSON file at `~/.cache/modflow-devtools/programs/metadata/{program}.json`
- Tracks all installations and versions:
  - Program name, installed versions, platform
  - For each installation: bindir, version, installation timestamp
  - Source repository, tag, asset URL, SHA256 hash
  - Currently active version in each bindir
- Enables executable discovery, version management, and fast re-switching

**Example metadata file** (`mf6.json`):
```json
{
  "program": "mf6",
  "installations": [
    {
      "version": "6.6.3",
      "platform": "linux",
      "bindir": "/usr/local/bin",
      "installed_at": "2024-01-15T10:30:00Z",
      "source": {
        "repo": "MODFLOW-ORG/modflow6",
        "tag": "6.6.3",
        "asset_url": "https://github.com/.../mf6.6.6.3_linux.zip",
        "hash": "sha256:..."
      },
      "executables": ["mf6"],
      "active": true
    },
    {
      "version": "6.5.0",
      "platform": "linux",
      "bindir": "/home/user/.local/bin",
      "installed_at": "2024-01-10T14:20:00Z",
      "source": {...},
      "active": false
    }
  ]
}
```

**Cache management**:
- Registry files are cached per source repository and release tag
- Downloaded archives are cached and verified against registry hashes before reuse
- Binary distributions (all versions) are cached per program name, version, and platform
- Installed binaries are **copies** from cache to user's chosen bindir (not symlinks)
- Cache can be cleared with `programs clean` command (with options for archives, binaries, or registries)
- Users can list cached/installed programs with `programs list`
- Cache is optional after installation - only needed for version switching without re-download

### Registry synchronization

Synchronization updates the local registry cache with remote program metadata.

#### Manual sync

Exposed as a CLI command and Python API:

```bash
# Sync all configured sources and release tags
python -m modflow_devtools.programs sync

# Sync specific source to specific release version
python -m modflow_devtools.programs sync --repo MODFLOW-ORG/modflow6 --version 6.6.3

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
sync_registries(repo="MODFLOW-ORG/modflow6", version="6.6.3")

# Check status
status = get_sync_status()
```

#### Automatic sync

- **At install time**: Best-effort sync during package installation (fail silently on network errors)
- **On first use**: If registry cache is empty, attempt to sync before raising errors
- **Configurable**: Users can disable auto-sync via environment variable: `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`

#### Force semantics

The `--force` flag has different meanings depending on the command, maintaining separation of concerns:

**`sync --force`**: Forces re-downloading of registry metadata
- Re-fetches `programs.toml` from GitHub even if already cached
- Use when registry files have been updated upstream
- Does not affect installed programs or downloaded archives
- Network operation required

**`install --force`**: Forces re-installation of program binaries
- Re-extracts from cached archive and re-copies to installation directory
- Does **not** re-sync registry metadata (registries and installations are decoupled)
- Use when installation is corrupted or when reinstalling to different location
- Works offline if archive is already cached
- Network operation only if archive not cached

**Design rationale**:
- **Separation of concerns**: Sync manages metadata discovery, install manages binary deployment
- **Offline workflows**: Users can reinstall without network access if archives are cached
- **Performance**: Avoids unnecessary network calls when registry hasn't changed
- **Explicit control**: Users explicitly choose when to refresh metadata vs reinstall binaries
- **Debugging**: Easier to isolate issues between registry discovery and installation

**Common patterns**:
```bash
# Update to latest registry and install
python -m modflow_devtools.programs sync --force
python -m modflow_devtools.programs install mf6

# Repair installation without touching registry (offline-friendly)
python -m modflow_devtools.programs install mf6 --force

# Complete refresh of both metadata and installation
python -m modflow_devtools.programs sync --force
python -m modflow_devtools.programs install mf6 --force
```

### Program installation

Installation extends beyond metadata to actually providing program executables by downloading and managing pre-built platform-specific binaries.

```bash
# Install from binary (auto-detects platform)
python -m modflow_devtools.programs install mf6

# Install specific version
python -m modflow_devtools.programs install mf6@6.6.3

# Install to custom location (interactive selection like get-modflow)
python -m modflow_devtools.programs install mf6 --bindir :

# Install to specific directory
python -m modflow_devtools.programs install mf6 --bindir /usr/local/bin

# Install multiple versions side-by-side (cached separately)
python -m modflow_devtools.programs install mf6@6.6.3
python -m modflow_devtools.programs install mf6@6.5.0

# Select active version (re-copies from cache to bindir)
python -m modflow_devtools.programs select mf6@6.6.3

# List installed programs
python -m modflow_devtools.programs list --installed

# List available versions of a program
python -m modflow_devtools.programs list mf6

# Show where program is installed
python -m modflow_devtools.programs which mf6

# Uninstall specific version
python -m modflow_devtools.programs uninstall mf6@6.6.3

# Uninstall all versions
python -m modflow_devtools.programs uninstall mf6 --all
```

Python API:

```python
from modflow_devtools.programs import install_program, list_installed, get_executable

# Install
install_program("mf6", version="6.6.3")

# Install to custom bindir
install_program("mf6", version="6.6.3", bindir="/usr/local/bin")

# Get executable path (looks up active version in bindir)
mf6_path = get_executable("mf6")

# Get specific version
mf6_path = get_executable("mf6", version="6.6.3")

# List installed
installed = list_installed()
```

**Installation process** (adapted from get-modflow):
1. Resolve program name to registry entry
2. Detect platform (or use specified platform)
3. Check if binary distribution available for platform
4. Determine bindir (interactive selection, explicit path, or default from previous install)
5. Check cache for existing archive (verify hash if present)
6. Download archive to cache if needed: `~/.cache/modflow-devtools/programs/archives/{program}/{version}/{platform}/`
7. Extract to binaries cache: `~/.cache/modflow-devtools/programs/binaries/{program}/{version}/{platform}/`
8. **Copy** executables from cache to user's chosen bindir (not symlink)
9. Apply executable permissions on Unix (`chmod +x`)
10. Update metadata file: `~/.cache/modflow-devtools/programs/metadata/{program}.json`
11. Return paths to installed executables

**Version management**:
- Multiple versions cached separately in `~/.cache/modflow-devtools/programs/binaries/{program}/{version}/`
- User can install to different bindirs (e.g., `/usr/local/bin`, `~/.local/bin`)
- Only one version is "active" per bindir (the actual copy at that location)
- `select` command re-copies a different version from cache to bindir
- Metadata tracks which version is active in each bindir
- Version switching is fast (copy operation, milliseconds for typical MODFLOW binaries)

**Why copy instead of symlink?**
- **Simplicity**: Single code path for all platforms (Unix, Windows, macOS)
- **Consistency**: Same behavior everywhere
- **Robustness**: Installed binary is independent of cache (cache can be cleared)
- **User expectations**: Binary is actually where they asked for it, not a symlink
- **No Windows symlink issues**: Avoids admin privilege requirements on older Windows

**Note**: Programs are expected to publish pre-built binaries for all supported platforms. Building from source is not supported - program repositories are responsible for releasing platform-specific binaries.

### Source program integration

For program repositories to integrate, they can generate registry files in two ways:

#### Mode 1: Local Assets (CI/Build Pipeline)

Use this mode when you have local distribution files during CI builds:

```bash
# Generate registry from local distribution files
python -m modflow_devtools.programs.make_registry \
  --dists *.zip \
  --programs mf6 zbud6 libmf6 mf5to6 \
  --version 6.6.3 \
  --repo MODFLOW-ORG/modflow6 \
  --compute-hashes \
  --output programs.toml
```

**How it works:**
- Uses `--dists` to specify a glob pattern for local distribution files (e.g., `*.zip`)
- Scans the local filesystem for matching files
- Requires `--version` and `--repo` arguments
- Optionally computes SHA256 hashes from local files with `--compute-hashes`
- Creates asset entries from local file names
- Auto-detects platform from file names (linux, mac, win64, etc.)
- **Automatic pattern detection**:
  - Inspects archives to detect executable locations
  - Recognizes nested and flat archive patterns
  - Automatically optimizes exe paths (only stores non-default paths)
  - Detects when all distributions use the same relative path
  - Caches downloaded assets to avoid redundant downloads when multiple programs share the same archive

**Example CI integration** (GitHub Actions):
```yaml
- name: Generate program registry
  run: |
    python -m modflow_devtools.programs.make_registry \
      --dists *.zip \
      --programs mf6 zbud6 libmf6 mf5to6 \
      --version ${{ github.ref_name }} \
      --repo ${{ github.repository }} \
      --compute-hashes \
      --output programs.toml

- name: Upload registry to release
  uses: softprops/action-gh-release@v1
  with:
    files: programs.toml
```

#### Mode 2: GitHub Release (Testing/Regeneration)

Use this mode to generate a registry from an existing GitHub release:

```bash
# Generate registry from existing GitHub release
python -m modflow_devtools.programs.make_registry \
  --repo MODFLOW-ORG/modflow6 \
  --version 6.6.3 \
  --programs mf6 zbud6 libmf6 mf5to6 \
  --output programs.toml
```

**How it works:**
- Fetches release assets from GitHub API using repo and version (tag)
- Downloads assets to detect exe paths and enable pattern optimization
- Optionally computes SHA256 hashes with `--compute-hashes`
- Useful for testing or regenerating a registry for an existing release
- No `--dists` argument needed - pulls from GitHub directly
- **Automatic pattern detection** (same as Mode 1):
  - Inspects archives to find executables
  - Detects nested/flat patterns automatically
  - Only stores non-default exe paths in registry
  - Caches downloads when processing multiple programs from same release

**Additional options:**
```bash
# With custom executable paths (if not bin/{program})
python -m modflow_devtools.programs.make_registry \
  --dists *.zip \
  --programs mf6:bin/mf6 zbud6:bin/zbud6 custom:path/to/exe \
  --version 6.6.3 \
  --repo MODFLOW-ORG/modflow6

# With description and license metadata
python -m modflow_devtools.programs.make_registry \
  --dists *.zip \
  --programs mf6 \
  --version 6.6.3 \
  --repo MODFLOW-ORG/modflow6 \
  --description "MODFLOW 6 groundwater flow model" \
  --license "CC0-1.0"
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

The Programs API uses a consolidated object-oriented design with Pydantic models and concrete classes.

#### ProgramDistribution

Represents platform-specific distribution information:

```python
class ProgramDistribution(BaseModel):
    """Distribution-specific information."""
    name: str  # Distribution name (e.g., linux, mac, win64)
    asset: str  # Release asset filename
    exe: str | None  # Executable path within archive (optional, overrides program-level exe)
    hash: str | None  # SHA256 hash
```

#### ProgramMetadata

Program metadata in registry:

```python
class ProgramMetadata(BaseModel):
    """Program metadata in registry."""
    description: str | None
    license: str | None
    exe: str | None  # Optional: defaults to bin/{program}
    dists: list[ProgramDistribution]  # Available distributions

    def get_exe_path(self, program_name: str, platform: str | None = None) -> str:
        """Get executable path, using default if not specified."""
```

#### ProgramRegistry

Top-level registry data model:

```python
class ProgramRegistry(BaseModel):
    """Program registry data model."""
    schema_version: str | None
    programs: dict[str, ProgramMetadata]
```

#### ProgramCache

Manages local caching of program registries:

```python
class ProgramCache:
    """Manages local caching of program registries."""
    def save(self, registry: ProgramRegistry, source: str, ref: str) -> Path
    def load(self, source: str, ref: str) -> ProgramRegistry | None
    def has(self, source: str, ref: str) -> bool
    def list(self) -> list[tuple[str, str]]
    def clear(self)
```

#### ProgramSourceRepo

Represents a single program source repository:

```python
class ProgramSourceRepo(BaseModel):
    """A single program source repository."""
    repo: str
    name: str | None
    refs: list[str]

    def discover(self, ref: str) -> DiscoveredProgramRegistry
    def sync(self, ref: str | None, force: bool, verbose: bool) -> SyncResult
    def is_synced(self, ref: str) -> bool
    def list_synced_refs(self) -> list[str]
```

#### ProgramSourceConfig

Configuration for program sources:

```python
class ProgramSourceConfig(BaseModel):
    """Configuration for program sources."""
    sources: dict[str, ProgramSourceRepo]

    @property
    def status(self) -> dict[str, ProgramSourceRepo.SyncStatus]

    def sync(self, source, force, verbose) -> dict[str, SyncResult]

    @classmethod
    def load(cls, bootstrap_path, user_config_path) -> "ProgramSourceConfig"
```

#### ProgramInstallation

Tracks a single program installation:

```python
class ProgramInstallation(BaseModel):
    """A single program installation."""
    version: str
    platform: str
    bindir: Path
    installed_at: datetime
    source: dict[str, str]  # repo, tag, asset_url, hash
    executables: list[str]
    active: bool
```

#### InstallationMetadata

Manages installation metadata for a program:

```python
class InstallationMetadata:
    """Manages installation metadata for a program."""
    def __init__(self, program: str, cache: ProgramCache | None = None)
    def load(self) -> bool
    def save(self) -> None
    def add_installation(self, installation: ProgramInstallation) -> None
    def remove_installation(self, version: str, bindir: Path | None) -> None
    def get_installation(self, version: str, bindir: Path | None) -> ProgramInstallation | None
    def list_installations(self) -> list[ProgramInstallation]
    def get_active_installation(self, bindir: Path | None) -> ProgramInstallation | None
    def set_active(self, version: str, bindir: Path) -> None
```

#### ProgramManager

High-level manager for program installation and version management:

```python
class ProgramManager:
    """High-level program installation manager."""
    def __init__(self, cache: ProgramCache | None = None)

    @property
    def config(self) -> ProgramSourceConfig

    def install(
        self,
        program: str,
        version: str | None = None,
        bindir: Path | None = None,
        platform: str | None = None,
        force: bool = False,
        verbose: bool = False,
    ) -> list[Path]

    def select(
        self,
        program: str,
        version: str,
        bindir: Path | None = None,
        verbose: bool = False,
    ) -> list[Path]

    def uninstall(
        self,
        program: str,
        version: str | None = None,
        bindir: Path | None = None,
        all_versions: bool = False,
        remove_cache: bool = False,
        verbose: bool = False,
    ) -> None

    def get_executable(
        self,
        program: str,
        version: str | None = None,
        bindir: Path | None = None,
    ) -> Path

    def list_installed(
        self,
        program: str | None = None,
    ) -> dict[str, list[ProgramInstallation]]
```

### Python API

The Programs API provides both object-oriented and functional interfaces.

**Object-Oriented API** (using `ProgramManager`):

```python
from modflow_devtools.programs import ProgramManager

# Create manager (or use _DEFAULT_MANAGER)
manager = ProgramManager()

# Install programs
paths = manager.install("mf6", version="6.6.3", verbose=True)

# Switch versions
manager.select("mf6", version="6.5.0", verbose=True)

# Get executable path
mf6_path = manager.get_executable("mf6")

# List installed programs
installed = manager.list_installed()

# Uninstall
manager.uninstall("mf6", version="6.5.0")
```

**Functional API** (convenience wrappers):

```python
from modflow_devtools.programs import (
    install_program,
    select_version,
    get_executable,
    list_installed,
    uninstall_program,
)

# Install
paths = install_program("mf6", version="6.6.3", verbose=True)

# Switch versions
select_version("mf6", version="6.5.0")

# Get executable path
mf6_path = get_executable("mf6")

# List installed
installed = list_installed()

# Uninstall
uninstall_program("mf6", version="6.5.0")
```

**Registry and Configuration API**:

```python
from modflow_devtools.programs import (
    _DEFAULT_CACHE,
    ProgramSourceConfig,
    ProgramSourceRepo,
    ProgramRegistry,
)

# Load configuration and sync
config = ProgramSourceConfig.load()
results = config.sync(verbose=True)

# Access cached registries
registry = _DEFAULT_CACHE.load("modflow6", "6.6.3")
programs = registry.programs  # dict[str, ProgramMetadata]

# Work with specific sources
source = config.sources["modflow6"]
result = source.sync(ref="6.6.3", force=True, verbose=True)
```

## Migration path

### Transitioning from pymake

Since programs will publish pre-built binaries, pymake is no longer needed for building or for maintaining the program database:

1. **Phase 1**: Programs API provides read-only access to program metadata
2. **Phase 2**: Add installation capabilities, users can install programs via devtools
3. **Phase 3**: Program repositories begin publishing their own registries with pre-built binaries
4. **Phase 4**: devtools becomes the authoritative source for program metadata
5. **Phase 5**: pymake deprecated entirely (no longer needed)

### Implementation Summary

The Programs API has been implemented following a consolidated object-oriented approach in `modflow_devtools/programs/__init__.py` (~600 lines).

**Core Infrastructure** ✅
- Bootstrap configuration: `modflow_devtools/programs/programs.toml`
- Pydantic models: `ProgramRegistry`, `ProgramMetadata`, `ProgramBinary`
- Cache management: `ProgramCache` class with save/load/list/clear operations
- Thread-safe caching with filelock
- User config overlay support at `~/.config/modflow-devtools/programs.toml`

**Registry Classes** ✅
- `ProgramSourceRepo`: Represents a program source repository with discovery and sync
- `ProgramSourceConfig`: Configuration container with multi-source management
- `DiscoveredProgramRegistry`: Discovery result dataclass
- Nested `SyncResult` and `SyncStatus` classes for operation tracking

**Discovery & Sync** ✅
- Release asset discovery from GitHub releases
- Local cache at `~/.cache/modflow-devtools/programs/registries/{source}/{ref}/`
- Automatic sync on import (unless `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`)
- Manual sync via CLI or Python API
- Force re-download support

**CLI Interface** ✅
- `python -m modflow_devtools.programs sync` - Sync registries
- `python -m modflow_devtools.programs info` - Show sync status
- `python -m modflow_devtools.programs list` - List available programs
- `python -m modflow_devtools.programs install` - Install a program
- `python -m modflow_devtools.programs select` - Switch active version
- `python -m modflow_devtools.programs uninstall` - Uninstall a program
- `python -m modflow_devtools.programs which` - Show executable path
- `python -m modflow_devtools.programs installed` - List installed programs

**Registry Generation Tool** ✅
- `modflow_devtools/programs/make_registry.py` - Generate registry files
- Auto-detects platform binaries (linux/mac/win64)
- Optional SHA256 hash computation
- Example usage:
  ```bash
  python -m modflow_devtools.programs.make_registry \
    --repo MODFLOW-ORG/modflow6 \
    --version 6.6.3 \
    --programs mf6 zbud6 libmf6 mf5to6 \
    --compute-hashes \
    --output programs.toml
  ```

**Testing & Code Quality** ✅
- 20 tests passing (cache, config, sync, ProgramManager, installation metadata)
- Full mypy type checking (clean)
- Ruff code quality checks (clean)

**Python API Examples**:
```python
from modflow_devtools.programs import (
    _DEFAULT_CACHE,
    ProgramSourceConfig,
    ProgramSourceRepo,
    ProgramRegistry,
)

# Load bootstrap configuration
config = ProgramSourceConfig.load()

# Access a specific source
source = config.sources["modflow6"]

# Sync a specific release
result = source.sync(ref="6.6.3", verbose=True)

# Check sync status
status = config.status

# Load cached registry
registry = _DEFAULT_CACHE.load("modflow6", "6.6.3")
programs = registry.programs  # dict[str, ProgramMetadata]
```

**Installation & Version Management** ✅
- `ProgramManager` class: High-level manager for program operations
- `InstallationMetadata`: JSON-based tracking of installed programs
- Platform detection (linux/mac/win64)
- Binary download with SHA256 verification
- Archive extraction (zip/tar.gz)
- Bindir selection (auto-detect or custom)
- Copy-based installation from cache
- Fast version switching via re-copy
- Installation metadata at `~/.cache/modflow-devtools/programs/installations/{program}.json`
- Archive cache at `~/.cache/modflow-devtools/programs/archives/`
- Binary cache at `~/.cache/modflow-devtools/programs/binaries/{source}/{ref}/`
- Methods: `install()`, `select()`, `uninstall()`, `get_executable()`, `list_installed()`
- Convenience wrappers: `install_program()`, `select_version()`, etc.

**Upstream Integration** (next steps):
- Add registry generation to program repositories' CI (starting with modflow6)
- Publish registries as release assets
- Test discovery and installation with real releases
- Eventually deprecate pymake's program database functionality

## Relationship to Models API

The Programs API deliberately mirrors the Models API architecture:

| Aspect | Models API | Programs API |
|--------|-----------|--------------|
| **Bootstrap file** | `models/models.toml` | `programs/programs.toml` |
| **Registry format** | TOML with files/models/examples | TOML with programs/binaries |
| **Discovery** | Release assets or version control | Release assets only |
| **Caching** | `~/.cache/modflow-devtools/models` | `~/.cache/modflow-devtools/programs` |
| **Addressing** | `source@ref/path/to/model` | `program@version` |
| **CLI** | `models sync/info/list` | `programs sync/info/list/install` |
| **Key classes** | `ModelRegistry`, `ModelSourceRepo` | `ProgramRegistry`, `ProgramSourceRepo`, `ProgramManager` |

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

## Relationship to get-modflow

The Programs API should eventually supersede flopy's [`get-modflow`](https://github.com/modflowpy/flopy/blob/develop/flopy/utils/get_modflow.py) utility. Many of its patterns are directly applicable and can be adapted or reused.

### Reusable patterns from get-modflow

#### 1. Platform detection
**get-modflow approach**: `get_ostag()` function detects OS and returns platform identifiers (`linux`, `win32`, `win64`, `mac`, `macarm`).

**Programs API adaptation**:
- Reuse the platform detection logic
- Map to modflow-devtools OS tag values (`linux`, `mac`, `win64`)

```python
# Adapted from get-modflow
def get_platform() -> str:
    """Detect current platform for binary selection."""
    # Reuse get-modflow's logic, mapping to OS tag values
```

#### 2. Installation metadata tracking
**get-modflow approach**: Maintains JSON at `~/.local/share/flopy/get_modflow.json` with installation history:
```json
[
  {
    "bindir": "/usr/local/bin",
    "owner": "MODFLOW-USGS",
    "repo": "executables",
    "release_id": "12345",
    "asset_name": "linux.zip",
    "installed": "2024-01-15T10:30:00Z",
    "md5": "abc123...",
    "subset": ["mf6", "mp7"],
    "updated_at": "2024-01-15T09:00:00Z"
  }
]
```

**Programs API adaptation**:
- Store metadata per program at `~/.cache/modflow-devtools/programs/metadata/{program}.json`
- Track all installations (different versions, different bindirs) for each program
- Use JSON format similar to get-modflow but structured to track multiple installations
- See cache structure section for detailed metadata schema

#### 3. Bindir selection and writable directory discovery
**get-modflow approach**: `get_bindir_options()` evaluates directories in priority order:
1. Previous installation location
2. FloPy-specific directory (if in FloPy)
3. Python's Scripts/bin directory
4. User local bin (`~/.local/bin`, `%LOCALAPPDATA%\Microsoft\WindowsApps`)
5. System local bin (`/usr/local/bin`)

Returns only writable directories with interactive/auto-select modes.

**Programs API adaptation**:
- Reuse the writable directory discovery logic exactly
- Support same interactive selection (`:` prompt) and auto-select modes (`:python`)
- Default to previous installation location for that program
- Copy executables from cache to selected bindir (same as get-modflow's direct install approach)

```python
# Adapted from get-modflow
def get_install_locations(previous: Path | None = None) -> list[Path]:
    """Get writable installation directories in priority order."""
    # Reuse get-modflow's logic directly
```

#### 4. Executable extraction and installation
**get-modflow approach**:
1. Download ZIP to `~/Downloads`
2. Extract files from internal `bin/` directories
3. Parse optional `code.json` manifest
4. Filter by subset parameter
5. Extract to bindir root
6. Apply executable permissions on Unix (`chmod +x`)

**Programs API adaptation**:
- Download to cache: `~/.cache/modflow-devtools/programs/archives/`
- Use registry `exe` field instead of scanning for `bin/` dirs
- Apply same permission handling
- Track extracted files in metadata

```python
# Adapted from get-modflow
def extract_executables(archive: Path, dest: Path, executables: list[str]):
    """Extract specified executables from archive and set permissions."""
    # Reuse get-modflow's extraction and permission logic
```

#### 5. GitHub API interactions
**get-modflow approach**:
- Token authentication via `GITHUB_TOKEN` environment variable
- Retry logic for HTTP 503/404 (up to 3 attempts)
- Rate limit warnings (< 10 requests remaining)
- Release metadata fetching

**Programs API adaptation**:
- Reuse token authentication and retry logic
- Adapt for registry asset discovery (downloading `registry.toml`)
- Keep rate limit handling
- Add caching of GitHub API responses

```python
# Adapted from get-modflow
def get_github_request(url: str, token: str | None = None) -> requests.Response:
    """Make GitHub API request with token auth and retry logic."""
    # Reuse get-modflow's implementation
```

#### 6. Archive caching
**get-modflow approach**: Cache downloaded ZIPs in `~/Downloads`, reuse unless `--force`.

**Programs API adaptation**:
- Cache in `~/.cache/modflow-devtools/programs/archives/{program}/{version}/{platform}/`
- Verify cached archives against registry hash before reuse
- Support `--force` to bypass cache

### Key enhancements over get-modflow

1. **Registry-driven discovery**: Use TOML registries instead of hard-coded GitHub repos
2. **Multiple versions**: Support side-by-side caching with fast version switching via re-copy
3. **Unified cache structure**: Organize by program/version/platform hierarchy
4. **Comprehensive metadata**: Track all installations across different bindirs and versions
6. **Version selection**: `select` command to switch active version in a bindir

### Migration path

Users of get-modflow should be able to migrate smoothly:

1. **Compatible metadata**: Programs API can read get-modflow's JSON to discover existing installations
3. **Import existing installations**: Detect executables installed by get-modflow and import metadata
4. **Gradual transition**: Both tools can coexist during migration period

## Cross-API Consistency

The Programs API follows the same design patterns as the Models and DFNs APIs for consistency. See the **Cross-API Consistency** section in `models.md` for full details.

**Key shared patterns**:
- Pydantic-based registry classes (not ABCs)
- Dynamic URL construction (URLs built at runtime, not stored in registries)
- Bootstrap and user config files with identical naming (`programs.toml`), distinguished by location
- Top-level `schema_version` metadata field
- Distinctly named registry file (`programs.toml`)
- Shared config utility: `get_user_config_path("programs")`

**Unique to Programs API**:
- Discovery via release assets only (not version control)
- Installation capabilities (binary downloads, version management)
- No `MergedRegistry` (program names globally unique)

## Design Decisions

### Initial implementation

These features are in scope for the initial implementation:

1. **Multiple versions side-by-side**: Users can install multiple versions of the same program in cache. Copy selected version to bindir to make it active. Fast version switching via re-copy from cache.

2. **Installation metadata tracking**: Maintain metadata about each installation (similar to flopy's `get-modflow`) to support executable discovery and version management.

3. **Executable discovery**: Provide utilities to locate previously installed executables.

4. **Platform error messages**: When a platform-specific binary isn't available, show helpful error messages indicating which platforms are supported.

5. **PATH management**: Support adding installed programs to PATH (similar to flopy's `get-modflow`).

6. **flopy integration**: This API should eventually supersede flopy's `get-modflow` utility. See "Relationship to get-modflow" section for reusable patterns.

### Explicitly out of scope

1. **Cross-platform installations**: No support for installing Windows binaries on Linux, etc.

2. **Dependency handling**: Programs don't depend on each other, so no dependency modeling needed.

3. **Mirror URLs**: Use GitHub releases only (no mirror support).

### Future enhancements

These features are desirable but can be added after the initial implementation:

1. **Semantic version ranges**: Support version specifiers like `mf6@^6.6` to install any compatible version satisfying the range.

2. **Aliases and special versions**: Support aliasing (e.g., `mf6-latest` → `mf6@6.6.3`) and special version identifiers like `mf6@latest` or `mf6@stable`.

3. **Checksum/signature verification**: Verify checksums or signatures on binary distributions for security and integrity.

4. **Update notifications**: Notify users when newer versions are available.
