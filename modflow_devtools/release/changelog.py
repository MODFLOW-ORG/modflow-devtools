"""
Update CHANGELOG.md for a release, or print a release's notes from it.

``update`` runs git-cliff with the shared template (cliff.toml beside this
module), filled in with the repository and the long name from release.toml. Every
program uses the same template, so CHANGELOG.md looks the same everywhere and
``notes`` can find each version's section. ``notes`` prints the section of
CHANGELOG.md for one version, which becomes the GitHub release notes. It
also reads curated release notes, written by hand in the same format (see
config.py).

git-cliff runs at a pinned version with ``pipx run`` or ``uvx``, whichever is
available, so nothing needs installing beforehand.
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from modflow_devtools.release import config

GIT_CLIFF_VERSION = "2.14.2"
TEMPLATE = Path(__file__).resolve().parent / "cliff.toml"
HEADING = re.compile(r"^## Version (\S+)")
SECTION = re.compile(r"^## Version ", re.M)


def git_cliff():
    """The command that runs the pinned git-cliff."""
    if pipx := shutil.which("pipx"):
        return [pipx, "run", "--spec", f"git-cliff=={GIT_CLIFF_VERSION}", "git-cliff"]
    if uvx := shutil.which("uvx"):
        return [uvx, f"git-cliff@{GIT_CLIFF_VERSION}"]
    sys.exit("running git-cliff needs pipx or uvx")


def update(root, version, repository):
    """Add the release's section to CHANGELOG.md, above the earlier ones,
    creating the file with the template's header if needed. The file is
    assembled here rather than with git-cliff's --prepend, which repeats the
    header on Windows, and always written with LF line endings."""
    _, long_name = config.names(root)
    changelog = root / "CHANGELOG.md"
    text = TEMPLATE.read_text()
    text = text.replace("__REPOSITORY__", repository).replace("__NAME__", long_name)
    with tempfile.TemporaryDirectory() as tmp:
        cliff = Path(tmp) / "cliff.toml"
        cliff.write_text(text)
        cmd = [*git_cliff(), "--config", str(cliff), "--unreleased", "--tag", f"v{version}"]
        if changelog.is_file():
            cmd += ["--strip", "header"]
        # text mode turns any CRLF into LF
        out = subprocess.run(cmd, cwd=root, check=True, stdout=subprocess.PIPE, text=True).stdout
    if changelog.is_file():
        old = changelog.read_text()
        match = SECTION.search(old)
        head, rest = (old[: match.start()], old[match.start() :]) if match else (old, "")
        parts = [head.rstrip("\n"), out.strip("\n"), rest.strip("\n")]
        out = "\n\n".join(p for p in parts if p)
    with changelog.open("w", newline="\n") as f:
        f.write(out.strip("\n") + "\n")


def section(root, version, path=config.CHANGELOG):
    """The section of the notes file for the version, or None if the file or
    the section is missing."""
    file = root / path
    if not file.is_file():
        return None
    lines, found = [], False
    for line in file.read_text().splitlines():
        match = HEADING.match(line)
        if match:
            if found:
                break
            found = match.group(1) == version
            continue
        if found:
            lines.append(line)
    return "\n".join(lines) if found else None


def notes(root, version, title=False, path=config.CHANGELOG):
    """The section of the notes file (CHANGELOG.md by default) for the
    version, titled with the long name if ``title``."""
    if not (root / path).is_file():
        sys.exit(f"no {path}")
    body = section(root, version, path)
    if body is None:
        sys.exit(f"no section for version {version} in {path}")
    body = body.strip()
    body = body + "\n" if body else ""
    if not title:
        return body
    _, long_name = config.names(root)
    return f"{long_name} version {version}\n\n{body}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("update", help="prepend this release to CHANGELOG.md")
    up.add_argument("--version", required=True)
    up.add_argument("--repository", required=True, help="owner/repo")
    no = sub.add_parser("notes", help="print one version's section")
    no.add_argument("--version", required=True)
    no.add_argument("--path", default=config.CHANGELOG, help="notes file")
    no.add_argument(
        "--title", action="store_true", help="title the notes '<long name> version <version>'"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "update":
        update(root, args.version, args.repository)
    else:
        sys.stdout.write(notes(root, args.version, args.title, args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
