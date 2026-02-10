# Programs API

The `modflow_devtools.programs` module provides programmatic access to MODFLOW and related programs in the MODFLOW ecosystem. It enables discovering, synchronizing, installing, and managing program binaries.

**Note**: This API follows the same design patterns as the Models API, with a dynamic registry system that decouples program releases from `modflow-devtools` releases.

## Overview

The Programs API provides:

- **Registry synchronization**: Download program metadata from remote sources
- **Program installation**: Install pre-built binaries for your platform
- **Version management**: Install multiple versions side-by-side and switch between them
- **Executable discovery**: Locate installed programs programmatically

## Basic Usage

### Installing a program

The simplest way to install a program:

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
# Install latest version
python -m modflow_devtools.programs install mf6

# Install specific version
python -m modflow_devtools.programs install mf6@6.6.3

# Install to custom directory
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

Or via CLI:

```bash
# Show path to installed executable
python -m modflow_devtools.programs which mf6

# List all installed programs
python -m modflow_devtools.programs installed

# List specific program with details
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

Or via CLI:

```bash
# Install multiple versions
python -m modflow_devtools.programs install mf6@6.6.3
python -m modflow_devtools.programs install mf6@6.5.0

# Switch to different version
python -m modflow_devtools.programs select mf6@6.5.0
```

## Program Registries

Program metadata is provided by remote registries published by program repositories. On first use, `modflow-devtools` automatically attempts to sync these registries.

### Syncing registries

Registries can be manually synchronized:

```python
from modflow_devtools.programs import ProgramSourceConfig

# Load configuration
config = ProgramSourceConfig.load()

# Sync all configured sources
results = config.sync(verbose=True)

# Sync specific source
results = config.sync(source="modflow6", verbose=True)
```

Or via CLI:

```bash
# Sync all sources
python -m modflow_devtools.programs sync

# Sync specific source
python -m modflow_devtools.programs sync --source modflow6

# Force re-download
python -m modflow_devtools.programs sync --force
```

### Viewing available programs

```bash
# Show sync status
python -m modflow_devtools.programs info

# List available programs (summary)
python -m modflow_devtools.programs list

# List with details
python -m modflow_devtools.programs list --verbose

# Filter by source
python -m modflow_devtools.programs list --source modflow6 --verbose
```

## Program Addressing

Programs are addressed using the format: `{program}@{version}`

Examples:
- `mf6@6.6.3` - MODFLOW 6 version 6.6.3
- `zbud6@6.6.3` - MODFLOW 6 Zonebudget version 6.6.3
- `mp7@7.2.001` - MODPATH 7 version 7.2.001

## Advanced Usage

### Using `ProgramManager`

For more control, use the `ProgramManager` class directly:

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

# Uninstall specific version
manager.uninstall("mf6", version="6.5.0")

# Uninstall all versions
manager.uninstall("mf6", all_versions=True)
```

### Working with registries

Access cached registry data directly:

```python
from modflow_devtools.programs import _DEFAULT_CACHE, ProgramSourceConfig

# Load configuration
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

## Auto-sync Behavior

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

## Complete CLI Reference

```bash
# Sync registries
python -m modflow_devtools.programs sync [--source SOURCE] [--force]

# Show sync status
python -m modflow_devtools.programs info

# List available programs
python -m modflow_devtools.programs list [--source SOURCE] [--ref REF] [--verbose]

# Install a program
python -m modflow_devtools.programs install PROGRAM[@VERSION] [--bindir DIR] [--platform PLATFORM] [--force]

# Switch active version
python -m modflow_devtools.programs select PROGRAM@VERSION [--bindir DIR]

# Uninstall a program
python -m modflow_devtools.programs uninstall PROGRAM[@VERSION] [--bindir DIR] [--all] [--remove-cache]

# Show executable path
python -m modflow_devtools.programs which PROGRAM [--version VERSION] [--bindir DIR]

# List installed programs
python -m modflow_devtools.programs installed [PROGRAM] [--verbose]
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
