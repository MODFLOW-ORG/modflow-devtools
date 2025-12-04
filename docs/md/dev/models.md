# Dynamic Registry Design Document

## Overview

Transition from a baked-in static registry to a dynamic, branch-aware registry system where model repositories maintain their own registries and `modflow-devtools` syncs to them on-demand.

## Objectives

1. Reduce developer maintenance burden (no manual registry regeneration)
2. Keep package size minimal
3. Allow users to access latest models without package updates
4. Support multiple refs (release tags, branches)
5. Maintain backward compatibility through 1.x series

## Architecture

### Current State (v1.x)
- 1.7MB+ registry TOML files shipped with package
- Fixed to specific snapshot of model repositories
- Manual developer task to regenerate

### Target State (v2.x)
- Bootstrap metadata (~1-2KB) shipped with package
- Registries cached locally, synced from upstream repos
- Automatic registry generation in model repo CI

### Transition (v1.x → v2.x)
- v1.x: Add sync mechanism as optional feature, keep shipping full registry with deprecation warning
- v2.x: Switch to bootstrap-only, require sync for registry access

## Components

### Registry bootstrap file

In this project, registry bootstrap metadata can live in `modflow_devtools/models/bootstrap.toml`.

#### File contents

A `repo` attribute identifies the repository owner and name. 

The name of the section (under `sources.`) will become part of a prefix by which models can be hierarchically addressed. To override the name (thus the prefix as well) a `name` attribute can be provided.

A `registry_path` attribute points to the directory containing the registry database files. This can default to `.registry/` and therefore be optional, only required if overridden.

The `registry_path` **must** contain at least two (2) files:

- `registry.toml`
- `models.toml`

The `registry_path` **may** also contain a file called `examples.toml`.

#### Sample file

```toml
[sources.modflow6-examples]
repo = "MODFLOW-ORG/modflow6-examples"
name = "mf6/example"
dirs = [""]

[sources.modflow6-testmodels]
repo = "MODFLOW-ORG/modflow6-testmodels"
name = "mf6/test"
dirs = [
    "mf6",
    "mf5to6"
]

[sources.modflow6-largetestmodels]
repo = "MODFLOW-ORG/modflow6-largetestmodels"
name = "mf6/large"
```

### Registry Modes

Model repositories operate in one of two distinct modes, depending on how model files are stored and distributed. The mode is **self-describing** - it's determined by attributes in the registry metadata, not by hints in the bootstrap file.

#### Mode 1: In-Repo Models

**Characteristics**:
- Model input files are checked into the repository
- Registry files live in `.registry/` directory on each branch/tag
- Supports both branches and release tags as refs
- Model files fetched individually via GitHub raw content URLs

**Registry metadata** (no asset attributes):
```toml
[_meta]
schema_version = "1.0"
source_repo = "MODFLOW-ORG/modflow6-testmodels"
source_ref = "master"
generated_at = "2025-12-04T14:30:00Z"
devtools_version = "1.9.0"
# No release_asset/registry_asset/models_asset = in-repo mode
```

**Examples**: `modflow6-testmodels`, `modflow6-largetestmodels`

**Registry discovery**: `https://raw.githubusercontent.com/{org}/{repo}/{ref}/.registry/registry.toml`

**Model file URLs**: Individual files via raw content URLs (specified in registry)

#### Mode 2: Release-Only Models

**Characteristics**:
- Model input files are built during release (not in repository)
- Registry files attached to release as assets
- Supports release tags only (branches don't have built models)
- Model files packaged in release zip asset

**Registry metadata** (with asset attributes):

**Option A: Single zip containing both registry and models**
```toml
[_meta]
schema_version = "1.0"
source_repo = "MODFLOW-ORG/modflow6-examples"
source_ref = "v1.2.3"
release_asset = "mf6examples.zip"  # Both registry and models in this zip
generated_at = "2025-12-04T14:30:00Z"
devtools_version = "1.9.0"
```

**Option B: Separate registry and model assets**
```toml
[_meta]
schema_version = "1.0"
source_repo = "MODFLOW-ORG/modflow6-examples"
source_ref = "v1.2.3"
registry_asset = "registry.zip"    # Registry files in this asset
models_asset = "models.zip"        # Model files in this asset
generated_at = "2025-12-04T14:30:00Z"
devtools_version = "1.9.0"
```

**Examples**: `modflow6-examples`

**Registry discovery**: GitHub release assets for the given tag

**Model file URLs**: All point to the release zip asset

#### Mode Detection & Discovery

`PoochRegistry` automatically discovers the mode when syncing:

1. **If ref is a tag**: Try downloading registry from release assets first
2. **Fallback**: Try downloading registry from `.registry/` directory in repository
3. **After loading registry**: Inspect metadata to determine fetch strategy
   - If `release_asset`, `registry_asset`, or `models_asset` present → Release mode
   - Otherwise → In-repo mode

**Error handling**:
```python
# Generic error when registry not found
FileNotFoundError(
    f"Registry for '{source}@{ref}' not found. "
    f"Tried: release assets (if tag) and repository .registry/ directory."
)

# When attempting branch ref on release-only source
# (Will fail at discovery step - no registry in .registry/ dir)
FileNotFoundError(
    f"Registry for '{source}@{ref}' not found at "
    f"https://github.com/{org}/{repo}/blob/{ref}/.registry/registry.toml. "
    f"This source may only support release tags."
)
```

### 2. Registry Schema

**Files per source**:
- `registry.toml` - file hashes and URLs (Pooch format)
- `models.toml` - model name → file list mapping
- `examples.toml` - example name → model list mapping (optional)

**Metadata section**:

All registry files must include a `[_meta]` section with:
- `schema_version`: Registry schema version (currently "1.0")
- `source_repo`: Source repository identifier (e.g., "MODFLOW-ORG/modflow6-examples")
- `source_ref`: Git ref (branch or tag) this registry was built from
- `generated_at`: Timestamp when registry was generated
- `devtools_version`: Version of modflow-devtools used to generate registry

**Mode-specific attributes** (optional, determine fetch strategy):
- `release_asset`: Name of single zip file containing both registry and models (Mode 2, Option A)
- `registry_asset`: Name of zip file containing registry files (Mode 2, Option B)
- `models_asset`: Name of zip file containing model files (Mode 2, Option B)

See **Registry Modes** section above for complete examples of metadata for each mode.

**Validation**: Use `pydantic` for schema validation and versioning

### 3. Cache Structure

**Location**: `~/.cache/modflow-devtools/registries/` (or platform equivalent via Pooch)

**Directory layout**:
```
~/.cache/modflow-devtools/
├── registries/
│   ├── modflow6-examples/
│   │   ├── 1.2.3/          # release tag (if repo publishes releases)
│   │   │   ├── registry.toml
│   │   │   ├── models.toml
│   │   │   └── examples.toml
│   │   ├── master/         # branch
│   │   │   ├── registry.toml
│   │   │   ├── models.toml
│   │   │   └── examples.toml
│   │   └── develop/        # branch
│   │       ├── registry.toml
│   │       ├── models.toml
│   │       └── examples.toml
│   ├── modflow6-testmodels/
│   │   ├── master/
│   │   │   └── ...
│   │   └── develop/
│   │       └── ...
│   └── modflow6-largetestmodels/
│       └── ...
└── models/  # Actual model files, managed by Pooch
    └── ...
```

**Notes**:
- Keep registries for multiple refs cached simultaneously (tags and branches)
- Cache directory named by ref (tag or branch name)
- Enables fast switching between refs
- Model files themselves cached separately by Pooch

### 4. Ref Selection Priority

**Default behavior** (when user doesn't specify a ref):
1. **Latest release tag** (if repo publishes releases - e.g., `1.2.3`)
2. **master branch** (fallback for repos without releases)
3. **develop branch** (fallback for repos without master)

**Rationale**: Prefer stable/official tagged releases, gracefully degrade to branches

**Implementation**:
- Check GitHub API for latest release tag
- If no releases found, fall back to `master` branch
- If `master` doesn't exist, fall back to `develop` branch

**Git Ref Support**:
- **Supported**: Release tags (e.g., `v1.2.3`, `1.2.3`), branch names (e.g., `master`, `develop`, `feature/xyz`)
- **Not supported**: Commit SHAs (registries only generated on branch pushes/releases, not per-commit)
- **Error handling**: If user specifies a commit SHA, emit clear error message explaining limitation

### 5. Sync Mechanism

#### Install-Time Behavior
- **Best-effort sync** on package install (via `setup.py` or similar)
- **Warn if unsuccessful** but allow install to succeed
- **Retry on first import** if sync failed during install
- **Clear user messaging**: "Registry sync failed, remote models unavailable. Run `python -m modflow_devtools.models sync` to retry."

#### Manual Sync Command

**CLI**: `python -m modflow_devtools.models`

**Subcommands**:
```bash
# Sync all sources to default refs (latest release tag → master → develop)
python -m modflow_devtools.models sync

# Sync all sources to specific ref (branch or tag)
python -m modflow_devtools.models sync --ref develop
python -m modflow_devtools.models sync --ref v1.2.3

# Sync specific source
python -m modflow_devtools.models sync --source modflow6-examples

# Sync specific source to specific ref
python -m modflow_devtools.models sync --source modflow6-examples --ref develop
python -m modflow_devtools.models sync --source modflow6-examples --ref v1.2.3

# Force re-download even if cached
python -m modflow_devtools.models sync --force

# List available registries and their status
python -m modflow_devtools.models list

# Show sync status
python -m modflow_devtools.models status
```

**Error handling for unsupported refs**:
```bash
# Commit SHA not supported - clear error message
python -m modflow_devtools.models sync --ref abc123def
# Error: Commit SHAs are not supported. Registries are only generated for branches and release tags.
#        Please use a branch name (e.g., 'master', 'develop') or release tag (e.g., 'v1.2.3').
```

**Programmatic API**:
```python
from modflow_devtools.models import sync_registry, get_registry

# Sync and use default (latest release tag → master → develop)
sync_registry()
registry = get_registry()

# Sync to specific ref (branch or tag)
sync_registry(ref="develop")
sync_registry(ref="v1.2.3")

# Use specific ref without syncing
registry = get_registry(ref="develop")  # uses cached, syncs if missing
registry = get_registry(ref="v1.2.3")   # uses cached release tag

# Use specific source and ref
registry = get_registry(source="modflow6-examples", ref="develop")
registry = get_registry(source="modflow6-examples", ref="v1.2.3")

# Error on commit SHA
try:
    registry = get_registry(ref="abc123def")
except ValueError as e:
    print(e)  # "Commit SHAs are not supported..."
```

#### Sync Implementation
- **For release tags**: Download registry files from GitHub release assets
- **For branches**: Download registry files from GitHub raw URLs (e.g., `https://raw.githubusercontent.com/MODFLOW-ORG/modflow6-examples/{branch}/.registry/registry.toml`)
- Validate schema version and structure
- Cache to local directory (named by ref - tag or branch)
- Merge multiple sources at API level (keep files separate on disk)
- **Ref detection**: Use GitHub API to determine if ref is a tag or branch

### 6. Upstream Model Repository Changes

**Required changes in each model repo** (modflow6-examples, modflow6-testmodels, modflow6-largetestmodels):

#### CI Workflow
**File**: `.github/workflows/registry.yml`

**Trigger**: Push to master/develop branches, or release tag creation

**Steps**:
1. Install `modflow-devtools` (provides registry generation machinery)
2. Run registry generation:
   ```bash
   python -m modflow_devtools.make_registry \
     --path . \
     --output .registry \
     --url <appropriate-base-url>
   ```
3. Commit registry files to `.registry/` directory (for branches)
4. For release tags: Attach registry files as release assets

**Notes**:
- Registry generation machinery remains in `modflow-devtools`
- Model repos consume it as a dependency
- Keeps single source of truth for registry format

#### Directory Structure
```
modflow6-examples/
├── .registry/
│   ├── registry.toml
│   ├── models.toml
│   └── examples.toml
├── examples/
│   └── ...
└── .github/
    └── workflows/
        └── registry.yml
```

### 7. Registry Architecture & API

#### Core Principle: Separation of Concerns

- **`PoochRegistry`**: Single source, single ref - knows nothing about other sources
- **`MergedRegistry`**: Pure compositor - just merges existing registries, no construction logic
- **Module-level functions**: Handle sync, construction, and convenience APIs

#### Model Naming Convention

**Format**: `{source}@{ref}/{subpath}`

**Components**:
- `source`: Repository identifier (e.g., `modflow6-examples`, `modflow6-testmodels`)
- `ref`: Git ref (branch or tag, e.g., `v1.2.3`, `master`, `develop`)
- `subpath`: Relative path within repo to model directory

**Examples**:
- `modflow6-examples@v1.2.3/ex-gwf-twri`
- `modflow6-testmodels@develop/mf6/test001a_Tharmonic`
- `modflow6-largetestmodels@master/prudic2004t2`

**Benefits**:
- Guarantees no name collisions (unique per source + ref + path)
- Makes model provenance explicit to users
- Allows mixing multiple refs of same source
- Simplifies cache key generation

#### PoochRegistry (Single Source)

**Purpose**: Represent a single source repository at a specific ref

**Constructor**: Takes `source` (repo name) and `ref` (branch/tag)

```python
class PoochRegistry(ModelRegistry):
    def __init__(self, source: str, ref: str | None = None, cache_path: PathLike | None = None):
        """Create registry for a single source repository

        Args:
            source: Source repository name (e.g., "modflow6-examples")
            ref: Git ref - branch name or release tag
                 (default: latest release tag → master → develop)
                 Commit SHAs not supported.
            cache_path: Override default cache location

        Raises:
            ValueError: If ref is a commit SHA
            FileNotFoundError: If registry not cached and sync fails
        """
        self._source = source
        self._ref = self._resolve_ref(ref)  # Applies default priority
        self._cache_path = cache_path or self._default_cache_path()
        self._load()  # Load from cache, auto-sync if missing

    @property
    def source(self) -> str:
        """Source repository name"""
        return self._source

    @property
    def ref(self) -> str:
        """Git ref (branch or tag)"""
        return self._ref

    def sync(self, force: bool = False) -> None:
        """Sync this registry from upstream

        Automatically discovers registry location and mode:
        1. If ref is a tag: Try release assets first
        2. Fallback: Try .registry/ directory in repository
        3. After loading: Inspect metadata to determine fetch strategy

        Args:
            force: Re-download even if cached

        Raises:
            FileNotFoundError: If registry not found in either location
        """
        # Try release assets if ref is a tag
        if self._is_tag(self._ref):
            try:
                self._sync_from_release_assets()
                self._setup_pooch()  # Configure based on metadata
                return
            except ReleaseNotFound:
                pass  # Fall through to repository

        # Try .registry/ directory in repository
        try:
            self._sync_from_repository()
            self._setup_pooch()  # Configure based on metadata
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Registry for '{self._source}@{self._ref}' not found. "
                f"Tried: release assets (if tag) and repository .registry/ directory."
            )

    def _setup_pooch(self) -> None:
        """Configure Pooch based on registry metadata (mode detection)"""
        meta = self._meta

        if "release_asset" in meta:
            # Mode 2, Option A: Single zip with registry + models
            self._fetch_mode = "single_zip"
            self._asset_name = meta["release_asset"]

        elif "models_asset" in meta:
            # Mode 2, Option B: Separate registry and model assets
            self._fetch_mode = "models_zip"
            self._asset_name = meta["models_asset"]

        else:
            # Mode 1: In-repo individual files
            self._fetch_mode = "individual_files"
            # URLs already in registry from make_registry.py

    def is_synced(self) -> bool:
        """Check if registry is cached for this source/ref"""
        ...

    # Inherited from ModelRegistry abstract class
    @property
    def files(self) -> dict:
        """Map of file names to file info (with source@ref prefix)"""
        ...

    @property
    def models(self) -> dict:
        """Map of model names to file lists (with source@ref prefix)"""
        ...

    @property
    def examples(self) -> dict:
        """Map of example names to model lists (with source@ref prefix)"""
        ...
```

**Key changes from current**:
- Loads from cache by default (not package resources)
- Auto-syncs if cache missing (best-effort on first access)
- All keys prefixed with `{source}@{ref}/` in returned dicts

#### MergedRegistry (Compositor)

**Purpose**: Merge multiple `ModelRegistry` instances into unified API

**Constructor**: Takes list of pre-constructed registry instances

```python
class MergedRegistry(ModelRegistry):
    def __init__(self, registries: list[ModelRegistry]):
        """Merge multiple registries into unified API

        Args:
            registries: List of ModelRegistry instances (typically PoochRegistry)
                        Caller is responsible for constructing these with desired
                        sources and refs.

        Note:
            This class is a pure compositor - it knows nothing about sources,
            refs, syncing, or construction. All that logic happens before
            MergedRegistry is created.
        """
        self._registries = list(registries)

    @property
    def registries(self) -> list[ModelRegistry]:
        """The underlying registries being merged"""
        return list(self._registries)  # Return copy

    # Inherited from ModelRegistry - merge results from all registries
    @property
    def files(self) -> dict:
        """Merged files from all registries"""
        merged = {}
        for registry in self._registries:
            merged.update(registry.files)
        return merged

    @property
    def models(self) -> dict:
        """Merged models from all registries"""
        merged = {}
        for registry in self._registries:
            merged.update(registry.models)
        return merged

    @property
    def examples(self) -> dict:
        """Merged examples from all registries"""
        merged = {}
        for registry in self._registries:
            merged.update(registry.examples)
        return merged
```

**Why no factory methods?**
- Construction is trivial: `MergedRegistry([reg1, reg2])`
- Users can easily create new instances when refs change
- Keeps the class focused and simple
- Avoids coupling MergedRegistry to PoochRegistry

**Usage examples**:
```python
# Create individual registries
examples_v1 = PoochRegistry("modflow6-examples", "v1.2.3")
testmodels = PoochRegistry("modflow6-testmodels", "develop")

# Merge them
merged = MergedRegistry([examples_v1, testmodels])

# Later: update to new ref
examples_v2 = PoochRegistry("modflow6-examples", "v2.0.0")
merged = MergedRegistry([examples_v2, testmodels])

# Mix multiple refs of same source
examples_stable = PoochRegistry("modflow6-examples", "v1.2.3")
examples_dev = PoochRegistry("modflow6-examples", "develop")
merged = MergedRegistry([examples_stable, examples_dev, testmodels])
```

#### Module-Level API (Convenience Layer)

**Purpose**: Provide convenient access for common use cases

```python
# Module: modflow_devtools.models

def get_registry(
    source: str | None = None,
    ref: str | None = None,
    sources: dict[str, str] | None = None
) -> ModelRegistry:
    """Get a registry (single source or merged)

    Args:
        source: Single source name (returns PoochRegistry)
        ref: Git ref to use (applies to single source or all sources)
        sources: Dict mapping source names to refs for mixed-ref merged registry
                 e.g., {"modflow6-examples": "v1.2.3", "modflow6-testmodels": "develop"}

    Returns:
        PoochRegistry if source specified, otherwise MergedRegistry

    Examples:
        # Single source
        reg = get_registry(source="modflow6-examples", ref="v1.2.3")

        # All sources, same ref
        reg = get_registry(ref="develop")

        # All sources, default refs (latest release → master → develop)
        reg = get_registry()

        # All sources, mixed refs
        reg = get_registry(sources={
            "modflow6-examples": "v1.2.3",
            "modflow6-testmodels": "develop"
        })
    """
    if source:
        return PoochRegistry(source, ref)

    if sources:
        registries = [PoochRegistry(src, r) for src, r in sources.items()]
    else:
        # Load all from bootstrap, apply same ref to all
        bootstrap = load_bootstrap()
        registries = [PoochRegistry(src, ref) for src in bootstrap.sources.keys()]

    return MergedRegistry(registries)


def sync_registry(source: str | None = None, ref: str | None = None, force: bool = False) -> None:
    """Sync registry from upstream

    Args:
        source: Specific source to sync (default: all sources from bootstrap)
        ref: Git ref to sync (default: latest release → master → develop)
        force: Force re-download even if cached
    """
    if source:
        registry = PoochRegistry(source, ref)
        registry.sync(force=force)
    else:
        bootstrap = load_bootstrap()
        for src in bootstrap.sources.keys():
            registry = PoochRegistry(src, ref)
            registry.sync(force=force)


# DEFAULT_REGISTRY is now a MergedRegistry
DEFAULT_REGISTRY = get_registry()  # All sources, default refs
```

### 8. Backward Compatibility (v1.x)

**Goals**:
- Don't break existing code
- Gentle migration path for users
- Clear deprecation warnings

**Approach**:
1. Continue shipping full registry in v1.x
2. Add sync functionality as optional enhancement
3. Emit deprecation warning on import:
   ```
   DeprecationWarning: Bundled registry is deprecated and will be removed in v2.0.
   Use `python -m modflow_devtools.models sync` to download the latest registry.
   ```
4. Provide migration guide in docs

**Breaking changes in v2.x**:
- Remove bundled registry files (except bootstrap.toml)
- Require sync for remote registry access (LocalRegistry unaffected)
- Document migration clearly in CHANGELOG

## Implementation Plan

### Phase 1: Foundation (v1.x)
1. Add bootstrap metadata file
2. Implement registry schema with Pydantic validation
3. Create cache directory structure utilities
4. Add `sync_registry()` function with download logic
5. Implement branch priority resolution
6. Add CLI subcommands (sync, list, status)

### Phase 2: PoochRegistry Adaptation (v1.x)
1. Modify `PoochRegistry.__init__()` to check cache first
2. Add fallback to bundled registry
3. Implement best-effort sync on import
4. Add deprecation warnings for bundled registry

### Phase 3: Upstream CI (concurrent with Phase 1-2)
1. Add `.github/workflows/registry.yml` to each model repo
2. Test registry generation in CI
3. Commit registry files to `.registry/` directories
4. For repos with releases, add registry as release asset

### Phase 4: Testing & Documentation (v1.x)
1. Add comprehensive tests for sync mechanism
2. Test network failure scenarios
3. Document new workflow in `models.md`
4. Add migration guide for v2.x

### Phase 5: v2.x Release
1. Remove bundled registry files (keep bootstrap.toml)
2. Make sync required for PoochRegistry
3. Update documentation
4. Release notes with clear migration instructions

## Key Design Decisions

1. **Install-time sync**: Best-effort, warn on failure, allow install to proceed
2. **Registry location**: `.registry/` directory on each branch in model repos; also as release assets for tagged releases
3. **Bootstrap format**: Minimal TOML with just repo identifiers - no hints about location or fetch strategy
4. **Registry modes**: Self-describing via metadata attributes
   - Mode 1 (in-repo): No asset attributes → individual file fetching
   - Mode 2 (release-only): `release_asset`, `registry_asset`, or `models_asset` → zip fetching
   - Mode discovered automatically during sync
5. **Multi-ref caching**: Support simultaneous caching of multiple refs (tags and branches)
6. **Schema versioning**: Use Pydantic, include `_meta` section in registries
7. **Ref priority**: Latest release tag → master branch → develop branch (when user doesn't specify)
8. **Ref support**: Branch names and release tags supported; commit SHAs not supported (with clear error message)
9. **CLI parameter**: Use `--ref` (not `--branch`) to clarify support for both tags and branches
10. **Transition**: Optional in v1.x with deprecation warning, required in v2.x
11. **Registry architecture**: Clear separation of concerns
    - `PoochRegistry`: Single source, single ref - no knowledge of other sources
    - `MergedRegistry`: Pure compositor - takes pre-built registries, no construction logic
    - Module functions: Handle sync, construction, convenience APIs
12. **Model naming**: `{source}@{ref}/{subpath}` format guarantees collision-free names and explicit provenance
13. **Registry merging**: Keep separate on disk and in separate `PoochRegistry` instances, merge via `MergedRegistry`
14. **No factory methods**: `MergedRegistry` construction is trivial, users create new instances directly
15. **Mixed refs**: Supported naturally via naming scheme - can mix multiple refs of same source
16. **LocalRegistry**: Remains independent, serves different purpose (local development)

## Design Considerations & Risk Mitigation

### Name Collisions
**Risk**: Models from different sources could have identical names.

**Mitigation**: Systematic naming scheme `{source}@{ref}/{subpath}` guarantees uniqueness:
- Each source has distinct identifier
- Refs are included in name
- Subpaths are unique within a source

**Example**: `modflow6-examples@v1.2.3/ex-gwf-twri` cannot collide with `modflow6-testmodels@develop/ex-gwf-twri`

### Partial Sync State
**Risk**: User syncs some sources but not others, leading to incomplete `MergedRegistry`.

**Mitigation**:
- `MergedRegistry` is transparent - only merges what it's given
- Module-level `get_registry()` handles ensuring sources are synced
- `PoochRegistry` auto-syncs on first access (best-effort)
- Clear error messages if sync fails

### Performance
**Risk**: Loading multiple registry files could be slow.

**Analysis**: Not a concern - TOML files load instantly (even 1.7MB registry is trivial). Model files download lazily via Pooch only when accessed.

**Decision**: No lazy loading needed for registries themselves.

### Error Propagation
**Risk**: One source failing to sync could break entire `MergedRegistry`.

**Mitigation**:
- `PoochRegistry` constructor fails fast if sync fails
- Caller (module functions) can handle errors before constructing `MergedRegistry`
- `MergedRegistry` itself is simple - no error handling needed (operates on valid registries)

### Backward Compatibility
**Risk**: Changing `DEFAULT_REGISTRY` from `PoochRegistry` to `MergedRegistry` breaks code checking `isinstance(DEFAULT_REGISTRY, PoochRegistry)`.

**Mitigation**:
- Both implement `ModelRegistry` abstract class
- API is identical for common operations
- Breaking change acceptable for v2.x with clear migration guide
- v1.x maintains current behavior with deprecation warnings

### Cache Invalidation
**Risk**: Registry instance doesn't reflect newly synced data.

**Mitigation**:
- Document that registries are immutable per ref
- To use new data, create new instance: `get_registry(ref="new-ref")`
- Construction is cheap (just loading TOML), so recreating is fine

## Open Questions / Future Enhancements

1. **Registry compression**: Should we gzip registry files for faster downloads?
2. **Partial registry updates**: Could we diff registries and download only changes?
3. **Registry CDN**: Should we consider hosting registries on a CDN for faster access?
4. **Offline mode**: Should we provide an explicit "offline mode" that never tries to sync?
5. **Registry analytics**: Track which models are most frequently accessed?
6. **Naming scheme refinement**: Keep current verbose prefixes (`mf6/example/`, `mf6/test/`) or simplify to `{repo-name}/{subpath}`?

## Success Criteria

1. Package size reduced by ~2MB
2. Users can access latest models without package update
3. Zero manual developer registry updates needed
4. Install always succeeds (even with network failures)
5. Existing v1.x code continues to work with deprecation warnings
6. Clear migration path to v2.x
