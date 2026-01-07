# Models API v2.0 Demo Walkthrough

**New Dynamic Registry System** - Decoupled from package releases!

---

## Overview: What Changed?

### Before (v1.x)
- ❌ 1.7MB+ TOML files shipped with every package release
- ❌ Tight coupling: `modflow-devtools` releases tied to model repository states
- ❌ Users had to wait for package updates to access new models
- ❌ Manual registry regeneration required by package maintainers

### After (v2.x)
- ✅ Minimal ~5KB bootstrap file (just tells us where repos are)
- ✅ Model repositories publish their own registries
- ✅ Sync on-demand to any git ref (branch, tag, commit hash)
- ✅ User config overlay for custom/forked repositories
- ✅ Automated registry generation in model repository CI

---

## Key Concepts

### 1. **Bootstrap File**
Bundled config that tells `modflow-devtools` where to find model repositories:
```toml
# modflow_devtools/models/models.toml
[sources.modflow6-testmodels]
repo = "MODFLOW-ORG/modflow6-testmodels"
name = "mf6/test"
refs = ["develop", "master"]
```

### 2. **User Config Overlay**
Override or extend bundled config for testing/custom repos:
```toml
# Windows: %APPDATA%/modflow-devtools/models.toml
# Linux/macOS: ~/.config/modflow-devtools/models.toml

[sources.modflow6-testmodels]
repo = "wpbonelli/modflow6-testmodels"  # Use fork instead
refs = ["registry"]  # Use custom branch
```

### 3. **Registry Discovery**
Two publication modes:
- **Release Assets**: `https://github.com/org/repo/releases/download/{tag}/models.toml`
- **Version Controlled**: `https://raw.githubusercontent.com/org/repo/{ref}/.registry/models.toml`

### 4. **Model Addressing**
Format: `{source}@{ref}/{model_path}`
- Example: `mf6/test@develop/test001a_Tharmonic`
- Guarantees provenance and no collisions

---

## Python API Demo

### Basic Workflow

```python
from modflow_devtools.models import discovery, sync, cache

# 1. Load bootstrap configuration (with user overlay)
bootstrap = discovery.load_bootstrap()

# 2. Discover remote registry
source = bootstrap.sources["modflow6-testmodels"]
discovered = discovery.discover_registry(source, ref="develop")
# Returns: DiscoveredRegistry with mode, URL, and parsed registry

# 3. Sync registry to local cache
result = sync.sync_registry(
    source="modflow6-testmodels",
    ref="develop",
    verbose=True
)
# Returns: SyncResult(synced=1, skipped=0, failed=0)

# 4. Load cached registry and use it
registry = cache.load_cached_registry("mf6/test", "develop")
print(f"Models: {len(registry.models)}")
print(f"Files: {len(registry.files)}")
```

### Convenience Methods on BootstrapSource

```python
source = bootstrap.sources["modflow6-testmodels"]

# Check if synced
if source.is_synced("develop"):
    print("Already cached!")

# List synced refs
synced_refs = source.list_synced_refs()
print(f"Cached: {synced_refs}")

# Sync via source method
result = source.sync(ref="develop", verbose=True)
```

### Cache Management

```python
from modflow_devtools.models import cache

# Get cache locations
cache_root = cache.get_cache_root()
models_dir = cache.get_models_cache_dir()

# List all cached registries
cached = cache.list_cached_registries()
# Returns: [(source, ref), ...]

# Check specific cache
is_cached = cache.is_registry_cached("mf6/test", "develop")

# Clear cache
cache.clear_registry_cache()
```

---

## CLI Demo

### 1. **Show Registry Status**
```bash
$ python -m modflow_devtools.models info

Registry sync status:

mf6/test (wpbonelli/modflow6-testmodels)
  Configured refs: registry
  Cached refs: registry

mf6/large (wpbonelli/modflow6-largetestmodels)
  Configured refs: registry
  Cached refs: registry

mf6/example (MODFLOW-ORG/modflow6-examples)
  Configured refs: current
  Cached refs: none
  Missing refs: current
```

### 2. **Sync Registries**

```bash
# Sync all configured sources/refs
$ python -m modflow_devtools.models sync

# Sync specific source
$ python -m modflow_devtools.models sync --source modflow6-testmodels

# Sync specific ref
$ python -m modflow_devtools.models sync --source modflow6-testmodels --ref develop

# Force re-download
$ python -m modflow_devtools.models sync --force

# Test against a fork
$ python -m modflow_devtools.models sync \
    --source modflow6-testmodels \
    --ref feature-branch \
    --repo myusername/modflow6-testmodels
```

### 3. **List Available Models**

```bash
# Summary view
$ python -m modflow_devtools.models list

Available models:

mf6/large@registry:
  Models: 19

mf6/test@registry:
  Models: 242

# Verbose view (show model names)
$ python -m modflow_devtools.models list --verbose

Available models:

mf6/test@registry:
  Models: 242
    - mf6/test/test001a_Tharmonic
    - mf6/test/test001a_Tharmonic_extlist
    - mf6/test/test001b_Tlogarithmic
    ... and 239 more
```

---

## Advanced: Testing Against Forks

This is what we demonstrated with the user config!

**Scenario**: You're developing a new registry file in your fork

1. **Create user config** at `%APPDATA%/modflow-devtools/models.toml`:
```toml
[sources.modflow6-testmodels]
repo = "wpbonelli/modflow6-testmodels"
name = "mf6/test"
refs = ["registry"]  # Your development branch
```

2. **Sync your fork**:
```bash
$ python -m modflow_devtools.models sync --source modflow6-testmodels
Discovering registry mf6/test@registry...
  Found via version_controlled at https://raw.githubusercontent.com/wpbonelli/modflow6-testmodels/registry/.registry/models.toml
  [+] Synced mf6/test@registry
```

3. **Use it normally** - your fork is now the default!

---

## Registry File Structure

Model repositories publish a single `models.toml`:

```toml
# Top-level metadata
schema_version = "1.0"
generated_at = "2025-12-23T12:51:49Z"
devtools_version = "1.9.0"

# File hashes (URLs constructed dynamically at runtime)
[files]
"test001a_Tharmonic/mfsim.nam" = {hash = "sha256:abc123..."}
"test001a_Tharmonic/gwf.nam" = {hash = "sha256:def456..."}

# Model definitions
[models]
"test001a_Tharmonic" = [
    "test001a_Tharmonic/mfsim.nam",
    "test001a_Tharmonic/gwf.nam",
]

# Example groupings (optional)
[examples]
"test001" = ["test001a_Tharmonic", "test001b_Tlogarithmic"]
```

**Key design**: No `url` field! URLs are constructed dynamically from:
- Bootstrap metadata (repo, ref, registry_path)
- Filename

This enables fork testing by just changing bootstrap config!

---

## Benefits for Developers

### For `modflow-devtools` Developers
- ✅ No more manual registry regeneration
- ✅ No more bloated package releases
- ✅ Release anytime without waiting for model updates
- ✅ Easier testing (just point to forks)

### For Model Repository Developers
- ✅ Automated registry generation in CI
- ✅ Models available immediately upon push/release
- ✅ Full control over versioning
- ✅ Support for multiple refs simultaneously

### For Users
- ✅ Access to latest models without package update
- ✅ Pin to specific git refs for reproducibility
- ✅ Test against development branches
- ✅ Smaller package installs (no 1.7MB+ TOML files)

---

## Registry Creation Tool - Simplified Interface

The `make_registry` tool has been completely redesigned for simplicity and clarity!

### Old Way (v1.x)
```bash
# Had to manually construct URLs - error prone!
python -m modflow_devtools.make_registry \
  --path . \
  --url https://github.com/MODFLOW-ORG/modflow6-testmodels/raw/master/mf6 \
  --model-name-prefix mf6/test
```

### New Way (v2.x)
```bash
# Just specify mode, repo, and ref - URLs constructed automatically!
python -m modflow_devtools.make_registry \
  --path ./mf6 \
  --mode version \
  --repo MODFLOW-ORG/modflow6-testmodels \
  --ref master \
  --name mf6/test \
  --output .registry
```

### Key Improvements

1. **Mode-based interface**: Choose `--mode version` or `--mode release`
2. **Automatic URL construction**: No manual URL typing
3. **Smart path detection**: Finds subdirectory path from directory structure (no git required!)
4. **Clear naming**: `--name` matches bootstrap file's `name` field
5. **Required arguments**: `--mode`, `--repo`, `--ref`, and `--name` prevent mistakes

### Example: Creating Registry for modflow6-examples

```bash
python -m modflow_devtools.make_registry \
  --path ./examples \
  --mode release \
  --repo MODFLOW-ORG/modflow6-examples \
  --ref current \
  --asset-file mf6examples.zip \
  --name mf6/example \
  --output .registry
```

This automatically constructs:
```
https://github.com/MODFLOW-ORG/modflow6-examples/releases/download/current/mf6examples.zip
```

---

## What's Next?

### Upstream CI (In Progress)
Add `.github/workflows/registry.yml` to model repositories:

**For version-controlled models** (e.g., testmodels):
```yaml
- name: Generate registry
  run: |
    # Path in repo auto-detected from directory structure (no git required!)
    python -m modflow_devtools.make_registry \
      --path ./mf6 \
      --mode version \
      --repo MODFLOW-ORG/modflow6-testmodels \
      --ref ${{ github.ref_name }} \
      --name mf6/test \
      --output .registry

- name: Commit registry
  run: |
    git add .registry/models.toml
    git commit -m "Update registry [skip ci]"
    git push
```

**For release asset models** (e.g., examples):
```yaml
- name: Generate registry
  run: |
    python -m modflow_devtools.make_registry \
      --path ./examples \
      --mode release \
      --repo MODFLOW-ORG/modflow6-examples \
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

### Future Enhancements
- Registry compression for faster downloads?
- Partial registry updates (diffs)?
- Registry CDN for global access?
- Offline mode with explicit flag?

---

## Summary

The new Models API transforms how we access MODFLOW test models:

| Aspect | v1.x | v2.x |
|--------|------|------|
| **Registry storage** | Bundled TOML files (1.7MB+) | On-demand sync from repos |
| **Model updates** | Package release required | Available immediately |
| **Versioning** | Implicit (package version) | Explicit (git refs) |
| **Customization** | Difficult | User config overlay |
| **Maintenance** | Manual regeneration | Automated CI |
| **Package size** | Large | Minimal |
| **Registry creation** | Manual URL construction | Mode-based with auto URL construction |
| **Path detection** | Manual specification | Automatic from directory structure |

**The result**: A more flexible, maintainable, and user-friendly system! 🎉
