import argparse
import hashlib
from os import PathLike
from pathlib import Path

import tomli_w as tomli
from boltons.iterutils import remap

from modflow_devtools.misc import get_model_paths
from modflow_devtools.models import BASE_URL

REGISTRY_PATH = Path(__file__).parent / "registry" / "registry.toml"


def _sha256(path: Path) -> str:
    """
    Compute the SHA256 hash of the given file.
    Reference: https://stackoverflow.com/a/44873382/6514033
    """
    h = hashlib.sha256()
    b = bytearray(128 * 1024)
    mv = memoryview(b)
    with path.open("rb", buffering=0) as f:
        for n in iter(lambda: f.readinto(mv), 0):
            h.update(mv[:n])
    return h.hexdigest()


def write_registry(
    path: str | PathLike,
    registry_path: str | PathLike,
    base_url: str,
    append: bool = False,
):
    path = Path(path).expanduser().absolute()
    registry_path = Path(registry_path).expanduser().absolute()

    if not registry_path.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)

    registry: dict[str, dict[str, str | None]] = {}
    models: dict[str, list[str]] = {}
    exclude = [".DS_Store"]

    if not path.is_dir():
        raise NotADirectoryError(f"Path {path} is not a directory.")
    for mp in get_model_paths(path):
        for p in mp.rglob("*"):
            if "compare" in str(p):
                continue
            if p.is_file() and not any(e in p.name for e in exclude):
                relpath = p.expanduser().absolute().relative_to(path)
                name = str(relpath)  # .replace("/", "_").replace("-", "_")
                model_name = str(relpath.parent).replace("/", "_").replace("-", "_")
                if base_url.endswith((".zip", ".tar")):
                    url = base_url
                    hash = None
                else:
                    url = f"{base_url}/{relpath!s}"
                    hash = _sha256(p)
                registry[name] = {"hash": hash, "url": url}
                if model_name not in models:
                    models[model_name] = []
                models[model_name].append(name)

    if base_url.endswith((".zip", ".tar")):
        registry[base_url.rpartition("/")[2]] = {"hash": None, "url": base_url}

    def drop_none_or_empty(path, key, value):
        if value is None or value == "":
            return False
        return True

    with registry_path.open("ab+" if append else "wb") as registry_file:
        tomli.dump(
            remap(dict(sorted(registry.items())), visit=drop_none_or_empty),
            registry_file,
        )

    models_path = registry_path.parent / "models.toml"
    with models_path.open("ab+" if append else "wb") as models_file:
        tomli.dump(dict(sorted(models.items())), models_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Make a registry of example models.")
    parser.add_argument("path")
    parser.add_argument(
        "--append",
        "-a",
        action="store_true",
        help="Append instead of overwriting.",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        type=str,
        help="Base URL for example models.",
    )
    args = parser.parse_args()
    path = Path(args.path)
    base_url = args.base_url if args.base_url else BASE_URL
    write_registry(path, REGISTRY_PATH, base_url, args.append)
