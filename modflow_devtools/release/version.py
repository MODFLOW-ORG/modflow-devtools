"""
Get or set a program's version.

The version lives in the ``version`` keyword of meson.build's ``project()``
call (``version: 'X.Y.Z'``), or in version.txt when the project reads it with
``version: files('version.txt')``. Setting the version also updates
``version = "..."`` in pixi.toml, when present, and any extra files listed in
release.toml:

    [[version-files]]
    path = "src/mfusg.f"
    # one capture group, holding the text to replace
    pattern = "PARAMETER \\(VERSION='([^']*)'\\)"
    # optional; {version} and {date} (UTC) are available
    format = "{version} {date:%m/%d/%Y}"

Every file is checked before any is written, so a failed update changes
nothing. Release versions are X.Y.Z, development versions X.Y.Z.devN.
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

PROJECT = re.compile(r"^\s*project\s*\(", re.M)
# \b keeps meson_version from matching
MESON_LITERAL = re.compile(r"\bversion\s*:\s*'([^']*)'")
MESON_FILE = re.compile(r"\bversion\s*:\s*files\(\s*'([^']*)'\s*\)")
VERSION_TXT = re.compile(r"\A\s*(\S+)\s*\Z")
PIXI = re.compile(r'^version\s*=\s*"([^"]*)"', re.M)


@dataclass
class Target:
    path: Path
    pattern: re.Pattern
    format: str = "{version}"
    # the part of the file to search, (start, end); None for all of it
    span: tuple[int, int] | None = None

    def matches(self, text):
        start, end = self.span or (0, len(text))
        return list(self.pattern.finditer(text, start, end))


def read(path):
    with Path(path).open(newline="") as f:
        return f.read()


def write(path, text):
    with Path(path).open("w", newline="") as f:
        f.write(text)


def project_span(text):
    """The span of meson.build's project(...) call: from its opening to its
    closing parenthesis, skipping strings and comments."""
    match = PROJECT.search(text)
    if match is None:
        return None
    depth, i, n = 1, match.end(), len(text)
    while i < n:
        if text.startswith("'''", i):
            close = text.find("'''", i + 3)
            i = n if close < 0 else close + 3
            continue
        c = text[i]
        if c == "'":
            # meson strings can't span lines, and escape with backslash
            i += 1
            while i < n and text[i] not in "'\n":
                i += 2 if text[i] == "\\" else 1
        elif c == "#":
            close = text.find("\n", i)
            i = n if close < 0 else close
            continue
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return match.start(), i + 1
        i += 1
    return None


def source(root):
    """The file that holds the version, and a pattern matching it."""
    meson = root / "meson.build"
    if not meson.is_file():
        sys.exit(f"no meson.build in {root}")
    text = read(meson)
    span = project_span(text)
    if span is None:
        sys.exit("no project() in meson.build")
    match = MESON_FILE.search(text, *span)
    if match:
        return Target(root / match.group(1), VERSION_TXT)
    if MESON_LITERAL.search(text, *span):
        return Target(meson, MESON_LITERAL, span=span)
    sys.exit("no version in meson.build's project()")


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


def files(root):
    """Paths of every file the version is written to, relative to root."""
    return [t.path.relative_to(root).as_posix() for t in targets(root)]


def get_version(root):
    target = source(root)
    matches = target.matches(read(target.path))
    if not matches:
        sys.exit(f"no version in {target.path.name}")
    return matches[0].group(1)


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
    # check every target before writing any
    updates = []
    for target in targets(root):
        name = target.path.relative_to(root).as_posix()
        if not target.path.is_file():
            sys.exit(f"no file {name}")
        text = read(target.path)
        matches = target.matches(text)
        if len(matches) != 1:
            sys.exit(f"expected one version in {name}, found {len(matches)}")
        value = target.format.format(version=version, date=date)
        start, end = matches[0].span(1)
        updates.append((target.path, name, text[:start] + value + text[end:], value))
    for path, name, text, value in updates:
        write(path, text)
        print(f"{name}: {value}")


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
    group.add_argument(
        "--files", action="store_true", help="print the files the version is written to"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.get:
        print(get_version(root))
    elif args.next:
        print(next_version(get_version(root)))
    elif args.is_release:
        return 0 if RELEASE.match(get_version(root)) else 1
    elif args.files:
        print("\n".join(files(root)))
    else:
        set_version(root, args.set)
    return 0


if __name__ == "__main__":
    sys.exit(main())
