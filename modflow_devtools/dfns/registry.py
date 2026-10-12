import json
import os
import tempfile
import urllib.request
from os import PathLike
from pathlib import Path
from platform import system

import pooch
import tomli
import tomli_w
from pydantic import BaseModel, Field, PrivateAttr

from modflow_devtools.dfn import schema as dfn
from modflow_devtools.dfns import schema as dfns
from modflow_devtools.download import get_request

__all__ = [
    "DfnRegistry",
    "LocalDfnRegistry",
    "RemoteDfnRegistry",
    "add_to_user_config",
    "is_cached",
]


class DfnRegistry(BaseModel):
    """Base class for DFN registries."""

    model_config = {"arbitrary_types_allowed": True}

    def spec(self, schema_version: str = dfns.CURRENT_SCHEMA_VERSION) -> dfns.Dfns | dfn.Dfns:
        raise NotImplementedError

    def get_path(self, component: str) -> Path:
        raise NotImplementedError


class LocalDfnRegistry(DfnRegistry):
    """Registry for local DFN files."""

    path: Path = Field(description="Path to directory containing DFN files")

    def model_post_init(self, _) -> None:
        object.__setattr__(self, "path", Path(self.path).expanduser().resolve())

    def spec(self, schema_version: str = dfns.CURRENT_SCHEMA_VERSION) -> dfns.Dfns | dfn.Dfns:
        if schema_version == dfns.CURRENT_SCHEMA_VERSION:
            return dfns.Dfns.load(self.path)
        return dfn.Dfn.load_all(self.path, schema_version=schema_version)  # type: ignore

    def get_path(self, component: str) -> Path:
        for ext in [".dfn", ".toml"]:
            p = self.path / f"{component}{ext}"
            if p.exists():
                return p
        raise FileNotFoundError(f"Component '{component}' not found in {self.path}")


def _auto_sync() -> bool:
    return os.environ.get("MODFLOW_DEVTOOLS_AUTO_SYNC", "").lower() in ("1", "true", "yes")


class RemoteDfnRegistry(DfnRegistry):
    """Registry for DFN files associated with a GitHub repository release."""

    release_id: str = Field(
        description="DFN source repository release ID (owner/name@tag)",
    )

    _latest: str | None = PrivateAttr(default=None, init=False)

    def latest_tag(self) -> str:
        repo, tag = self.release_id.split("@")
        if tag != "latest":
            return tag
        if self._latest is None:
            owner, name = repo.split("/")
            # authenticated if GITHUB_TOKEN is set, to bypass the rate limit
            url = f"https://api.github.com/repos/{owner}/{name}/releases/latest"
            with urllib.request.urlopen(get_request(url)) as resp:
                self._latest = json.loads(resp.read())["tag_name"]
        return self._latest

    @staticmethod
    def base_cache_path() -> Path:
        """
        Get the base DFN cache path. On Unix: $XDG_CACHE_HOME/modflow-devtools/dfns,
        falling back to ~/.cache/. On Windows: %LOCALAPPDATA%/modflow-devtools/dfns.
        """
        if system() == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        return base / "modflow-devtools" / "dfns"

    @staticmethod
    def user_config_path() -> Path:
        """
        Path to the user overlay configuration file, in which users can override
        and/or add to the configuration shipped with the package.

        On Unix: $XDG_CONFIG_HOME/modflow-devtools/dfns.toml (default ~/.config/).
        On Windows: %APPDATA%/modflow-devtools/dfns.toml.
        """
        if system() == "Windows":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base / "modflow-devtools" / "dfns.toml"

    @classmethod
    def from_ids(cls, *ids: str) -> "dict[str, RemoteDfnRegistry]":
        """Create registries from one or more DFN source repository release IDs."""
        registries = {}

        for id in ids:
            registry = cls(release_id=id)

            if _auto_sync() and (
                not registry.cache_path.exists() or not any(registry.cache_path.iterdir())
            ):
                registry.sync()

            registries[id] = registry

        return registries

    @classmethod
    def load(cls, path: str | PathLike) -> "dict[str, RemoteDfnRegistry]":
        """Load registries from a TOML file of DFN source repository release IDs."""
        path = Path(path)
        if not path.exists():
            return {}

        with path.open("rb") as f:
            data = tomli.load(f)

        registries = {}
        for id in data.get("releases", []):
            registry = RemoteDfnRegistry(release_id=id)
            registries[id] = registry

        return registries

    @classmethod
    def load_default(cls) -> "dict[str, RemoteDfnRegistry]":
        """
        Load registries from remote DFN source repository configuration bundled
        with the package, and from a user overlay configuration file if present.
        """
        base = RemoteDfnRegistry.load(Path(__file__).parent / "dfns.toml")
        if not RemoteDfnRegistry.user_config_path().exists():
            return base

        user = RemoteDfnRegistry.load(RemoteDfnRegistry.user_config_path())
        return base | user

    @property
    def cache_path(self) -> Path:
        repo, _ = self.release_id.split("@")
        return RemoteDfnRegistry.base_cache_path() / repo / self.latest_tag()

    def spec(self, schema_version: str = dfns.CURRENT_SCHEMA_VERSION) -> dfns.Dfns | dfn.Dfns:
        if not self.cache_path.exists() or not any(self.cache_path.iterdir()):
            self.sync()
        if schema_version == dfns.CURRENT_SCHEMA_VERSION:
            return dfns.Dfns.load(self.cache_path)
        return dfn.Dfn.load_all(self.cache_path, schema_version=schema_version)  # type: ignore

    def sync(self, force: bool = False) -> None:
        """Download and extract DFN files for this release to the local cache."""

        if not force and self.cache_path.exists() and any(self.cache_path.iterdir()):
            return

        asset_name = "dfns.zip"
        repo, _ = self.release_id.split("@")
        url = f"https://github.com/{repo}/releases/download/{self.latest_tag()}/{asset_name}"

        self.cache_path.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            pooch.retrieve(
                url=url,
                known_hash=None,
                path=tmpdir,
                fname=asset_name,
                processor=pooch.Unzip(extract_dir=str(self.cache_path)),
            )

    def cached_tag(self) -> str | None:
        """
        Return the cached tag for this release without making a network request.

        For exact tags, checks the specific cache directory. For ``@latest``,
        scans the repo's cache directory and returns the most recently modified
        cached tag, or None if nothing is cached.
        """
        repo, tag = self.release_id.split("@")
        if tag != "latest":
            return tag if self.cache_path.exists() and any(self.cache_path.iterdir()) else None
        repo_cache = RemoteDfnRegistry.base_cache_path() / repo
        if not repo_cache.is_dir():
            return None
        tags = [p for p in repo_cache.iterdir() if p.is_dir() and any(p.iterdir())]
        if not tags:
            return None
        return max(tags, key=lambda p: p.stat().st_mtime).name

    def get_path(self, component: str) -> Path:
        if not self.cache_path.exists() or not any(self.cache_path.iterdir()):
            self.sync()
        for ext in [".dfn", ".toml"]:
            p = self.cache_path / f"{component}{ext}"
            if p.exists():
                return p
        raise FileNotFoundError(f"Component '{component}' not found for '{self.release_id}'")


def add_to_user_config(release_id: str) -> bool:
    """
    Add a release ID to the user overlay config file.

    Returns True if the release was added, False if it was already present.
    Creates the config file (and its parent directory) if they don't exist.
    """
    path = RemoteDfnRegistry.user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        with path.open("rb") as f:
            data = tomli.load(f)
    else:
        data = {}

    releases = data.get("releases", [])
    if release_id in releases:
        return False

    data["releases"] = [*releases, release_id]
    with path.open("wb") as f:
        tomli_w.dump(data, f)
    return True


def is_cached(release_id: str) -> bool:
    """
    Check whether a remote DFN source repository's release is in the cache.
    """
    registry = RemoteDfnRegistry(release_id=release_id)
    cache_dir = registry.cache_path
    return any(cache_dir.iterdir()) if cache_dir.is_dir() else False
