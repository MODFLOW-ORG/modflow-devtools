"""
Update CHANGELOG.md for a release, or print a release's notes from it.

``update`` runs git-cliff with the repo's cliff.toml, or with the shared
template (cliff.toml beside this script) filled in with the
repository and the program's long name. ``notes`` prints the section of
CHANGELOG.md for one version, which becomes the GitHub release notes.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent / "cliff.toml"
HEADING = re.compile(r"^## Version (\S+)")


def config(root, repository, long_name):
    own = root / "cliff.toml"
    if own.is_file():
        return own
    text = TEMPLATE.read_text()
    text = text.replace("__REPOSITORY__", repository).replace("__NAME__", long_name)
    tmp = Path(tempfile.mkdtemp()) / "cliff.toml"
    tmp.write_text(text)
    return tmp


def update(root, version, repository, long_name):
    cliff = shutil.which("git-cliff")
    if cliff is None:
        sys.exit("git-cliff is not installed")
    changelog = root / "CHANGELOG.md"
    cmd = [
        cliff,
        "--config",
        str(config(root, repository, long_name)),
        "--unreleased",
        "--tag",
        f"v{version}",
    ]
    # --prepend keeps the existing file's header and earlier sections
    cmd += ["--prepend", str(changelog)] if changelog.is_file() else ["-o", str(changelog)]
    subprocess.run(cmd, cwd=root, check=True)


def notes(root, version):
    changelog = root / "CHANGELOG.md"
    if not changelog.is_file():
        sys.exit("no CHANGELOG.md")
    lines, found = [], False
    for line in changelog.read_text().splitlines():
        match = HEADING.match(line)
        if match:
            if found:
                break
            found = match.group(1) == version
            continue
        if found:
            lines.append(line)
    if not found:
        sys.exit(f"no section for version {version} in CHANGELOG.md")
    return "\n".join(lines).strip() + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("update", help="prepend this release to CHANGELOG.md")
    up.add_argument("--version", required=True)
    up.add_argument("--repository", required=True, help="owner/repo")
    up.add_argument("--long-name", required=True)
    no = sub.add_parser("notes", help="print one version's section")
    no.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "update":
        update(root, args.version, args.repository, args.long_name)
    else:
        sys.stdout.write(notes(root, args.version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
