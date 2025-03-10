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
    url: str,
    append: bool = False,
):
    path = Path(path).expanduser().absolute()
    registry_path = Path(registry_path).expanduser().absolute()
    modelmap_path = registry_path.parent / "models.toml"

    if not path.is_dir():
        raise NotADirectoryError(f"Path {path} is not a directory.")
    if not registry_path.exists():
        registry_path.parent.mkdir(parents=True, exist_ok=True)

    registry: dict[str, dict[str, str | None]] = {}
    modelmap: dict[str, list[str]] = {}
    exclude = [".DS_Store", "compare"]
    if is_zip := url.endswith((".zip", ".tar")):
        registry[url.rpartition("/")[2]] = {"hash": None, "url": url}

    def _find_examples_dir(p):
        while p.name != "examples":
            p = p.parent
        return p

    model_paths = get_model_paths(path)
    for model_path in model_paths:
        # TODO: the renaming is only necessary because we're attaching auto-
        # generated functions to the models module. If we can live without,
        # and get by with a single function that takes model name as an arg,
        # then the model names could correspond directly to directory names.
        model_path = model_path.expanduser().absolute()
        base_path = _find_examples_dir(model_path) if is_zip else path
        model_name = (
            str(model_path.relative_to(base_path)).replace("/", "_").replace("-", "_")
        )
        modelmap[model_name] = []
        for p in model_path.glob("*"):
            if not p.is_file() or any(e in p.name for e in exclude):
                continue
            if is_zip:
                relpath = p.expanduser().absolute().relative_to(base_path)
                name = str(relpath)
                url_ = url
                hash = None
            else:
                relpath = p.expanduser().absolute().relative_to(base_path)
                name = str(relpath)
                url_ = f"{url}/{relpath!s}"
                hash = _sha256(p)
            registry[name] = {"hash": hash, "url": url_}
            modelmap[model_name].append(name)

    def drop_none_or_empty(path, key, value):
        if value is None or value == "":
            return False
        return True

    with registry_path.open("ab+" if append else "wb") as registry_file:
        tomli.dump(
            remap(dict(sorted(registry.items())), visit=drop_none_or_empty),
            registry_file,
        )

    with modelmap_path.open("ab+" if append else "wb") as modelmap_file:
        tomli.dump(dict(sorted(modelmap.items())), modelmap_file)


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
        "--url",
        "-u",
        type=str,
        help="Base URL for example models.",
    )
    args = parser.parse_args()
    path = Path(args.path)
    url = args.url if args.url else BASE_URL
    write_registry(path=path, registry_path=REGISTRY_PATH, url=url, append=args.append)
