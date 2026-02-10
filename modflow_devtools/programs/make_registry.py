"""
Generate a programs.toml registry file for a program release.

This tool helps create registry metadata for program releases, which can then
be published as release assets for the Programs API to discover and sync.

The registry includes program metadata (version, description, license) and
platform-specific binary information (asset filename, hash, executable path).
"""

import argparse
import hashlib
import sys
import tempfile
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

import requests  # type: ignore[import-untyped]
import tomli_w

import modflow_devtools


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_release_assets(repo: str, version: str) -> list[dict]:
    """
    Get release assets for a GitHub release.

    Parameters
    ----------
    repo : str
        Repository in "owner/name" format
    version : str
        Release version (tag)

    Returns
    -------
    list[dict]
        List of asset dictionaries from GitHub API
    """
    url = f"https://api.github.com/repos/{repo}/releases/tags/{version}"
    response = requests.get(url)
    response.raise_for_status()
    release_data = response.json()
    return release_data.get("assets", [])


def download_asset(asset_url: str, output_path: Path) -> None:
    """Download a release asset."""
    response = requests.get(asset_url, stream=True)
    response.raise_for_status()

    with output_path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a programs.toml registry file for a program release.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate registry from local distribution files (for CI)
  python -m modflow_devtools.programs.make_registry \\
    --dists *.zip \\
    --programs mf6 zbud6 libmf6 mf5to6 \\
    --version 6.6.3 \\
    --repo MODFLOW-ORG/modflow6 \\
    --compute-hashes \\
    --output programs.toml

  # Generate registry from existing GitHub release (for testing)
  python -m modflow_devtools.programs.make_registry \\
    --repo MODFLOW-ORG/modflow6 \\
    --version 6.6.3 \\
    --programs mf6 zbud6 libmf6 mf5to6 \\
    --output programs.toml

  # With custom exe paths
  python -m modflow_devtools.programs.make_registry \\
    --dists *.zip \\
    --program mf6:bin/mf6 \\
    --program zbud6:bin/zbud6 \\
    --version 6.6.3 \\
    --repo MODFLOW-ORG/modflow6
""",
    )
    parser.add_argument(
        "--repo",
        required=False,
        type=str,
        help='Repository in "owner/name" format (e.g., MODFLOW-ORG/modflow6) [required]',
    )
    parser.add_argument(
        "--dists",
        type=str,
        help="Glob pattern for local distribution files (e.g., *.zip) [for CI mode]",
    )
    parser.add_argument(
        "--programs",
        nargs="+",
        required=True,
        help="Program names to include (optionally with custom exe path: name:path)",
    )
    parser.add_argument(
        "--version",
        required=False,
        help="Program version",
    )
    parser.add_argument(
        "--description",
        help="Program description",
    )
    parser.add_argument(
        "--license",
        help="License identifier (e.g., CC0-1.0)",
    )
    parser.add_argument(
        "--compute-hashes",
        action="store_true",
        help="Download assets and compute SHA256 hashes (recommended for verification)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="programs.toml",
        help="Output file path (default: programs.toml)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show verbose output",
    )
    args = parser.parse_args()

    # Validate arguments
    if args.dists:
        # Local files mode
        if not args.repo:
            print("Error: --repo is required", file=sys.stderr)
            sys.exit(1)
        if not args.version:
            print("Error: --version is required when using --dists", file=sys.stderr)
            sys.exit(1)
    else:
        # GitHub release mode
        if not args.repo:
            print("Error: --repo is required when not using --dists", file=sys.stderr)
            sys.exit(1)

    # Parse programs (support name:path syntax)
    program_exes = {}
    for prog_spec in args.programs:
        if ":" in prog_spec:
            name, exe = prog_spec.split(":", 1)
            program_exes[name] = exe
        else:
            program_exes[prog_spec] = f"bin/{prog_spec}"  # Default path

    # Get distribution files
    if args.dists:
        # Local files mode: scan for files matching pattern

        dist_files = glob(args.dists)  # noqa: PTH207
        if not dist_files:
            print(f"No files found matching pattern: {args.dists}", file=sys.stderr)
            sys.exit(1)

        if args.verbose:
            print(f"Found {len(dist_files)} distribution file(s)")

        # Convert to asset-like structure
        assets = []
        for file_path in dist_files:
            assets.append(
                {
                    "name": Path(file_path).name,
                    "local_path": file_path,
                }
            )
    else:
        # GitHub release mode: fetch from GitHub API
        if args.verbose:
            print(f"Fetching release assets for {args.repo}@{args.version}...")

        try:
            assets = get_release_assets(args.repo, args.version)
        except Exception as e:
            print(f"Error fetching release assets: {e}", file=sys.stderr)
            sys.exit(1)

        if not assets:
            print(f"No assets found for release {args.version}", file=sys.stderr)
            sys.exit(1)

        if args.verbose:
            print(f"Found {len(assets)} release assets")

    # Build registry structure
    registry = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "devtools_version": modflow_devtools.__version__,
        "programs": {},
    }

    # Distribution name mappings for filenames
    dist_map = {
        "linux": ["linux", "ubuntu"],
        "mac": ["mac", "osx", "darwin"],
        "macarm": ["macarm", "mac_arm", "mac-arm"],
        "win64": ["win64"],
        "win64ext": ["win64ext"],
        "win32": ["win32"],
    }

    temp_dir = None
    if args.compute_hashes:
        temp_dir = Path(tempfile.mkdtemp(prefix="programs-registry-"))

    try:
        # Process each program
        for program_name in program_exes.keys():
            if args.verbose:
                print(f"\nProcessing program: {program_name}")

            program_meta = {
                "version": args.version,
                "repo": args.repo,
                "exe": program_exes[program_name],  # Get exe path for this program
            }

            if args.description:
                program_meta["description"] = args.description
            if args.license:
                program_meta["license"] = args.license

            # Find distributions for this program
            dists = []

            for asset in assets:
                asset_name = asset["name"]

                # Try to match asset to distribution name
                asset_lower = asset_name.lower()
                matched_dist = None

                # Try to match distribution name from filename
                # Check longest names first to match win64ext before win64
                for dist_name in sorted(dist_map.keys(), key=len, reverse=True):
                    keywords = dist_map[dist_name]
                    if any(keyword in asset_lower for keyword in keywords):
                        matched_dist = dist_name
                        break

                if not matched_dist:
                    if args.verbose:
                        print(f"  Skipping asset (no distribution match): {asset_name}")
                    continue

                if args.verbose:
                    print(f"  Found {matched_dist} distribution: {asset_name}")

                # Create distribution entry
                dist = {
                    "name": matched_dist,
                    "asset": asset_name,
                }

                # Compute hash if requested
                if args.compute_hashes:
                    if args.verbose:
                        print("    Computing hash...")

                    if args.dists:
                        # Local file - use local_path
                        asset_path = Path(asset["local_path"])
                    else:
                        # GitHub release - download first
                        if args.verbose:
                            print("    Downloading to compute hash...")
                        asset_url = asset["browser_download_url"]
                        asset_path = temp_dir / asset_name
                        download_asset(asset_url, asset_path)

                    hash_value = compute_sha256(asset_path)
                    dist["hash"] = f"sha256:{hash_value}"

                    if args.verbose:
                        print(f"    SHA256: {hash_value}")

                dists.append(dist)

            if dists:
                program_meta["dists"] = dists
                registry["programs"][program_name] = program_meta

                if args.verbose:
                    print(f"  Added {program_name} with {len(dists)} distribution(s)")
            else:
                if args.verbose:
                    print(f"  Warning: No distributions found for {program_name}")

        # Write registry to file
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("wb") as f:
            tomli_w.dump(registry, f)

        if args.verbose:
            print(f"\nRegistry written to: {output_path}")
            print(f"Programs: {len(registry['programs'])}")

        print(f"Successfully generated {output_path}")

    finally:
        # Clean up temp directory
        if temp_dir and temp_dir.exists():
            if args.verbose:
                print(f"\nCleaning up temporary directory: {temp_dir}")
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
