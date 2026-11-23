"""
Zip a program's release archives, the same way on every platform.

Everything under bin/ goes in <ostag>.zip, at the archive root (bin/mfusg
becomes mfusg). On Linux, the source also goes in <name>_source.zip, with
paths relative to the repo root and the name from release.toml. When the
repo is a git checkout, only tracked files go in the source archive. Prints
the OS tag; the archive contents go to stderr.
"""

import argparse
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

from modflow_devtools.release import config

# (sys.platform, machine) -> OS tag; Intel macOS (mac) isn't supported
OSTAGS = {
    ("linux", "x86_64"): "linux",
    ("darwin", "arm64"): "macarm",
    ("win32", "amd64"): "win64",
}
DEFAULT_SOURCE = ["meson.build", "meson.options", "src"]


def ostag():
    key = (sys.platform, platform.machine().lower())
    if key not in OSTAGS:
        sys.exit(f"no OS tag for {key[0]} {key[1]}")
    return OSTAGS[key]


def zip_files(archive, files, base):
    """Zip the files with paths relative to base. ZipFile.write keeps the
    file mode, so executables stay executable."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(files):
            name = path.relative_to(base).as_posix()
            z.write(path, name)
            print(f"{archive.name}: {name}", file=sys.stderr)


def tracked(root, paths):
    """Tracked files under the paths, or None if root isn't a git checkout."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", *paths],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [root / p for p in out.split("\0") if p]


def source_files(root, paths):
    """Files under the paths. Missing paths are an error, except optional
    ones in the default list (meson.options)."""
    if paths is None:
        paths = [p for p in DEFAULT_SOURCE if (root / p).exists() or p != "meson.options"]
    missing = [p for p in paths if not (root / p).exists()]
    if missing:
        sys.exit(f"source paths not found: {' '.join(missing)}")
    files = tracked(root, paths)
    if files is None:
        files = []
        for p in paths:
            path = root / p
            files += [f for f in path.rglob("*") if f.is_file()] if path.is_dir() else [path]
    return [f for f in files if f.is_file()]


def package(root, dist, source_paths=None, tag=None):
    tag = tag or ostag()
    bindir = root / "bin"
    exes = [f for f in bindir.rglob("*") if f.is_file()] if bindir.is_dir() else []
    if not exes:
        sys.exit(f"nothing in {bindir}")
    zip_files(dist / f"{tag}.zip", exes, bindir)
    if tag == "linux" and source_paths != []:
        name, _ = config.names(root)
        zip_files(dist / f"{name}_source.zip", source_files(root, source_paths), root)
    return tag


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    parser.add_argument("--dist", type=Path, required=True, help="directory to write archives to")
    parser.add_argument(
        "--source-paths",
        nargs="*",
        help="paths for the source archive; default meson.build, meson.options "
        "(if present) and src; none to skip it",
    )
    args = parser.parse_args(argv)
    print(package(args.root.resolve(), args.dist.resolve(), args.source_paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
