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
import tarfile
import tempfile
import zipfile
from glob import glob
from pathlib import Path

import requests  # type: ignore[import-untyped]
import tomli_w


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


def peek_archive_for_exe(archive_path: Path, program_name: str, platform: str) -> str | None:
    """
    Peek inside archive to find executable path.

    Supports both nested (archive_name/bin/program) and flat (bin/program) patterns.

    Parameters
    ----------
    archive_path : Path
        Path to archive file
    program_name : str
        Name of program to find
    platform : str
        Platform name (for determining exe extension)

    Returns
    -------
    str | None
        Path to executable within archive, or None if not found
    """
    # Determine expected executable name
    is_windows = platform.startswith("win")

    # Generate possible executable names
    possible_names = []
    if is_windows:
        possible_names.extend(
            [
                f"{program_name}.exe",
                f"{program_name}.dll",  # For libraries like libmf6
            ]
        )
    else:
        possible_names.extend(
            [
                program_name,
                f"{program_name}.so",  # Linux shared libraries
                f"{program_name}.dylib",  # macOS shared libraries
                f"lib{program_name}.so",  # libmf6.so
                f"lib{program_name}.dylib",  # libmf6.dylib
            ]
        )

    try:
        # List archive contents
        if archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                members = zf.namelist()
        elif archive_path.suffix.lower() in [".gz", ".tgz"]:
            with tarfile.open(archive_path, "r:gz") as tf:
                members = tf.getnames()
        elif archive_path.suffix.lower() == ".tar":
            with tarfile.open(archive_path, "r") as tf:
                members = tf.getnames()
        else:
            return None

        # Search for executable in priority order (executables before libraries)
        for name in possible_names:
            for member in members:
                member_path = Path(member)
                if member_path.name == name:
                    # Found it! Return the path
                    return member.replace("\\", "/")  # Normalize to forward slashes

        return None

    except (zipfile.BadZipFile, tarfile.TarError):
        return None


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
    downloaded_assets = {}  # Cache: asset_name -> Path
    if args.compute_hashes:
        temp_dir = Path(tempfile.mkdtemp(prefix="programs-registry-"))

    try:
        # Process each program
        for program_name in program_exes.keys():
            if args.verbose:
                print(f"\nProcessing program: {program_name}")

            program_meta = {}

            # Only include exe if it differs from the default (bin/{program_name})
            exe_path = program_exes[program_name]
            if exe_path != f"bin/{program_name}":
                program_meta["exe"] = exe_path

            if args.description:
                program_meta["description"] = args.description
            if args.license:
                program_meta["license"] = args.license

            # Find distributions for this program
            dists = []
            dist_exe_paths = {}  # Track exe path for each dist (for pattern detection)

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

                # Get archive path (for exe detection and optional hash computation)
                asset_path = None
                if args.dists:
                    # Local file - always available
                    asset_path = Path(asset["local_path"])
                else:
                    # GitHub release - download if not already cached
                    if asset_name in downloaded_assets:
                        asset_path = downloaded_assets[asset_name]
                    else:
                        # Always download to enable exe detection and pattern optimization
                        if args.verbose:
                            action = (
                                "to compute hash and detect exe path"
                                if args.compute_hashes
                                else "to detect exe path"
                            )
                            print(f"    Downloading {action}...")
                        asset_url = asset["browser_download_url"]
                        asset_path = temp_dir / asset_name
                        download_asset(asset_url, asset_path)
                        downloaded_assets[asset_name] = asset_path

                # Compute hash if requested
                if args.compute_hashes:
                    if args.verbose:
                        print("    Computing hash...")
                    hash_value = compute_sha256(asset_path)
                    dist["hash"] = f"sha256:{hash_value}"
                    if args.verbose:
                        print(f"    SHA256: {hash_value}")

                # Peek inside archive to find exe path (always do this for pattern optimization)
                if asset_path and asset_path.exists():
                    exe_path = peek_archive_for_exe(asset_path, program_name, matched_dist)
                    if exe_path:
                        dist_exe_paths[matched_dist] = exe_path
                        if args.verbose:
                            print(f"    Found exe: {exe_path}")

                dists.append(dist)

            if dists:
                # Optimize: check if all dists follow a consistent pattern
                # Patterns: nested ({asset_stem}/path) or flat (path at archive root)
                if dist_exe_paths and len(dist_exe_paths) == len(dists):
                    # We have exe paths for all distributions
                    # Check if they all follow the same pattern (nested or flat)
                    consistent_pattern = True
                    relative_paths = []
                    is_nested = None  # Will be set to True/False after checking first dist

                    for dist in dists:
                        dist_name = dist["name"]
                        asset_name = dist["asset"]
                        asset_stem = Path(asset_name).stem  # Remove .zip extension

                        if dist_name in dist_exe_paths:
                            exe_path = dist_exe_paths[dist_name]

                            # Check if exe_path starts with asset_stem/ (nested pattern)
                            if exe_path.startswith(f"{asset_stem}/"):
                                # Nested pattern for this dist
                                if is_nested is False:
                                    # Inconsistent: previous dists were flat
                                    consistent_pattern = False
                                    break
                                is_nested = True
                                rel_path = exe_path[
                                    len(asset_stem) + 1 :
                                ]  # Remove asset_stem/ prefix
                                relative_paths.append(rel_path)
                            else:
                                # Flat pattern for this dist (no nested folder)
                                if is_nested is True:
                                    # Inconsistent: previous dists were nested
                                    consistent_pattern = False
                                    break
                                is_nested = False
                                # exe_path is already the relative path
                                relative_paths.append(exe_path)
                        else:
                            consistent_pattern = False
                            break

                    # Are all relative paths the same,
                    # ignoring platform-specific extensions?
                    if consistent_pattern and relative_paths:
                        normalized_paths = set()
                        for rp in relative_paths:
                            normalized = rp
                            for ext in [".exe", ".dll", ".so", ".dylib"]:
                                if normalized.endswith(ext):
                                    normalized = normalized[: -len(ext)]
                                    break
                            normalized_paths.add(normalized)

                        if len(normalized_paths) == 1:
                            common_path = normalized_paths.pop()

                            # Only store exe if it's not in a recognized location:
                            # - {program}
                            # - bin/{program}
                            if common_path not in [f"bin/{program_name}", program_name]:
                                program_meta["exe"] = common_path
                                if args.verbose:
                                    pattern_type = "nested" if is_nested else "flat"
                                    print(f"  Detected {pattern_type} pattern")
                            else:
                                if args.verbose:
                                    pattern_type = "nested" if is_nested else "flat"
                                    print(
                                        f"  Detected {pattern_type} pattern with "
                                        f"default path ({common_path})"
                                    )
                        else:
                            # Different relative paths, need dist-level exe entries
                            for dist in dists:
                                dist_name = dist["name"]
                                if dist_name in dist_exe_paths:
                                    dist["exe"] = dist_exe_paths[dist_name]
                    else:
                        # Pattern not detected, use dist-level exe entries
                        for dist in dists:
                            dist_name = dist["name"]
                            if dist_name in dist_exe_paths:
                                dist["exe"] = dist_exe_paths[dist_name]
                else:
                    # No exe paths found (archives may not be accessible)
                    if args.verbose:
                        print(
                            "  Warning: Could not detect exe paths from archives. "
                            "Registry will use runtime detection."
                        )

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
