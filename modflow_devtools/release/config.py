"""
A program's release.toml, at the repo root:

    name = "mfusg"
    long-name = "MODFLOW-USG"

    [[version-files]]
    ...

``name`` goes in the source archive's name and the release title,
``long-name`` in the changelog header and the release notes. See version.py
for ``version-files``.
"""

import sys
import tomllib


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
