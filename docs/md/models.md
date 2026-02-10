# Models API

The `modflow_devtools.models` module provides programmatic access to MODFLOW 6 (and other) model input files from official test and example repositories.

**Note**: This API uses a dynamic registry system that decouples model repository releases from `modflow-devtools` releases. Model registries are synchronized from remote sources on demand.

## Overview

The Models API provides:

- **Model discovery**: Browse available models from multiple repositories
- **Registry synchronization**: Download model metadata from remote sources
- **Model retrieval**: Copy model input files to local workspaces
- **Local registries**: Index custom model collections

## Basic Usage

### Listing available models

```python
from modflow_devtools.models import get_models, get_examples

# List all available models
models = get_models()
print(f"Available models: {len(models)}")

# Show first few model names
for name in list(models.keys())[:5]:
    print(f"  {name}")

# List example scenarios
examples = get_examples()
for example_name, model_list in list(examples.items())[:3]:
    print(f"{example_name}: {len(model_list)} models")
```

### Copying models to a workspace

The simplest way to use a model:

```python
from tempfile import TemporaryDirectory
from modflow_devtools.models import copy_to

# Copy model to a temporary directory
with TemporaryDirectory() as workspace:
    model_path = copy_to(workspace, "mf6/example/ex-gwf-twri01", verbose=True)
    print(f"Model copied to: {model_path}")
```

Or copy to a specific directory:

```python
from pathlib import Path
from modflow_devtools.models import copy_to

# Copy to specific workspace
workspace = Path("./my_workspace")
workspace.mkdir(exist_ok=True)
model_path = copy_to(workspace, "mf6/example/ex-gwf-twri01")
```

### Using the default registry

The module provides a default registry for convenient access:

```python
from modflow_devtools.models import DEFAULT_REGISTRY

# Access registry properties
models = DEFAULT_REGISTRY.models
files = DEFAULT_REGISTRY.files
examples = DEFAULT_REGISTRY.examples

# Copy using the registry directly
workspace = DEFAULT_REGISTRY.copy_to("./workspace", "mf6/example/ex-gwf-twri01")
```

## Model Names

Model names follow a hierarchical addressing scheme: `{source}@{ref}/{path/to/model}`

Currently available model prefixes:

- **`mf6/example/...`**: MODFLOW 6 example models from [modflow6-examples](https://github.com/MODFLOW-ORG/modflow6-examples)
- **`mf6/test/...`**: MODFLOW 6 test models from [modflow6-testmodels](https://github.com/MODFLOW-ORG/modflow6-testmodels)
- **`mf6/large/...`**: Large MODFLOW 6 test models from [modflow6-largetestmodels](https://github.com/MODFLOW-ORG/modflow6-largetestmodels)
- **`mf2005/...`**: MODFLOW-2005 models from [modflow6-testmodels](https://github.com/MODFLOW-ORG/modflow6-testmodels)

The path component reflects the relative location of the model within its source repository.

Example model names:
```
mf6/example/ex-gwf-twri01
mf6/test/test001a_Tharmonic
mf6/large/prudic2004t2
```

## Model Registries

Model metadata is provided by remote registries published by model repositories. On first use, `modflow-devtools` automatically attempts to sync these registries.

### Syncing registries

Registries can be manually synchronized:

```python
from modflow_devtools.models import ModelSourceConfig

# Load configuration
config = ModelSourceConfig.load()

# Sync all configured sources
results = config.sync(verbose=True)

# Sync specific source
results = config.sync(source="modflow6-testmodels", verbose=True)

# Check sync status
status = config.status
for source_name, source_status in status.items():
    print(f"{source_name}: {source_status.cached_refs}")
```

Or via CLI:

```bash
# Sync all sources
python -m modflow_devtools.models sync

# Sync specific source
python -m modflow_devtools.models sync --source modflow6-testmodels

# Sync specific ref
python -m modflow_devtools.models sync --source modflow6-testmodels --ref develop

# Force re-download
python -m modflow_devtools.models sync --force
```

### Viewing available models

```bash
# Show sync status
python -m modflow_devtools.models info

# List available models (summary)
python -m modflow_devtools.models list

# List with details
python -m modflow_devtools.models list --verbose

# Filter by source
python -m modflow_devtools.models list --source mf6/test --verbose
```

## Registry Structure

Each model registry contains three main components:

- **`files`**: Map of model input files to metadata (hash, path/URL)
- **`models`**: Map of model names to lists of their input files
- **`examples`**: Map of example scenarios to lists of models that run together

Access registry data directly:

```python
from modflow_devtools.models import get_files, get_models, get_examples

# Get all files
files = get_files()
for filename, file_info in list(files.items())[:3]:
    print(f"{filename}: {file_info.hash}")

# Get all models
models = get_models()
for model_name, file_list in list(models.items())[:3]:
    print(f"{model_name}: {len(file_list)} files")

# Get examples
examples = get_examples()
for example_name, model_list in examples.items():
    print(f"{example_name}: {model_list}")
```

## Local Registries

For development or testing with local models, create a local registry:

```python
from modflow_devtools.models import LocalRegistry

# Create and index a local registry
registry = LocalRegistry()
registry.index("path/to/models")

# Index with custom namefile pattern (e.g., for MODFLOW-2005)
registry.index("path/to/mf2005/models", namefile_pattern="*.nam")

# Use the local registry
models = registry.models
workspace = registry.copy_to("./workspace", "my-model-name")
```

Model subdirectories are identified by the presence of a namefile. By default, only MODFLOW 6 models are indexed (`mfsim.nam`). Use `namefile_pattern` to include other model types.

## Advanced Usage

### Working with specific sources

Access individual model sources:

```python
from modflow_devtools.models import ModelSourceConfig, _DEFAULT_CACHE

# Load configuration
config = ModelSourceConfig.load()

# Work with specific source
source = config.sources["modflow6-testmodels"]

# Check if synced
if source.is_synced("develop"):
    print("Already cached!")

# List synced refs
synced_refs = source.list_synced_refs()

# Sync specific ref
result = source.sync(ref="develop", verbose=True)

# Load cached registry
registry = _DEFAULT_CACHE.load("mf6/test", "develop")
if registry:
    print(f"Models: {len(registry.models)}")
    print(f"Files: {len(registry.files)}")
```

### Customizing model sources

Create a user config file to add custom sources or override defaults:

- **Windows**: `%APPDATA%/modflow-devtools/models.toml`
- **macOS**: `~/Library/Application Support/modflow-devtools/models.toml`
- **Linux**: `~/.config/modflow-devtools/models.toml`

Example user config:

```toml
[sources.modflow6-testmodels]
repo = "myusername/modflow6-testmodels"  # Use a fork for testing
name = "mf6/test"
refs = ["feature-branch"]
```

The user config is automatically merged with the bundled config, allowing you to test against forks or add private repositories.

## Cache Management

Model registries and files are cached locally for fast access:

- **Registries**: `~/.cache/modflow-devtools/models/registries/{source}/{ref}/`
- **Model files**: `~/.cache/modflow-devtools/models/` (managed by Pooch)

The cache enables:
- Fast model access without re-downloading
- Offline access to previously used models
- Efficient switching between repository refs

Check cache status:

```python
from modflow_devtools.models import _DEFAULT_CACHE

# List all cached registries
cached = _DEFAULT_CACHE.list()  # Returns: [(source, ref), ...]
for source, ref in cached:
    print(f"{source}@{ref}")

# Check specific cache
is_cached = _DEFAULT_CACHE.has("mf6/test", "develop")

# Clear cache (if needed)
_DEFAULT_CACHE.clear()
```

## Auto-sync Behavior

By default, `modflow-devtools` attempts to sync registries:
- On first import (best-effort, fails silently on network errors)
- When accessing models (unless `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`)

To disable auto-sync:

```bash
export MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1
```

Then manually sync when needed:

```bash
python -m modflow_devtools.models sync
```

## Complete CLI Reference

```bash
# Sync registries
python -m modflow_devtools.models sync [--source SOURCE] [--ref REF] [--force]

# Show sync status
python -m modflow_devtools.models info

# List available models
python -m modflow_devtools.models list [--source SOURCE] [--ref REF] [--verbose]
```

## Integration with Pooch

The Models API builds on [Pooch](https://www.fatiando.org/pooch/latest/index.html) for file fetching and caching. While it leverages Pooch's capabilities, it provides an independent layer with:

- Dynamic registry discovery and synchronization
- Multi-source and multi-ref support
- Hierarchical model naming
- Integration with MODFLOW ecosystem conventions

## Model Repository Integration

For model repository maintainers who want to publish their models:

Model repositories should publish a `models.toml` registry file either:
1. As a release asset (for repositories that build models in CI)
2. Under version control in a `.registry/` directory

Registry files contain:
- **`files`**: Map of filenames to hashes
- **`models`**: Map of model names to file lists
- **`examples`**: Map of example names to model lists

The `make_registry.py` tool (part of `modflow-devtools`) can generate these registry files. See the [developer documentation](dev/models.md) for details on registry creation.
