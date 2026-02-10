# Programs API

The `modflow_devtools.programs` module provides programmatic access to MODFLOW and related programs in the MODFLOW ecosystem. It can be used with MODFLOW organization releases or custom program repositories.

This module builds on [Pooch](https://www.fatiando.org/pooch/latest/index.html) for file fetching and caching. While it leverages Pooch's capabilities, it provides an independent layer with:

- Registration, discovery and synchronization
- Installation and version management
- Platform-specific binary handling

Program registries can be synchronized from remote sources on demand. The user or developer can inspect and install programs published by the MODFLOW organization, from a personal fork, or from custom repositories.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->


- [Overview](#overview)
- [Usage](#usage)
  - [Syncing registries](#syncing-registries)
  - [Inspecting available programs](#inspecting-available-programs)
  - [Installing a program](#installing-a-program)
  - [Finding installed programs](#finding-installed-programs)
  - [Version management](#version-management)
  - [Using the default manager](#using-the-default-manager)
  - [Customizing program sources](#customizing-program-sources)
  - [Working with registries](#working-with-registries)
- [Program Addressing](#program-addressing)
- [Platform Support](#platform-support)
- [Cache Management](#cache-management)
- [Automatic Synchronization](#automatic-synchronization)
- [Relationship to pymake and get-modflow](#relationship-to-pymake-and-get-modflow)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Overview

The Programs API provides:

- **Program registration**: Index local or remote program repositories
- **Program discovery**: Browse available programs and versions
- **Program installation**: Install pre-built binaries for your platform
- **Version management**: Install multiple versions side-by-side and switch between them

Program metadata is provided by **registries** which are published by program repositories. On first use, `modflow-devtools` automatically attempts to sync these registries.

A program registry contains metadata for available programs including:

- **Program name and description**
- **Available versions**
- **Platform-specific distributions** (binaries and assets)

## Usage

### Syncing registries

Registries can be manually synchronized:

```python
from modflow_devtools.programs import ProgramSourceConfig

config = ProgramSourceConfig.load()

# Sync all configured sources
results = config.sync(verbose=True)

# Sync specific source
results = config.sync(source="modflow6", verbose=True)
```

Or via CLI:

```bash
python -m modflow_devtools.programs sync
python -m modflow_devtools.programs sync --source modflow6
python -m modflow_devtools.programs sync --force
```

### Inspecting available programs

```python
from modflow_devtools.programs import ProgramSourceConfig

config = ProgramSourceConfig.load()

# Check sync status
status = config.status
for source_name, source_status in status.items():
    print(f"{source_name}: {source_status.cached_refs}")
```

Or by CLI:

```bash
python -m modflow_devtools.programs info  # Show sync status
python -m modflow_devtools.programs list  # Show program summary
python -m modflow_devtools.programs list --verbose  # Full list with details
python -m modflow_devtools.programs list --source modflow6 --verbose  # Filter by source
```

### Installing a program

```python
from modflow_devtools.programs import install_program

# Install latest available version
paths = install_program("mf6", verbose=True)

# Install specific version
paths = install_program("mf6", version="6.6.3", verbose=True)

# Install to custom directory
paths = install_program("mf6", version="6.6.3", bindir="/usr/local/bin")
```

Or via CLI:

```bash
python -m modflow_devtools.programs install mf6
python -m modflow_devtools.programs install mf6@6.6.3
python -m modflow_devtools.programs install mf6@6.6.3 --bindir /usr/local/bin
```

### Finding installed programs

```python
from modflow_devtools.programs import get_executable, list_installed

# Get path to installed executable
mf6_path = get_executable("mf6")

# Get specific version
mf6_path = get_executable("mf6", version="6.6.3")

# List all installed programs
installed = list_installed()
for program_name, installations in installed.items():
    for inst in installations:
        print(f"{program_name} {inst.version} in {inst.bindir}")
```

Or by CLI:

```bash
python -m modflow_devtools.programs which mf6
python -m modflow_devtools.programs installed
python -m modflow_devtools.programs installed mf6 --verbose
```

### Version management

Multiple versions can be installed side-by-side. Switch between them using `select`:

```python
from modflow_devtools.programs import install_program, select_version

# Install multiple versions
install_program("mf6", version="6.6.3")
install_program("mf6", version="6.5.0")

# Switch active version
select_version("mf6", version="6.5.0")
```

Or by CLI:

```bash
python -m modflow_devtools.programs install mf6@6.6.3
python -m modflow_devtools.programs install mf6@6.5.0
python -m modflow_devtools.programs select mf6@6.5.0
```

### Using the default manager

The module provides explicit access to the default manager used by `install_program()` etc.

```python
from modflow_devtools.programs import _DEFAULT_MANAGER

# Install programs
paths = _DEFAULT_MANAGER.install("mf6", version="6.6.3", verbose=True)

# Switch versions
_DEFAULT_MANAGER.select("mf6", version="6.5.0", verbose=True)

# Get executable path
mf6_path = _DEFAULT_MANAGER.get_executable("mf6")

# List installed programs
installed = _DEFAULT_MANAGER.list_installed()

# Uninstall specific version
_DEFAULT_MANAGER.uninstall("mf6", version="6.5.0")

# Uninstall all versions
_DEFAULT_MANAGER.uninstall("mf6", all_versions=True)
```

### Customizing program sources

Create a user config file to add custom sources or override defaults:

- **Windows**: `%APPDATA%/modflow-devtools/programs.toml`
- **macOS**: `~/Library/Application Support/modflow-devtools/programs.toml`
- **Linux**: `~/.config/modflow-devtools/programs.toml`

Example user config:

```toml
[sources.modflow6]
repo = "myusername/modflow6"  # Use a fork for testing
refs = ["develop"]
```

The user config is automatically merged with the bundled config, allowing you to test against forks or add private repositories.

### Working with registries

Access cached registry data directly:

```python
from modflow_devtools.programs import _DEFAULT_CACHE, ProgramSourceConfig

config = ProgramSourceConfig.load()

# Check sync status
status = config.status
for source_name, source_status in status.items():
    print(f"{source_name}: {source_status.cached_refs}")

# Load cached registry
registry = _DEFAULT_CACHE.load("modflow6", "6.6.3")
if registry:
    for program_name, metadata in registry.programs.items():
        print(f"{program_name} {metadata.version}")
        print(f"  Description: {metadata.description}")
        print(f"  Distributions: {[d.name for d in metadata.dists]}")
```

## Program Addressing

Programs are addressed using the format: `{program}@{version}`.

Examples:
- `mf6@6.6.3` - MODFLOW 6 version 6.6.3
- `zbud6@6.6.3` - MODFLOW 6 Zonebudget version 6.6.3
- `mp7@7.2.001` - MODPATH 7 version 7.2.001

## Platform Support

The Programs API automatically detects your platform and downloads the appropriate binaries:

- **linux**: Linux x86_64
- **mac**: macOS ARM64 (Apple Silicon)
- **win64**: Windows 64-bit

Programs must provide pre-built binaries for supported platforms. Building from source is not supported—program repositories are responsible for releasing platform-specific binaries.

## Cache Management

Downloaded archives and installed binaries are cached locally:

- **Registries**: `~/.cache/modflow-devtools/programs/registries/{source}/{ref}/`
- **Archives**: `~/.cache/modflow-devtools/programs/archives/{program}/{version}/{platform}/`
- **Binaries**: `~/.cache/modflow-devtools/programs/binaries/{program}/{version}/{platform}/`
- **Metadata**: `~/.cache/modflow-devtools/programs/installations/{program}.json`

The cache enables:
- Fast re-installation without re-downloading
- Efficient version switching
- Offline access to previously installed programs

## Automatic Synchronization

By default, `modflow-devtools` attempts to sync registries:
- On first import (best-effort, fails silently on network errors)
- Before installation (unless `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`)
- Before listing available programs

To disable auto-sync:

```bash
export MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1
```

Then manually sync when needed:

```bash
python -m modflow_devtools.programs sync
```

## Relationship to pymake and get-modflow

The Programs API is designed to eventually supersede:
- **pymake's program database**: Registry responsibilities are delegated to program repositories
- **flopy's get-modflow**: Installation patterns adapted and enhanced for multi-version support

The Programs API provides:
- Decoupled releases (programs release independently of devtools)
- Multiple versions side-by-side
- Unified cache structure
- Comprehensive installation tracking
- Fast version switching
