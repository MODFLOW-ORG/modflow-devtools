"""
Get or set a program's version.

The version lives in meson.build (``version: 'X.Y.Z'``), or in version.txt
when meson.build reads it with ``version: files('version.txt')``. Setting the
version also updates ``version = "..."`` in pixi.toml, when present, and any
extra files listed in release.toml:

    [[version-files]]
    path = "src/mfusg.f"
    # one capture group, holding the text to replace
    pattern = "PARAMETER \\(VERSION='([^']*)'\\)"
    # optional; {version} and {date} (UTC) are available
    format = "{version} {date:%m/%d/%Y}"

Release versions are X.Y.Z, development versions X.Y.Z.devN.
"""

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RELEASE = re.compile(r"^\d+\.\d+\.\d+$")
DEVELOP = re.compile(r"^\d+\.\d+\.\d+\.dev\d+$")

MESON_LITERAL = re.compile(r"^\s*version\s*:\s*'([^']*)'", re.M)
MESON_FILE = re.compile(r"^\s*version\s*:\s*files\(\s*'([^']*)'\s*\)", re.M)
PIXI = re.compile(r'^version\s*=\s*"([^"]*)"', re.M)


@dataclass
class Target:
    path: Path
    pattern: re.Pattern
    format: str = "{version}"


def read(path):
    with Path(path).open(newline="") as f:
        return f.read()


def write(path, text):
    with Path(path).open("w", newline="") as f:
        f.write(text)


def source(root):
    """The file that holds the version, and a pattern matching it."""
    meson = root / "meson.build"
    if not meson.is_file():
        sys.exit(f"no meson.build in {root}")
    text = read(meson)
    match = MESON_FILE.search(text)
    if match:
        return Target(root / match.group(1), re.compile(r"\A\s*(\S+)\s*\Z"))
    if MESON_LITERAL.search(text):
        return Target(meson, MESON_LITERAL)
    sys.exit("no version in meson.build")


def load_config(root):
    path = root / "release.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def targets(root):
    """Every file the version is written to, the source first."""
    found = [source(root)]
    pixi = root / "pixi.toml"
    if pixi.is_file() and PIXI.search(read(pixi)):
        found.append(Target(pixi, PIXI))
    for entry in load_config(root).get("version-files", []):
        pattern = re.compile(entry["pattern"], re.M)
        if pattern.groups != 1:
            sys.exit(f"pattern for {entry['path']} needs exactly one group")
        found.append(Target(root / entry["path"], pattern, entry.get("format", "{version}")))
    return found


def get_version(root):
    target = source(root)
    match = target.pattern.search(read(target.path))
    if match is None:
        sys.exit(f"no version in {target.path.name}")
    return match.group(1)


def next_version(version):
    """The next minor development version. The dev number is the micro
    version, as in MODFLOW 6, so 1.5.0 gives 1.6.0.dev0 and 1.5.2 gives
    1.6.0.dev2."""
    major, minor, micro = version.split(".")[:3]
    return f"{major}.{int(minor) + 1}.0.dev{int(micro)}"


def set_version(root, version, date=None):
    if not (RELEASE.match(version) or DEVELOP.match(version)):
        sys.exit(f"{version} is not X.Y.Z or X.Y.Z.devN")
    date = date or datetime.now(UTC)
    for target in targets(root):
        text = read(target.path)
        matches = list(target.pattern.finditer(text))
        if len(matches) != 1:
            name = target.path.relative_to(root)
            sys.exit(f"expected one version in {name}, found {len(matches)}")
        match = matches[0]
        value = target.format.format(version=version, date=date)
        start, end = match.span(1)
        write(target.path, text[:start] + value + text[end:])
        print(f"{target.path.relative_to(root).as_posix()}: {value}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--get", action="store_true", help="print the version")
    group.add_argument("--next", action="store_true", help="print the next minor dev version")
    group.add_argument(
        "--is-release",
        action="store_true",
        help="exit 0 if the version is X.Y.Z, else 1",
    )
    group.add_argument("--set", metavar="VERSION", help="set the version")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.get:
        print(get_version(root))
    elif args.next:
        print(next_version(get_version(root)))
    elif args.is_release:
        return 0 if RELEASE.match(get_version(root)) else 1
    else:
        set_version(root, args.set)
    return 0


if __name__ == "__main__":
    sys.exit(main())
