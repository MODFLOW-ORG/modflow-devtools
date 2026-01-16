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


def get_release_assets(repo: str, tag: str) -> list[dict]:
    """
    Get release assets for a GitHub release.

    Parameters
    ----------
    repo : str
        Repository in "owner/name" format
    tag : str
        Release tag

    Returns
    -------
    list[dict]
        List of asset dictionaries from GitHub API
    """
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
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
  # Generate registry for MODFLOW 6 release
  python -m modflow_devtools.programs.make_registry \\
    --repo MODFLOW-ORG/modflow6 \\
    --tag 6.6.3 \\
    --programs mf6 zbud6 libmf6 mf5to6 \\
    --output programs.toml

  # Generate with manual program metadata
  python -m modflow_devtools.programs.make_registry \\
    --repo MODFLOW-ORG/modflow6 \\
    --tag 6.6.3 \\
    --program mf6 --version 6.6.3 --description "MODFLOW 6" \\
    --output programs.toml

  # Include hashes for verification
  python -m modflow_devtools.programs.make_registry \\
    --repo MODFLOW-ORG/modflow6 \\
    --tag 6.6.3 \\
    --programs mf6 zbud6 \\
    --compute-hashes \\
    --output programs.toml
""",
    )
    parser.add_argument(
        "--repo",
        required=True,
        type=str,
        help='Repository in "owner/name" format (e.g., MODFLOW-ORG/modflow6)',
    )
    parser.add_argument(
        "--tag",
        required=True,
        type=str,
        help="Release tag (e.g., 6.6.3)",
    )
    parser.add_argument(
        "--programs",
        nargs="+",
        required=True,
        help="Program names to include in registry",
    )
    parser.add_argument(
        "--version",
        help="Program version (defaults to tag)",
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

    # Get release assets
    if args.verbose:
        print(f"Fetching release assets for {args.repo}@{args.tag}...")

    try:
        assets = get_release_assets(args.repo, args.tag)
    except Exception as e:
        print(f"Error fetching release assets: {e}", file=sys.stderr)
        sys.exit(1)

    if not assets:
        print(f"No assets found for release {args.tag}", file=sys.stderr)
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

    # Use tag as version if not specified
    version = args.version or args.tag

    # Platform mappings for common names
    platform_map = {
        "linux": ["linux", "ubuntu"],
        "mac": ["mac", "osx", "darwin"],
        "win64": ["win64", "win"],
    }

    temp_dir = None
    if args.compute_hashes:
        temp_dir = Path(tempfile.mkdtemp(prefix="programs-registry-"))

    try:
        # Process each program
        for program_name in args.programs:
            if args.verbose:
                print(f"\nProcessing program: {program_name}")

            program_meta = {
                "version": version,
                "repo": args.repo,
            }

            if args.description:
                program_meta["description"] = args.description
            if args.license:
                program_meta["license"] = args.license

            # Find binaries for this program
            binaries = {}

            for asset in assets:
                asset_name = asset["name"]
                asset_url = asset["browser_download_url"]

                # Try to match asset to platform
                asset_lower = asset_name.lower()
                matched_platform = None

                for platform, keywords in platform_map.items():
                    if any(keyword in asset_lower for keyword in keywords):
                        matched_platform = platform
                        break

                if not matched_platform:
                    if args.verbose:
                        print(f"  Skipping asset (no platform match): {asset_name}")
                    continue

                if args.verbose:
                    print(f"  Found {matched_platform} asset: {asset_name}")

                # Create binary entry
                binary = {
                    "asset": asset_name,
                    "exe": f"bin/{program_name}",  # Default executable path
                }

                # Compute hash if requested
                if args.compute_hashes:
                    if args.verbose:
                        print("    Downloading to compute hash...")

                    asset_path = temp_dir / asset_name
                    download_asset(asset_url, asset_path)
                    hash_value = compute_sha256(asset_path)
                    binary["hash"] = f"sha256:{hash_value}"

                    if args.verbose:
                        print(f"    SHA256: {hash_value}")

                binaries[matched_platform] = binary

            if binaries:
                program_meta["binaries"] = binaries
                registry["programs"][program_name] = program_meta

                if args.verbose:
                    print(f"  Added {program_name} with {len(binaries)} platform(s)")
            else:
                if args.verbose:
                    print(f"  Warning: No binaries found for {program_name}")

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
