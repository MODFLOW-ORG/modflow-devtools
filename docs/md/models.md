# Models API

The `modflow_devtools.models` module provides programmatic access to MODFLOW 6 (and other) model input files from official test and example repositories. It can also be used with local model repositories.

This module builds on [Pooch](https://www.fatiando.org/pooch/latest/index.html) for file fetching and caching. While it leverages Pooch's capabilities, it provides an independent layer with:

- Registration, discovery and synchronization
- Support for multiple sources and refs
- Hierarchical model addressing

Model registries can be synchronized from remote sources on demand. The user or developer can inspect and load models published by the MODFLOW organization, from a personal fork, or from the local filesystem.

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->


- [Overview](#overview)
- [Usage](#usage)
  - [Syncing registries](#syncing-registries)
  - [Inspecting available models](#inspecting-available-models)
  - [Copying models to a workspace](#copying-models-to-a-workspace)
  - [Using the default registry](#using-the-default-registry)
  - [Customizing model sources](#customizing-model-sources)
  - [Working with specific sources](#working-with-specific-sources)
- [Model Names](#model-names)
- [Local Registries](#local-registries)
- [Cache Management](#cache-management)
- [Automatic Synchronization](#automatic-synchronization)
- [Repository Integration](#repository-integration)
  - [Registry Generation](#registry-generation)
  - [Publishing Registries](#publishing-registries)
  - [Registry Format](#registry-format)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Overview

The Models API provides:

- **Model registration**: Index local or remote model repositories
- **Model discovery**: Browse available models from multiple repositories
- **Model retrieval**: Copy model input files to local workspaces

Model metadata is provided by **registries** which are published by model repositories. On first use, `modflow-devtools` automatically attempts to sync these registries.

A model registry contains three main components:

- **`files`**: Map of model input files to metadata (hash, path/URL)
- **`models`**: Map of model names to lists of their input files
- **`examples`**: Map of example scenarios to lists of models

An **example** is an ordered set of models which together form a complete example scenario.

The MODFLOW organization publishes a set of models for demonstration and testing, some of which are grouped into example scenarios, from the following repositories:

- `MODFLOW-ORG/modflow6-examples`
- `MODFLOW-ORG/modflow6-testmodels`
- `MODFLOW-ORG/modflow6-largetestmodels`

## Usage

### Syncing registries

Registries can be manually synchronized:

```python
from modflow_devtools.models import ModelSourceConfig

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

Or via CLI (both forms are equivalent):

```bash
# Using the mf command
mf models sync
mf models sync --source modflow6-testmodels
mf models sync --source modflow6-testmodels --ref develop
mf models sync --force

# Or using the module form
python -m modflow_devtools.models sync
python -m modflow_devtools.models sync --source modflow6-testmodels
python -m modflow_devtools.models sync --source modflow6-testmodels --ref develop
python -m modflow_devtools.models sync --force
```

### Inspecting available models

```python
from modflow_devtools.models import get_models, get_examples

models = get_models()
print(f"Available models: {len(models)}")
for name in list(models.keys())[:5]:
    print(f"  {name}")

examples = get_examples()
for example_name, model_list in list(examples.items())[:3]:
    print(f"{example_name}: {len(model_list)} models")
```

Or by CLI (both forms are equivalent):

```bash
# Using the mf command
mf models info  # Show sync status
mf models list  # Show model summary...
mf models list --verbose  # ..or full list
# Filter by source
mf models list --source mf6/test --verbose

# Or using the module form
python -m modflow_devtools.models info  # Show sync status
python -m modflow_devtools.models list  # Show model summary...
python -m modflow_devtools.models list --verbose  # ..or full list
# Filter by source
python -m modflow_devtools.models list --source mf6/test --verbose
```

### Copying models to a workspace

```python
from tempfile import TemporaryDirectory
from modflow_devtools.models import copy_to

with TemporaryDirectory() as workspace:
    model_path = copy_to(workspace, "mf6/example/ex-gwf-twri01", verbose=True)
```

### Using the default registry

The module provides explicit access to the default registry used by `get_models()` etc.

```python
from modflow_devtools.models import DEFAULT_REGISTRY

models = DEFAULT_REGISTRY.models
files = DEFAULT_REGISTRY.files
examples = DEFAULT_REGISTRY.examples

workspace = DEFAULT_REGISTRY.copy_to("./workspace", "mf6/example/ex-gwf-twri01")
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

## Model Names

Model names follow a hierarchical addressing scheme: `{source}@{ref}/{path/to/model}`.

The `path/to/` part is referred to as the **prefix**. Valid prefixes include:

- **`mf6/example/...`**: MODFLOW 6 example models from [modflow6-examples](https://github.com/MODFLOW-ORG/modflow6-examples)
- **`mf6/test/...`**: MODFLOW 6 test models from [modflow6-testmodels](https://github.com/MODFLOW-ORG/modflow6-testmodels)
- **`mf6/large/...`**: Large MODFLOW 6 test models from [modflow6-largetestmodels](https://github.com/MODFLOW-ORG/modflow6-largetestmodels)
- **`mf2005/...`**: MODFLOW-2005 models from [modflow6-testmodels](https://github.com/MODFLOW-ORG/modflow6-testmodels)

Example model names:
```
mf6/example/ex-gwf-twri01
mf6/test/test001a_Tharmonic
mf6/large/prudic2004t2
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

## Automatic Synchronization

By default, `modflow-devtools` attempts to sync registries:
- On first import (best-effort, fails silently on network errors)
- When accessing models (unless `MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1`)

To disable auto-sync:

```bash
export MODFLOW_DEVTOOLS_NO_AUTO_SYNC=1
```

Then manually sync when needed:

```bash
mf models sync
# Or: python -m modflow_devtools.models sync
```

## Repository Integration

Model repositories publish registry files (`models.toml`) describing available models, input files, and example groupings.

### Registry Generation

The `make_registry` tool generates registry files from version-controlled or release asset models.

**Version-controlled models**:

```bash
python -m modflow_devtools.models.make_registry \
  --repo MODFLOW-ORG/modflow6-testmodels \
  --ref master \
  --name mf6/test \
  --path mf6 \
  --output .registry
```

**Release asset models**:

```bash
python -m modflow_devtools.models.make_registry \
  --repo MODFLOW-ORG/modflow6-examples \
  --ref current \
  --asset-file mf6examples.zip \
  --name mf6/example \
  --output .registry
```

### Publishing Registries

Registry files can be published under version control or as release assets.

**Under version control**:

For instance, to commit a generated registry to a `.registry/` directory:

```yaml
- name: Generate registry
  run: |
    python -m modflow_devtools.models.make_registry \
      --repo ${{ github.repository }} \
      --ref ${{ github.ref_name }} \
      --name mf6/test \
      --path mf6 \
      --output .registry

- name: Commit registry
  run: |
    git add .registry/models.toml
    git commit -m "Update registry [skip ci]"
    git push
```

**As release assets**:

For instance, to upload a registry as a release asset:

```yaml
- name: Generate registry
  run: |
    python -m modflow_devtools.models.make_registry \
      --repo ${{ github.repository }} \
      --ref ${{ github.ref_name }} \
      --asset-file mf6examples.zip \
      --name mf6/example \
      --output .registry

- name: Upload registry as release asset
  uses: actions/upload-release-asset@v1
  with:
    asset_path: .registry/models.toml
    asset_name: models.toml
```

### Registry Format

The generated `models.toml` file contains:

- **`files`**: Map of filenames to hashes (URLs constructed dynamically)
- **`models`**: Map of model names to file lists
- **`examples`**: Map of example names to model lists

See the [developer documentation](dev/models.md) for detailed registry format specifications.
