import hashlib
from pathlib import Path
from typing import Iterator

import pkg_resources

from modflow_devtools.imports import import_optional_dependency

pooch = import_optional_dependency("pooch")


def _sha256(filename) -> str:
    """
    Compute the SHA256 hash of the given file.
    Reference: https://stackoverflow.com/a/44873382/6514033
    """
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with open(filename, "rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


PROJ_ROOT = Path(__file__).parents[1]
DATA_PATH = PROJ_ROOT / "data"
OWNER = "wpbonelli"
PACKAGE = "modflow-devtools"
VERSION = pkg_resources.get_distribution(PACKAGE).version.rpartition(".dev")[0]
EXCLUDED = [
    ".DS_Store",
]
REGISTRY = {
    p.name: _sha256(p)
    for p in DATA_PATH.rglob("*")
    if p.is_file() and not any(e in p.name for e in EXCLUDED)
}
FETCHER = pooch.create(
    # Folder where the data will be stored. For a sensible default, use the
    # default cache folder for your OS.
    path=pooch.os_cache(PACKAGE),
    # Base URL of the remote data store. Will call .format on this string
    # to insert the version (see below).
    base_url="https://github.com/"
    + OWNER
    + "/"
    + PACKAGE
    + "/raw/models-api/data/",  # todo: replace branch (debugging)
    # Pooches are versioned so that you can use multiple versions of a
    # package simultaneously. Use PEP440 compliant version number. The
    # version will be appended to the path.
    version=VERSION,
    # The cache file registry. A dictionary with all files managed by this
    # pooch. Keys are the file names (relative to *base_url*) and values
    # are their respective SHA256 hashes. Files will be downloaded
    # automatically when needed (see fetch_gravity_data).
    registry=REGISTRY,
)


def to_paths(strs) -> Iterator[Path]:
    for s in strs:
        yield Path(s).expanduser().absolute()


def mf2005_freyberg():
    """
    Load the MF2005 Freyberg example model files.
    """
    return list(
        to_paths(FETCHER.fetch("mf2005_freyberg.zip", processor=pooch.Unzip()))
    )


def mf6_freyberg():
    """
    Load the MF6 Freyberg example model files.
    """
    return list(
        to_paths(FETCHER.fetch("mf6_freyberg.zip", processor=pooch.Unzip()))
    )


def mfusg_freyberg():
    """
    Load the MFUSG Freyberg example model files.
    """
    return list(
        to_paths(FETCHER.fetch("mfusg_freyberg.zip", processor=pooch.Unzip()))
    )
