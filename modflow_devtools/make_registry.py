import argparse
import hashlib
from os import PathLike
from pathlib import Path

import tomli_w as tomli
from boltons.iterutils import remap

from modflow_devtools.misc import get_model_paths
from modflow_devtools.models import BASE_URL

REGISTRY_DIR = Path(__file__).parent / "registry"
REGISTRY_PATH = REGISTRY_DIR / "registry.toml"
MODELMAP_PATH = REGISTRY_DIR / "models.toml"
EXAMPLES_PATH = REGISTRY_DIR / "examples.toml"


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
    url: str,
    prefix: str = "",
    append: bool = False,
):
    path = Path(path).expanduser().absolute()
    if not path.is_dir():
        raise NotADirectoryError(f"Path {path} is not a directory.")

    registry: dict[str, dict[str, str | None]] = {}
    modelmap: dict[str, list[str]] = {}
    examples: dict[str, list[str]] = {}
    exclude = [".DS_Store", "compare"]
    if is_zip := url.endswith((".zip", ".tar")):
        registry[url.rpartition("/")[2]] = {"hash": None, "url": url}

    model_paths = get_model_paths(path)
    for model_path in model_paths:
        model_path = model_path.expanduser().absolute()
        rel_path = model_path.relative_to(path)
        parts = [prefix, *list(rel_path.parts)] if prefix else list(rel_path.parts)
        model_name = "/".join(parts)
        modelmap[model_name] = []
        if is_zip:
            name = rel_path.parts[0]
            if name not in examples:
                examples[name] = []
            examples[name].append(model_name)
        for p in model_path.rglob("*"):
            if not p.is_file() or any(e in p.name for e in exclude):
                continue
            if is_zip:
                relpath = p.expanduser().absolute().relative_to(path)
                name = "/".join(relpath.parts)
                url_ = url
                hash = None
            else:
                relpath = p.expanduser().absolute().relative_to(path)
                name = "/".join(relpath.parts)
                url_ = f"{url}/{relpath!s}"
                hash = _sha256(p)
            registry[name] = {"hash": hash, "url": url_}
            modelmap[model_name].append(name)

    def drop_none_or_empty(path, key, value):
        if value is None or value == "":
            return False
        return True

    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    with REGISTRY_PATH.open("ab+" if append else "wb") as registry_file:
        tomli.dump(
            remap(dict(sorted(registry.items())), visit=drop_none_or_empty),
            registry_file,
        )

    with MODELMAP_PATH.open("ab+" if append else "wb") as modelmap_file:
        tomli.dump(dict(sorted(modelmap.items())), modelmap_file)

    with EXAMPLES_PATH.open("ab+" if append else "wb") as examples_file:
        tomli.dump(dict(sorted(examples.items())), examples_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Make a registry of models.")
    parser.add_argument("path")
    parser.add_argument(
        "--append",
        "-a",
        action="store_true",
        help="Append instead of overwriting.",
    )
    parser.add_argument(
        "--prefix", "-p", type=str, help="Prefix for models.", default=""
    )
    parser.add_argument(
        "--url",
        "-u",
        type=str,
        help="Base URL for models.",
        default=BASE_URL,
    )
    args = parser.parse_args()
    write_registry(path=args.path, url=args.url, prefix=args.prefix, append=args.append)
