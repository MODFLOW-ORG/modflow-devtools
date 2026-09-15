"""
Programs API: install MODFLOW-ecosystem program executables and track what's
installed where.

Unlike the Models and DFNs APIs, this module does not maintain a registry
synced from per-repository metadata files. Program binaries are a solved
problem for a real package manager (e.g. conda-forge); asking every program
repository to also publish a bespoke registry contract duplicates that for no
real gain. Instead, this module ports flopy's get_modflow.py download/install
logic (generalized across the three real MODFLOW-ORG release formats) and
adds one genuinely new piece: a per-program installation ledger, so callers
can ask "where is mf6 installed" regardless of how it got there.
"""

import hashlib
import json
import os
import re
import shutil
import stat
import time
import warnings
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pooch
import requests  # type: ignore[import-untyped]

from modflow_devtools.ostags import get_binary_suffixes, get_modflow_ostag

warnings.warn(
    "The modflow_devtools.programs API is experimental and may change or be "
    "removed in future versions without following normal deprecation procedures. "
    "Use at your own risk. To suppress this warning, use:\n"
    "  warnings.filterwarnings('ignore', "
    "message='.*modflow_devtools.programs.*experimental.*')",
    FutureWarning,
    stacklevel=2,
)

_CACHE_ROOT = Path(pooch.os_cache("modflow-devtools"))
"""Root cache directory (platform-appropriate location via Pooch)"""

DEFAULT_OWNER = "MODFLOW-ORG"
DEFAULT_REPO = "executables"
KNOWN_REPOS = ("executables", "modflow6", "modflow6-nightly-build")
"""The three repos get_modflow.py supports out of the box - not an allowlist.
Any owner/repo with a GitHub release and an ostag-matching asset works with
`install_program`/`get_release`; a growing number of individual program repos
(mfnwt, mt3d-usgs, vs2dt, gridgen, triangle, zonbud, zonbudusg, ...) already
publish releases in the same shape `executables` and `modflow6` do."""

GITHUB_API = "https://api.github.com"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_TRIES = 3
_RETRY_DELAY = 2.0
_MAX_RETRY_DELAY = 60.0


class ProgramInstallationError(Exception):
    """Raised when program discovery, download, or installation fails."""


def get_platform() -> str:
    """
    Detect the current platform as a MODFLOW ostag: 'linux', 'mac', 'macarm',
    or 'win64'. Delegates to `modflow_devtools.ostags.get_ostag`.
    """
    try:
        return get_modflow_ostag()
    except NotImplementedError as e:
        raise ProgramInstallationError(str(e)) from e


def _compute_file_hash(file_path: Path, algorithm: str = "sha256") -> str:
    hash_obj = hashlib.new(algorithm)
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def _verify_hash(file_path: Path, expected_hash: str) -> bool:
    if ":" not in expected_hash:
        raise ValueError(f"Invalid hash format: {expected_hash}. Expected 'algorithm:hexdigest'")
    algorithm, expected_digest = expected_hash.split(":", 1)
    actual_digest = _compute_file_hash(file_path, algorithm)
    return actual_digest.lower() == expected_digest.lower()


def _github_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _request_json(
    url: str, *, tries: int | None = None, delay: float | None = None, timeout: int = 10
):
    tries = _MAX_TRIES if tries is None else max(1, tries)
    delay = _RETRY_DELAY if delay is None else max(0.0, delay)
    for attempt in range(1, tries + 1):
        try:
            response = requests.get(url, headers=_github_headers(), timeout=timeout)
            if response.status_code in _RETRYABLE_STATUS and attempt < tries:
                time.sleep(min(delay * (2 ** (attempt - 1)), _MAX_RETRY_DELAY))
                continue
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError:
            raise
        except requests.exceptions.RequestException as err:
            if attempt == tries:
                raise ProgramInstallationError(f"request failed for {url}: {err}") from err
            time.sleep(min(delay * (2 ** (attempt - 1)), _MAX_RETRY_DELAY))
    raise ProgramInstallationError(f"request failed for {url}: exhausted retries")


def get_releases(
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    *,
    tries: int | None = None,
    delay: float | None = None,
) -> list[str]:
    """List available release tags for owner/repo, plus 'latest'."""
    try:
        data = _request_json(
            f"{GITHUB_API}/repos/{owner}/{repo}/releases", tries=tries, delay=delay
        )
    except requests.exceptions.HTTPError as err:
        raise ProgramInstallationError(f"repo {owner}/{repo} not found: {err}") from err
    return ["latest", *(r["tag_name"] for r in data)]


def get_release(
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    tag: str = "latest",
    *,
    tries: int | None = None,
    delay: float | None = None,
) -> dict:
    """Fetch GitHub release metadata for owner/repo@tag ('latest' resolves the newest release)."""
    url = (
        f"{GITHUB_API}/repos/{owner}/{repo}/releases/latest"
        if tag == "latest"
        else f"{GITHUB_API}/repos/{owner}/{repo}/releases/tags/{tag}"
    )
    try:
        return _request_json(url, tries=tries, delay=delay)
    except requests.exceptions.HTTPError as err:
        if err.response is not None and err.response.status_code == 404:
            try:
                available = get_releases(owner, repo, tries=tries, delay=delay)
            except ProgramInstallationError:
                raise ProgramInstallationError(f"repo {owner}/{repo} not found") from err
            raise ProgramInstallationError(
                f"release {tag!r} not found for {owner}/{repo}; choose from: {', '.join(available)}"
            ) from err
        raise ProgramInstallationError(
            f"failed to fetch release {tag!r} for {owner}/{repo}: {err}"
        ) from err


def _select_asset(release: dict, ostag: str) -> dict:
    """
    Match a release asset to `ostag`, requiring the tag to appear as a whole
    token (not e.g. matching 'win64' inside 'win64ext', or 'mac' inside
    'macarm').
    """
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(ostag)}(?![A-Za-z0-9])")
    assets = release.get("assets", [])
    for asset in assets:
        if pattern.search(asset["name"]):
            return asset
    available = ", ".join(a["name"] for a in assets)
    raise ProgramInstallationError(
        f"no asset for platform {ostag!r} in release {release.get('tag_name')!r}; "
        f"available assets: {available}"
    )


def download_archive(
    url: str,
    dest: Path,
    *,
    expected_hash: str | None = None,
    force: bool = False,
    verbose: bool = False,
    tries: int | None = None,
    delay: float | None = None,
    timeout: int = 120,
) -> Path:
    """Download an archive to `dest`, reusing a cached copy unless `force`."""
    if dest.exists() and not force:
        if expected_hash is None or _verify_hash(dest, expected_hash):
            if verbose:
                print(f"using cached archive: {dest}")
            return dest
        if verbose:
            print(f"cached archive hash mismatch, re-downloading: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    tries = _MAX_TRIES if tries is None else max(1, tries)
    delay = _RETRY_DELAY if delay is None else max(0.0, delay)
    temp_dest = dest.with_suffix(dest.suffix + ".part")

    if verbose:
        print(f"downloading: {url}")

    for attempt in range(1, tries + 1):
        try:
            response = requests.get(url, headers=_github_headers(), stream=True, timeout=timeout)
            response.raise_for_status()
            with temp_dest.open("wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            break
        except requests.exceptions.RequestException as err:
            temp_dest.unlink(missing_ok=True)
            if attempt == tries:
                raise ProgramInstallationError(f"failed to download {url}: {err}") from err
            secs = min(delay * (2 ** (attempt - 1)), _MAX_RETRY_DELAY)
            if verbose:
                print(f"  attempt {attempt}/{tries} failed ({err}); retrying in {secs:.0f}s")
            time.sleep(secs)

    if expected_hash is not None:
        if verbose:
            print("verifying hash...")
        if not _verify_hash(temp_dest, expected_hash):
            temp_dest.unlink()
            raise ProgramInstallationError(
                f"downloaded file hash does not match expected: {expected_hash}"
            )

    temp_dest.replace(dest)
    if verbose:
        print(f"downloaded to: {dest}")
    return dest


@dataclass
class _ExtractedProgram:
    name: str
    version: str
    path: Path
    is_shared_object: bool


def _normalize_subset(program: str | None, subset) -> set[str] | None:
    if subset is None:
        return {program} if program else None
    if isinstance(subset, str):
        items = set(subset.replace(",", " ").split())
    else:
        items = set(subset)
    if program:
        items.add(program)
    return items or None


def extract_release_archive(
    archive: Path,
    dest_dir: Path,
    *,
    release_tag: str,
    ostag: str,
    subset: set[str] | None = None,
    verbose: bool = False,
) -> list["_ExtractedProgram"]:
    """
    Extract program executables from a release archive into `dest_dir` (flat,
    no nested directories preserved).

    Looks for files nested under a top-level `bin/` directory in the archive,
    falling back to the archive root if none is found (mirrors the actual
    layouts of `executables`, `modflow6`, and `modflow6-nightly-build`
    releases). If the archive also contains a `code.json` manifest (used by
    the combined `executables` distribution to bundle many independently
    versioned programs into one archive), each program's own version comes
    from there; otherwise every extracted executable is versioned as
    `release_tag`, since a `modflow6`/`modflow6-nightly-build` release ships
    every program at the same version.

    Double-precision program variants (`code.json`'s legacy `*dbl` entries,
    used by a few old MODFLOW-2005-era programs) are not handled - a niche
    build variant, not central to installing modern ecosystem programs.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    exe_suffix, lib_suffix = get_binary_suffixes(ostag)

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        full_path = {Path(n).name: n for n in names if Path(n).parent.name == "bin"}
        files = set(full_path) if full_path else set(names)

        code = None
        if "code.json" in files:
            code = json.loads(zf.read(full_path.get("code.json", "code.json")))
            files.discard("code.json")

        extracted: list[_ExtractedProgram] = []
        to_extract: set[str] = set()

        if code:
            for key in sorted(code):
                meta = code[key]
                is_so = bool(meta.get("shared_object"))
                fname = f"{key}{lib_suffix if is_so else exe_suffix}"
                if fname not in files:
                    continue
                if subset and key not in subset and fname not in subset:
                    continue
                to_extract.add(full_path.get(fname, fname))
                extracted.append(_ExtractedProgram(key, meta["version"], dest_dir / fname, is_so))
        else:
            for fname in sorted(files):
                stem = Path(fname).stem
                if subset and fname not in subset and stem not in subset:
                    continue
                to_extract.add(full_path.get(fname, fname))
                is_so = bool(lib_suffix) and fname.endswith(lib_suffix)
                extracted.append(_ExtractedProgram(stem, release_tag, dest_dir / fname, is_so))

        if not to_extract:
            raise ProgramInstallationError(
                "no matching executables found"
                + (f" for subset {sorted(subset)}" if subset else "")
                + f"; available: {', '.join(sorted(files))}"
            )

        if verbose:
            print(f"extracting {len(to_extract)} file(s) to {dest_dir}")

        zf.extractall(dest_dir, members=to_extract)

    if full_path:
        rmdirs: set[Path] = set()
        for member in to_extract:
            member_path = Path(member)
            (dest_dir / member_path).replace(dest_dir / member_path.name)
            rmdirs.add(member_path.parent)
        for rmdir in sorted(rmdirs, key=lambda p: len(p.parts), reverse=True):
            for ancestor in (rmdir, *rmdir.parents):
                if ancestor == Path():
                    break
                try:
                    (dest_dir / ancestor).rmdir()
                except OSError:
                    break

    if os.name != "nt":
        for prog in extracted:
            if not prog.is_shared_object:
                prog.path.chmod(
                    prog.path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                )

    if verbose:
        for prog in extracted:
            print(f"  {prog.path.name} ({prog.version})")

    return extracted


def get_bindir_options(program: str | None = None) -> list[Path]:
    """
    Get writable installation directories in priority order.

    Adapted from flopy's get-modflow utility.
    """
    import sys

    candidates = []

    if program:
        metadata = InstallationMetadata(program)
        if metadata.load():
            installations = metadata.list_installations()
            if installations:
                most_recent = max(installations, key=lambda i: i.installed_at)
                candidates.append(most_recent.bindir)

    if hasattr(sys, "base_prefix"):
        candidates.append(Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin"))

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Microsoft" / "WindowsApps")
    else:
        candidates.append(Path.home() / ".local" / "bin")

    if os.name != "nt":
        candidates.append(Path("/usr/local/bin"))

    writable = []
    for path in candidates:
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                writable.append(path)
            except (OSError, PermissionError):
                continue
        elif os.access(path, os.W_OK):
            writable.append(path)

    seen = set()
    result = []
    for path in writable:
        if path not in seen:
            seen.add(path)
            result.append(path)

    return result


def get_bindir_shortcut_map(program: str | None = None) -> dict[str, tuple[Path, str]]:
    """
    Get map of installation directory shortcuts to (path, description) tuples.

    Adapted from flopy's get-modflow utility:
    https://github.com/modflowpy/flopy/blob/develop/flopy/utils/get_modflow.py
    """
    import sys

    options: dict[str, tuple[Path, str]] = {}

    if program:
        metadata = InstallationMetadata(program)
        if metadata.load():
            installations = metadata.list_installations()
            if installations:
                most_recent = max(installations, key=lambda i: i.installed_at)
                prev_path = most_recent.bindir
                if prev_path.exists() and os.access(prev_path, os.W_OK):
                    options[":prev"] = (prev_path, "previously selected bindir")

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        mfdt_path = (
            Path(local_app_data) / "modflow-devtools" / "bin"
            if local_app_data
            else Path.home() / "AppData" / "Local" / "modflow-devtools" / "bin"
        )
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        mfdt_path = (
            Path(xdg_data_home) / "modflow-devtools" / "bin"
            if xdg_data_home
            else Path.home() / ".local" / "share" / "modflow-devtools" / "bin"
        )

    try:
        mfdt_path.mkdir(parents=True, exist_ok=True)
        if os.access(mfdt_path, os.W_OK):
            options[":mf"] = (mfdt_path, "used by modflow-devtools")
    except (OSError, PermissionError):
        pass

    if hasattr(sys, "base_prefix"):
        py_bin = Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin")
        if py_bin.is_dir() and os.access(py_bin, os.W_OK):
            options[":python"] = (py_bin, "used by Python")

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            windowsapps_path = Path(local_app_data) / "Microsoft" / "WindowsApps"
            if windowsapps_path.is_dir() and os.access(windowsapps_path, os.W_OK):
                options[":windowsapps"] = (windowsapps_path, "user app path")
    else:
        home_local_bin = Path.home() / ".local" / "bin"
        if home_local_bin.is_dir() and os.access(home_local_bin, os.W_OK):
            options[":home"] = (home_local_bin, "user-specific bindir")

    if os.name != "nt":
        local_bin = Path("/usr") / "local" / "bin"
        if local_bin.is_dir() and os.access(local_bin, os.W_OK):
            options[":system"] = (local_bin, "system local bindir")

    if not options:
        raise ProgramInstallationError("No writable installation directories found")

    return options


def select_bindir(bindir_arg: str, program: str | None = None) -> Path:
    """
    Parse and resolve a bindir argument with support for ':' prefix shortcuts.

    Adapted from flopy's get-modflow utility. Supports ':' alone for
    interactive selection, or a prefix of one of the shortcuts returned by
    `get_bindir_shortcut_map` (e.g. ':python', ':prev').
    """
    options = get_bindir_shortcut_map(program)

    if bindir_arg == ":":
        indexed_options = dict(enumerate(options.keys(), 1))
        print("Select a number to choose installation directory:")
        for idx, shortcut in indexed_options.items():
            opt_path, opt_info = options[shortcut]
            print(f"  {idx}: '{opt_path}' -- {opt_info} ('{shortcut}')")

        max_tries = 3
        for attempt in range(max_tries):
            try:
                res = input("> ")
                choice_idx = int(res)
                if choice_idx not in indexed_options:
                    raise ValueError("Invalid option number")
                selected_shortcut = indexed_options[choice_idx]
                return options[selected_shortcut][0].resolve()
            except (ValueError, KeyError):
                if attempt < max_tries - 1:
                    print("Invalid option, try again")
                else:
                    raise ProgramInstallationError(
                        "Invalid option selected, too many attempts"
                    ) from None
    else:
        bindir_lower = bindir_arg.lower()
        matches = [opt for opt in options if opt.startswith(bindir_lower)]
        if len(matches) == 0:
            available = ", ".join(options.keys())
            raise ProgramInstallationError(
                f"Invalid bindir shortcut '{bindir_arg}'. Available: {available}"
            )
        elif len(matches) > 1:
            raise ProgramInstallationError(
                f"Ambiguous bindir shortcut '{bindir_arg}'. Matches: {', '.join(matches)}"
            )
        return options[matches[0]][0].resolve()

    raise ProgramInstallationError("Failed to select bindir")


class ProgramCache:
    """Local cache directories for downloaded release archives."""

    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else _CACHE_ROOT / "programs"
        self.archives_dir = self.root / "archives"
        self.metadata_dir = self.root / "metadata"

    def get_archive_dir(self, repo: str, tag: str, platform: str) -> Path:
        return self.archives_dir / repo / tag / platform

    def clear_archives(self) -> None:
        if self.archives_dir.exists():
            shutil.rmtree(self.archives_dir)


_DEFAULT_CACHE = ProgramCache()
"""Default program cache instance"""


@dataclass
class ProgramInstallation:
    """A single installation of a program, recorded in its ledger."""

    version: str
    platform: str
    bindir: Path
    installed_at: datetime
    source: dict[str, str]
    """Free-form provenance, e.g. {'repo': 'MODFLOW-ORG/modflow6', 'tag': '6.8.0'}
    or {'origin': 'conda-forge'} - not a registry reference."""
    executables: list[str]


class InstallationMetadata:
    """Manages the installation ledger for a single program name."""

    def __init__(self, program: str):
        self.program = program
        self.metadata_file = _DEFAULT_CACHE.metadata_dir / f"{program}.json"
        self.installations: list[ProgramInstallation] = []

    def load(self) -> bool:
        if not self.metadata_file.exists():
            return False
        try:
            with self.metadata_file.open("r") as f:
                data = json.load(f)
            self.installations = [
                ProgramInstallation(
                    version=inst["version"],
                    platform=inst["platform"],
                    bindir=Path(inst["bindir"]),
                    installed_at=datetime.fromisoformat(inst["installed_at"]),
                    source=inst["source"],
                    executables=inst["executables"],
                )
                for inst in data.get("installations", [])
            ]
            return True
        except (json.JSONDecodeError, KeyError, ValueError):
            self.installations = []
            return False

    def save(self) -> None:
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "program": self.program,
            "installations": [
                {
                    "version": inst.version,
                    "platform": inst.platform,
                    "bindir": str(inst.bindir),
                    "installed_at": inst.installed_at.isoformat(),
                    "source": inst.source,
                    "executables": inst.executables,
                }
                for inst in self.installations
            ],
        }
        with self.metadata_file.open("w") as f:
            json.dump(data, f, indent=2)

    def add_installation(self, installation: ProgramInstallation) -> None:
        """Merge into the on-disk ledger. Reloads first, so this is safe to call
        on a fresh instance (e.g. one `InstallationMetadata(program)` per call,
        as `register_installation`/`install_program` do) without clobbering
        installations recorded by earlier calls."""
        self.load()
        self.installations = [
            inst
            for inst in self.installations
            if not (inst.version == installation.version and inst.bindir == installation.bindir)
        ]
        self.installations.append(installation)
        self.save()

    def remove_installation(self, version: str, bindir: Path) -> None:
        """Merge into the on-disk ledger; see `add_installation`."""
        self.load()
        self.installations = [
            inst
            for inst in self.installations
            if not (inst.version == version and inst.bindir == bindir)
        ]
        self.save()

    def list_installations(self) -> list[ProgramInstallation]:
        return self.installations.copy()


def install_program(
    program: str | None = None,
    *,
    repo: str = DEFAULT_REPO,
    owner: str = DEFAULT_OWNER,
    version: str = "latest",
    bindir: str | Path | None = None,
    platform: str | None = None,
    subset: str | list[str] | set[str] | None = None,
    force: bool = False,
    verbose: bool = False,
    tries: int | None = None,
    delay: float | None = None,
) -> list[ProgramInstallation]:
    """
    Download and install MODFLOW-ecosystem program executables from a GitHub
    release, and record each in its own program's installation ledger.

    Parameters
    ----------
    program : str, optional
        A single program to install (e.g. "mf6"). If omitted and `subset` is
        also omitted, every program in the release is installed - matching
        get_modflow.py's default behavior.
    repo : str
        Any repo under `owner` with a GitHub release and an ostag-matching
        asset - not restricted to `KNOWN_REPOS` (default: "executables", the
        combined legacy distribution). Individual program repos work directly,
        e.g. repo="mfnwt" or repo="gridgen".
    owner : str
        GitHub repository owner; override to test against a fork.
    version : str
        Release tag, or "latest".
    bindir : str | Path, optional
        Installation directory. Auto-selected (see `get_bindir_options`) if
        omitted.
    platform : str, optional
        Ostag override; auto-detected if omitted.
    subset : str | list[str] | set[str], optional
        Multiple programs to install from a combined release, e.g.
        "mf6,zbud6" or {"mf6", "zbud6"}.
    force : bool
        Re-download the archive even if already cached.

    Returns
    -------
    list[ProgramInstallation]
        One entry per installed program.
    """
    ostag = platform or get_platform()
    subset = _normalize_subset(program, subset)

    release = get_release(owner, repo, version, tries=tries, delay=delay)
    tag = release["tag_name"]
    asset = _select_asset(release, ostag)

    if bindir is None:
        options = get_bindir_options(program)
        if not options:
            raise ProgramInstallationError("no writable installation directory found")
        bindir = options[0]
        if verbose:
            print(f"selected installation directory: {bindir}")
    else:
        bindir = Path(bindir)
        bindir.mkdir(parents=True, exist_ok=True)

    archive_path = _DEFAULT_CACHE.get_archive_dir(repo, tag, ostag) / asset["name"]
    download_archive(
        url=asset["browser_download_url"],
        dest=archive_path,
        force=force,
        verbose=verbose,
        tries=tries,
        delay=delay,
    )

    extracted = extract_release_archive(
        archive_path,
        bindir,
        release_tag=tag,
        ostag=ostag,
        subset=subset,
        verbose=verbose,
    )

    installed_at = datetime.now(UTC)
    source = {"repo": f"{owner}/{repo}", "tag": tag, "asset_url": asset["browser_download_url"]}
    installations = []
    for prog in extracted:
        installation = ProgramInstallation(
            version=prog.version,
            platform=ostag,
            bindir=bindir,
            installed_at=installed_at,
            source=dict(source),
            executables=[prog.path.name],
        )
        InstallationMetadata(prog.name).add_installation(installation)
        installations.append(installation)

    return installations


def register_installation(
    program: str,
    version: str,
    bindir: str | Path,
    executables: list[str],
    *,
    source: str | dict[str, str] | None = None,
    platform: str | None = None,
    installed_at: datetime | None = None,
) -> ProgramInstallation:
    """
    Record an installation that happened by some other means (conda-forge, a
    manual build, a different tool) in this program's ledger, so
    `get_executable`/`list_installed` can find it. This is the source-agnostic
    hook other installers can call - `install_program` uses it internally too.
    """
    installation = ProgramInstallation(
        version=version,
        platform=platform or get_platform(),
        bindir=Path(bindir),
        installed_at=installed_at or datetime.now(UTC),
        source=source if isinstance(source, dict) else {"origin": source or "manual"},
        executables=list(executables),
    )
    InstallationMetadata(program).add_installation(installation)
    return installation


def uninstall_program(
    program: str,
    version: str | None = None,
    bindir: str | Path | None = None,
    all_versions: bool = False,
    delete_files: bool = True,
    verbose: bool = False,
) -> None:
    """Uninstall program executable(s) and remove them from the ledger."""
    metadata = InstallationMetadata(program)
    if not metadata.load():
        if verbose:
            print(f"no installation metadata found for {program}")
        return

    if all_versions:
        to_remove = metadata.list_installations()
    else:
        if version is None:
            raise ValueError("must specify version or set all_versions=True")
        to_remove = [
            inst
            for inst in metadata.list_installations()
            if inst.version == version and (bindir is None or inst.bindir == Path(bindir))
        ]

    if not to_remove:
        if verbose:
            print("no matching installations found")
        return

    for inst in to_remove:
        if delete_files:
            for exe_name in inst.executables:
                exe_path = inst.bindir / exe_name
                if exe_path.exists():
                    exe_path.unlink()
                    if verbose:
                        print(f"  removed {exe_path}")
        metadata.remove_installation(inst.version, inst.bindir)

    if verbose:
        print(f"successfully uninstalled {program}")


def get_executable(
    program: str,
    version: str | None = None,
    bindir: str | Path | None = None,
) -> Path | None:
    """Look up the path to an installed program's executable, or None if not found."""
    metadata = InstallationMetadata(program)
    if not metadata.load():
        return None

    installations = metadata.list_installations()
    if version is not None:
        installations = [i for i in installations if i.version == version]
    if bindir is not None:
        bindir = Path(bindir)
        installations = [i for i in installations if i.bindir == bindir]
    if not installations:
        return None

    latest = max(installations, key=lambda i: i.installed_at)
    for exe_name in latest.executables:
        exe_path = latest.bindir / exe_name
        if exe_path.exists():
            return exe_path
    return None


def list_installed(program: str | None = None) -> dict[str, list[ProgramInstallation]]:
    """List installed programs from the ledger."""
    result: dict[str, list[ProgramInstallation]] = {}
    metadata_dir = _DEFAULT_CACHE.metadata_dir
    if not metadata_dir.exists():
        return result
    for metadata_file in metadata_dir.glob("*.json"):
        program_name = metadata_file.stem
        if program and program_name != program:
            continue
        metadata = InstallationMetadata(program_name)
        if metadata.load():
            installations = metadata.list_installations()
            if installations:
                result[program_name] = installations
    return result


__all__ = [
    "DEFAULT_OWNER",
    "DEFAULT_REPO",
    "KNOWN_REPOS",
    "_DEFAULT_CACHE",
    "InstallationMetadata",
    "ProgramCache",
    "ProgramInstallation",
    "ProgramInstallationError",
    "download_archive",
    "extract_release_archive",
    "get_bindir_options",
    "get_bindir_shortcut_map",
    "get_executable",
    "get_platform",
    "get_release",
    "get_releases",
    "install_program",
    "list_installed",
    "register_installation",
    "select_bindir",
    "uninstall_program",
]
