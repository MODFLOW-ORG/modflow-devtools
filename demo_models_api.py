"""
Demo: New Models API (v2.0) - Dynamic Registry System

This script demonstrates the new dynamic registry system for accessing
MODFLOW test models from remote repositories.

Key Features:
- No more bundled 1.7MB+ TOML files in the package
- Model repositories publish their own registries
- Sync on-demand to any git ref (branch, tag, commit hash)
- User config overlay for custom/forked repositories
"""

from pathlib import Path

from modflow_devtools.models import cache, discovery, sync

print("=" * 70)
print("MODFLOW DevTools - New Models API Demo")
print("=" * 70)

# ===========================================================================
# 1. Bootstrap Configuration - Where to Find Model Repositories
# ===========================================================================
print("\n[Step 1] Load Bootstrap Configuration")
print("-" * 70)

# Load the bootstrap file (with user config overlay)
bootstrap = discovery.load_bootstrap()

print(f"Configured sources: {len(bootstrap.sources)}")
for name, source in bootstrap.sources.items():
    print(f"  • {name}")
    print(f"    Repository: {source.repo}")
    print(f"    Name/Prefix: {source.name}")
    print(f"    Default refs: {source.refs}")

# ===========================================================================
# 2. Registry Discovery - Find Remote Registries
# ===========================================================================
print("\n[Step 2] Discover Remote Registry")
print("-" * 70)

# Pick a source to demonstrate
demo_source = bootstrap.sources["modflow6-testmodels"]
demo_ref = demo_source.refs[0]  # First configured ref

print(f"Discovering registry for: {demo_source.name}@{demo_ref}")
print(f"Repository: {demo_source.repo}")

try:
    discovered = discovery.discover_registry(demo_source, demo_ref)
    print("[OK] Registry discovered!")
    print(f"  Mode: {discovered.mode}")
    print(f"  URL: {discovered.url}")
    print(f"  Models: {len(discovered.registry.models)}")
    print(f"  Files: {len(discovered.registry.files)}")
except discovery.RegistryDiscoveryError as e:
    print(f"[ERROR] Discovery failed: {e}")

# ===========================================================================
# 3. Registry Synchronization - Cache Registries Locally
# ===========================================================================
print("\n[Step 3] Synchronize Registry to Local Cache")
print("-" * 70)

# Sync a specific source/ref
print(f"Syncing {demo_source.name}@{demo_ref}...")
result = sync.sync_registry(source="modflow6-testmodels", ref=demo_ref, verbose=True)

print("\nSync results:")
print(f"  Synced: {len(result.synced)}")
print(f"  Skipped: {len(result.skipped)}")
print(f"  Failed: {len(result.failed)}")

if result.synced:
    print("  Successfully synced:")
    for source, ref in result.synced:
        print(f"    • {source}@{ref}")

if result.skipped:
    print("  Skipped (already cached):")
    for source, ref, reason in result.skipped:
        print(f"    • {source}@{ref} - {reason}")

# ===========================================================================
# 4. Using BootstrapSource Methods - Convenience API
# ===========================================================================
print("\n[Step 4] BootstrapSource Convenience Methods")
print("-" * 70)

# Check if a ref is synced
if demo_source.is_synced(demo_ref):
    print(f"[OK] {demo_source.name}@{demo_ref} is cached")
else:
    print(f"[NOT CACHED] {demo_source.name}@{demo_ref} is not cached")

# List all synced refs for this source
synced_refs = demo_source.list_synced_refs()
print(f"\nSynced refs for {demo_source.name}: {synced_refs}")

# Sync via source method (alternative to sync_registry)
# result = demo_source.sync(ref=demo_ref, verbose=True)

# ===========================================================================
# 5. Cache Management - Inspect What's Cached
# ===========================================================================
print("\n[Step 5] Cache Management")
print("-" * 70)

# Get cache locations
cache_root = cache.get_cache_root()
print(f"Cache root: {cache_root}")

models_cache = cache.get_models_cache_dir()
print(f"Models cache: {models_cache}")

# List all cached registries
cached = cache.list_cached_registries()
print(f"\nCached registries: {len(cached)}")
for source, ref in cached:
    print(f"  • {source}@{ref}")

# ===========================================================================
# 6. Working with Cached Registries - Load and Use Models
# ===========================================================================
print("\n[Step 6] Load and Use Cached Registry")
print("-" * 70)

# Load a cached registry
if cache.is_registry_cached(demo_source.name, demo_ref):
    registry = cache.load_cached_registry(demo_source.name, demo_ref)

    print(f"Registry: {demo_source.name}@{demo_ref}")
    print(f"  Schema version: {registry.schema_version}")
    print(f"  Generated at: {registry.generated_at}")
    print(f"  DevTools version: {registry.devtools_version}")
    print(f"\n  Total models: {len(registry.models)}")
    print(f"  Total files: {len(registry.files)}")

    # Show some example models
    print("\n  Example models (first 5):")
    for model_name in list(registry.models.keys())[:5]:
        num_files = len(registry.models[model_name])
        print(f"    • {model_name} ({num_files} files)")

    # Show examples if available
    if registry.examples:
        print(f"\n  Examples: {len(registry.examples)}")
        for example_name in list(registry.examples.keys())[:3]:
            models = registry.examples[example_name]
            print(f"    • {example_name} ({len(models)} models)")

# ===========================================================================
# 7. User Config Overlay - Custom/Fork Repositories
# ===========================================================================
print("\n[Step 7] User Config Overlay")
print("-" * 70)

user_config_path = discovery.get_user_config_path()
print(f"User config location: {user_config_path}")

if user_config_path.exists():
    print("[OK] User config found!")
    print("\nUser config overrides:")

    # Load without user config to compare
    bundled = discovery.load_bootstrap(
        bootstrap_path=Path(__file__).parent
        / "modflow_devtools"
        / "models"
        / "models.toml"
    )

    # Load with user config
    merged = discovery.load_bootstrap()

    # Find differences
    for name, source in merged.sources.items():
        if name in bundled.sources:
            if source.repo != bundled.sources[name].repo:
                print(f"  • {name}:")
                print(f"    Bundled: {bundled.sources[name].repo}")
                print(f"    Override: {source.repo}")
else:
    print("[INFO] No user config found")
    print(f"       Create one at: {user_config_path}")

# ===========================================================================
# Summary
# ===========================================================================
print("\n" + "=" * 70)
print("[SUCCESS] Demo Complete!")
print("=" * 70)
print("\nNext Steps:")
print("  • Use CLI: python -m modflow_devtools.models sync")
print("  • Get info: python -m modflow_devtools.models info")
print("  • List models: python -m modflow_devtools.models list")
print("  • Clear cache: python -m modflow_devtools.models clean")
