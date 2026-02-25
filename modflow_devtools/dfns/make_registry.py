"""
Registry generation tool for DFN files.

This tool scans a directory of DFN files and generates a registry file
that can be used by the DFNs API for discovery and verification.

Usage:
    python -m modflow_devtools.dfn.make_registry --dfn-path PATH --output FILE [--ref REF]

Example (for MODFLOW 6 CI):
    python -m modflow_devtools.dfn.make_registry \\
        --dfn-path doc/mf6io/mf6ivar/dfn \\
        --output .registry/dfns.toml \\
        --ref ${{ github.ref_name }}
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import tomli_w


def compute_file_hash(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


def scan_dfn_directory(dfn_path: Path) -> dict[str, str]:
    """
    Scan a directory for DFN files and compute their hashes.

    Parameters
    ----------
    dfn_path : Path
        Path to directory containing DFN files.

    Returns
    -------
    dict[str, str]
        Map of filename to SHA256 hash.
    """
    files = {}

    # Find all .dfn files
    for p in sorted(dfn_path.glob("*.dfn")):
        files[p.name] = compute_file_hash(p)

    # Find all .toml files (spec.toml and/or component files)
    for p in sorted(dfn_path.glob("*.toml")):
        files[p.name] = compute_file_hash(p)

    return files


def generate_registry(
    dfn_path: Path,
    output_path: Path,
    ref: str | None = None,
    devtools_version: str | None = None,
) -> None:
    """
    Generate a DFN registry file.

    Parameters
    ----------
    dfn_path : Path
        Path to directory containing DFN files.
    output_path : Path
        Path to write the registry file.
    ref : str, optional
        Git ref this registry is being generated for.
    devtools_version : str, optional
        Version of modflow-devtools generating this registry.
    """
    # Scan directory for files
    files = scan_dfn_directory(dfn_path)

    if not files:
        raise ValueError(f"No DFN files found in {dfn_path}")

    # Get devtools version if not provided
    if devtools_version is None:
        try:
            from modflow_devtools import __version__

            devtools_version = __version__
        except ImportError:
            devtools_version = "unknown"

    # Build registry structure
    registry: dict = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "devtools_version": devtools_version,
    }

    if ref:
        registry["metadata"] = {"ref": ref}

    # Add files section
    registry["files"] = {filename: {"hash": file_hash} for filename, file_hash in files.items()}

    # Write registry file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        tomli_w.dump(registry, f)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m modflow_devtools.dfn.make_registry",
        description="Generate a DFN registry file",
    )
    parser.add_argument(
        "--dfn-path",
        "-d",
        type=Path,
        required=True,
        help="Path to directory containing DFN files",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output path for registry file",
    )
    parser.add_argument(
        "--ref",
        "-r",
        help="Git ref this registry is being generated for",
    )
    parser.add_argument(
        "--devtools-version",
        help="Version of modflow-devtools (default: auto-detect)",
    )

    args = parser.parse_args(argv)

    dfn_path = args.dfn_path.expanduser().resolve()
    output_path = args.output.expanduser().resolve()

    if not dfn_path.exists():
        print(f"Error: DFN path does not exist: {dfn_path}", file=sys.stderr)
        return 1

    if not dfn_path.is_dir():
        print(f"Error: DFN path is not a directory: {dfn_path}", file=sys.stderr)
        return 1

    try:
        generate_registry(
            dfn_path=dfn_path,
            output_path=output_path,
            ref=args.ref,
            devtools_version=args.devtools_version,
        )

        # Report results
        files = scan_dfn_directory(dfn_path)
        print(f"Generated registry: {output_path}")
        print(f"  Files: {len(files)}")
        if args.ref:
            print(f"  Ref: {args.ref}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
