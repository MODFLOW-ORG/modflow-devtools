"""
A program's release.toml, at the repo root:

    name = "mfusg"
    long-name = "MODFLOW-USG"

    [[version-files]]
    ...

``name`` goes in the source archive's name and the release title,
``long-name`` in the changelog header and the release notes. See version.py
for ``version-files``.

Release notes are generated from commits into CHANGELOG.md by default (see
changelog.py). A program whose notes are written by hand instead names the
file holding them, with a ``## Version X.Y.Z`` section per release, and
optionally a release asset built from it, e.g. a PDF:

    [release-notes]
    path = "doc/release-notes.md"
    asset = "ReleaseNotes.pdf"

Either way, the version's section becomes the release's description. If
``asset`` is set, it must be attached to the release (e.g. with
release-finish's ``extra-assets``), and the description links to it.
"""

import sys
import tomllib
from typing import NamedTuple

CHANGELOG = "CHANGELOG.md"


def load(root):
    path = root / "release.toml"
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def names(root):
    """The program's name and long name."""
    config = load(root)
    name, long_name = config.get("name"), config.get("long-name")
    if not name or not long_name:
        sys.exit("release.toml must set name and long-name")
    return name, long_name


class Notes(NamedTuple):
    curated: bool
    path: str
    asset: str | None


def release_notes(root):
    """Where the release notes are: whether they are curated by hand (or
    generated), the file holding them, and the release asset built from
    them, if any."""
    table = load(root).get("release-notes", {})
    if not isinstance(table, dict) or set(table) - {"path", "asset"}:
        sys.exit("release.toml's release-notes may only set path and asset")
    path, asset = table.get("path"), table.get("asset")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        sys.exit("release.toml's release-notes.path must be a file in the repository")
    if asset is not None and (
        not isinstance(asset, str) or not asset or "/" in asset or "\\" in asset
    ):
        sys.exit("release.toml's release-notes.asset must be a release asset's file name")
    return Notes(path is not None, path or CHANGELOG, asset)
