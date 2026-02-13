"""
Version management API.

Provides functions to read and update version strings in version.txt,
meson.build, and pixi.toml. Also supports updating version strings in
arbitrary files via regex pattern and format string.
"""

import re
import sys
from pathlib import Path


def get_version(root: Path) -> str:
    """
    Read the current version from version.txt.

    Parameters
    ----------
    root : Path
        Project root directory containing version.txt.

    Returns
    -------
    str
        Version string.

    Raises
    ------
    FileNotFoundError
        If version.txt does not exist.
    """
    path = root / "version.txt"
    if not path.exists():
        raise FileNotFoundError(f"version.txt not found in {root}")
    return path.read_text().strip()


def _update_version_txt(root: Path, version: str, dry_run: bool = False) -> None:
    path = root / "version.txt"
    if not path.exists():
        raise FileNotFoundError(f"version.txt not found in {root}")
    old = path.read_text().strip()
    if dry_run:
        print(f"  version.txt: {old} -> {version}")
        return
    path.write_text(version)
    print(f"Updated version.txt: {old} -> {version}")


def _update_meson_build(root: Path, version: str, dry_run: bool = False) -> None:
    path = root / "meson.build"
    if not path.exists():
        print(f"Warning: meson.build not found in {root}, skipping", file=sys.stderr)
        return

    lines = path.read_text().splitlines(keepends=True)
    new_lines = []
    old_version = None
    for line in lines:
        if "version:" in line and "meson_version:" not in line:
            m = re.search(r"version:\s*'([^']*)'", line)
            if m:
                old_version = m.group(1)
                line = line[: m.start(1)] + version + line[m.end(1) :]
        new_lines.append(line)

    if old_version is None:
        print("Warning: version field not found in meson.build, skipping", file=sys.stderr)
        return

    if dry_run:
        print(f"  meson.build: {old_version} -> {version}")
        return

    path.write_text("".join(new_lines))
    print(f"Updated meson.build: {old_version} -> {version}")


def _update_pixi_toml(root: Path, version: str, dry_run: bool = False) -> None:
    path = root / "pixi.toml"
    if not path.exists():
        print(f"Warning: pixi.toml not found in {root}, skipping", file=sys.stderr)
        return

    text = path.read_text()
    pattern = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
    m = pattern.search(text)
    if not m:
        print("Warning: version field not found in pixi.toml, skipping", file=sys.stderr)
        return

    old_m = re.search(r'^version\s*=\s*"([^"]*)"', text, re.MULTILINE)
    old_version = old_m.group(1) if old_m else "?"

    new_text = pattern.sub(rf"\g<1>{version}\g<2>", text)

    if dry_run:
        print(f"  pixi.toml: {old_version} -> {version}")
        return

    path.write_text(new_text)
    print(f"Updated pixi.toml: {old_version} -> {version}")


def update_file(
    path: Path,
    pattern: str,
    fmt: str,
    version: str,
    dry_run: bool = False,
) -> None:
    """
    Update a version string in an arbitrary file using a regex pattern and
    a format string.

    Parameters
    ----------
    path : Path
        Path to the file to update.
    pattern : str
        Regular expression with exactly one capture group matching the
        current version string within the line.
    fmt : str
        Python format string for the replacement, must contain ``{version}``.
        Replaces the entire regex match (not just the captured group).
    version : str
        New version string.
    dry_run : bool
        If True, print what would change without modifying the file.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the pattern does not have exactly one capture group, or the
        format string does not contain ``{version}``.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    compiled = re.compile(pattern)

    if compiled.groups != 1:
        raise ValueError(
            f"Pattern must have exactly one capture group, got {compiled.groups}: {pattern!r}"
        )
    if "{version}" not in fmt:
        raise ValueError(f"Format string must contain {{version}}: {fmt!r}")

    text = path.read_text()
    m = compiled.search(text)
    if not m:
        print(f"Warning: pattern not found in {path.name}, skipping", file=sys.stderr)
        return

    old_version = m.group(1)
    replacement = fmt.format(version=version)
    new_text = compiled.sub(replacement, text)

    if dry_run:
        print(f"  {path.name}: {old_version} -> {version}")
        return

    path.write_text(new_text)
    print(f"Updated {path.name}: {old_version} -> {version}")


def set_version(
    version: str,
    root: Path,
    dry_run: bool = False,
    file: Path | None = None,
    pattern: str | None = None,
    fmt: str | None = None,
) -> None:
    """
    Set the version in version.txt, meson.build, and pixi.toml.

    Optionally also update an additional file using a regex pattern and
    format string (e.g. a Fortran source file).

    Parameters
    ----------
    version : str
        New version string. Must be a valid PEP 440 version.
    root : Path
        Project root directory.
    dry_run : bool
        If True, print what would change without modifying any files.
    file : Path, optional
        Additional file to update.
    pattern : str, optional
        Regex pattern for the additional file (required if file is given).
    fmt : str, optional
        Format string for the additional file replacement (required if file is given).

    Raises
    ------
    ValueError
        If the version string is not valid, or if file is given without
        pattern/fmt, or if the pattern/fmt fail validation.
    FileNotFoundError
        If version.txt does not exist in root, or if the additional file
        does not exist.
    """
    from packaging.version import InvalidVersion, Version

    try:
        Version(version)
    except InvalidVersion as e:
        raise ValueError(f"Invalid version {version!r}: {e}") from e

    if dry_run:
        print("Dry run - no files will be modified:")

    _update_version_txt(root, version, dry_run)
    _update_meson_build(root, version, dry_run)
    _update_pixi_toml(root, version, dry_run)

    if file is not None:
        if pattern is None or fmt is None:
            raise ValueError("--file requires both --pattern and --format")
        update_file(file, pattern, fmt, version, dry_run)


__all__ = [
    "get_version",
    "set_version",
    "update_file",
]
