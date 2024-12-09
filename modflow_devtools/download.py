import json
import os
import sys
import tarfile
import timeit
import urllib.request
from os import PathLike
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4
from warnings import warn

from modflow_devtools.zip import MFZipFile


def get_request(url, params={}):
    """
    Get urllib.request.Request, with parameters and headers.

    This bears a GitHub API authentication token if github.com is
    in the URL and the GITHUB_TOKEN environment variable is set.

    Originally written by Mike Toews (mwtoews@gmail.com) for FloPy.
    """
    if isinstance(params, dict):
        if len(params) > 0:
            url += "?" + urllib.parse.urlencode(params)
    else:
        raise TypeError("data must be a dict")
    headers = {}

    if "github.com" in url:
        github_token = os.environ.get("GITHUB_TOKEN", None)
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

    return urllib.request.Request(url, headers=headers)


def get_releases(
    repo, per_page=30, max_pages=10, retries=3, verbose=False
) -> list[dict]:
    """
    Get available releases for the given repository.

    Parameters
    ----------
    repo: str
        The repository (format must be owner/name)
    per_page : int
        The number of artifacts to return per page (must be between 1-100, inclusive)
    max_pages : int
        The maximum number of pages to retrieve
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to suppress verbose output
    """

    if "/" not in repo:
        raise ValueError("repo format must be owner/name")

    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive int")

    params = {}
    if per_page is not None:
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params["per_page"] = per_page

    req_url = f"https://api.github.com/repos/{repo}/releases"
    page = 1

    def get_response_json():
        tries = 0
        params["page"] = page
        request = get_request(req_url, params=params)
        while True:
            tries += 1
            try:
                if verbose:
                    print(
                        f"Fetching releases for "
                        f"repo {repo} "
                        f"(page {page}, "
                        f"{per_page} per page)"
                    )
                with urllib.request.urlopen(request, timeout=10) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as err:
                if err.code == 401 and os.environ.get("GITHUB_TOKEN"):
                    raise ValueError("GITHUB_TOKEN is invalid") from err
                elif err.code == 403 and "rate limit exceeded" in err.reason:
                    raise ValueError(
                        f"use GITHUB_TOKEN env to bypass rate limit ({err})"
                    ) from err
                elif err.code in (404, 503) and tries < retries:
                    # GitHub sometimes returns this error for valid URLs, so retry
                    warn(f"URL request try {tries} failed ({err})")
                    continue
                raise RuntimeError(f"cannot retrieve data from {req_url}") from err

    releases = []
    max_pages = max_pages if max_pages else sys.maxsize
    while page <= max_pages:
        rels = get_response_json()
        page += 1
        releases.extend(rels)
        if not any(rels) or len(rels) < per_page:
            break

    if verbose:
        print(f"Found {len(releases)} releases for {repo}")

    return releases


def get_release(repo, tag="latest", retries=3, verbose=False) -> dict:
    """
    Get info about a particular repository release.

    Parameters
    ----------
    repo : str
        The repository (format must be owner/name)
    tag : str
        The release tag to retrieve assets for
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to suppress verbose output
    """

    if "/" not in repo:
        raise ValueError("repo format must be owner/name")

    if not isinstance(tag, str) or not any(tag):
        raise ValueError("tag must be a non-empty string")

    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive int")

    req_url = f"https://api.github.com/repos/{repo}"
    req_url = (
        f"{req_url}/releases/latest"
        if tag == "latest"
        else f"{req_url}/releases/tags/{tag}"
    )
    request = get_request(req_url)
    releases = None
    num_tries = 0

    while True:
        num_tries += 1
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                result = resp.read()
                remaining = resp.headers.get("x-ratelimit-remaining", None)
                if remaining and int(remaining) <= 10:
                    warn(
                        f"Only {remaining} GitHub API requests remaining "
                        "before rate-limiting"
                    )
                break
        except urllib.error.HTTPError as err:
            if err.code == 401 and os.environ.get("GITHUB_TOKEN"):
                raise ValueError("GITHUB_TOKEN env is invalid") from err
            elif err.code == 403 and "rate limit exceeded" in err.reason:
                raise ValueError(
                    f"use GITHUB_TOKEN env to bypass rate limit ({err})"
                ) from err
            elif err.code == 404:
                if releases is None:
                    releases = get_releases(repo, verbose=verbose)
                if tag not in releases:
                    raise ValueError(
                        f"Release {tag} not found (choose from {', '.join(releases)})"
                    )
            elif err.code == 503 and num_tries < retries:
                # GitHub sometimes returns this error for valid URLs, so retry
                warn(f"URL request {num_tries} failed ({err})")
                continue
            raise RuntimeError(f"cannot retrieve data from {req_url}") from err

    release = json.loads(result.decode())
    tag_name = release["tag_name"]
    if verbose:
        print(f"fetched release {tag_name!r} info from {repo}")

    return release


def get_latest_version(repo, retries=3, verbose=False) -> str:
    """
    Get the repository's latest release version tag.

    Parameters
    ----------
    repo : str
        The repository (format must be owner/name)
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to show verbose output

    Returns
    -------
        The latest release tag name (a string).
    """

    if "/" not in repo:
        raise ValueError("repo format must be owner/name")

    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive int")

    release = get_release(repo, retries=retries, verbose=verbose)
    return release["tag_name"]


def get_release_assets(
    repo, tag="latest", simple=False, retries=3, verbose=False
) -> Union[dict, list[dict]]:
    """
    Get assets corresponding to the given release.

    Parameters
    ----------
    repo : str
        The repository (format must be owner/name)
    tag : str
        The release tag to retrieve assets for
    simple : bool
        If True, return a dict mapping asset names to download URLs, otherwise (by
        default) a list of dicts containing asset info as returned by the GitHub API
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to show verbose output

    Returns
    -------
        A list of dicts if simple is False, one per release asset.
        If simple is True, a dict mapping asset names to download URLs.
    """

    if "/" not in repo:
        raise ValueError("repo format must be owner/name")

    if not isinstance(tag, str) or not any(tag):
        raise ValueError("tag must be a non-empty string")

    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive int")

    release = get_release(repo, tag=tag, retries=retries, verbose=verbose)
    return (
        {a["name"]: a["browser_download_url"] for a in release["assets"]}
        if simple
        else release["assets"]
    )


def list_artifacts(
    repo, name=None, per_page=30, max_pages=10, retries=3, verbose=False
) -> list[dict]:
    """
    List artifacts for the given repository, optionally filtering by name (exact match).
    If more artifacts are available than will fit within the given page size, by default
    requests are made until all artifacts are retrieved. The number of requests made can
    be limited with the max_pages parameter.

    Parameters
    ----------
    repo : str
        The repository (format must be owner/name)
    name : str
        The artifact name (must be an exact match)
    per_page : int
        The number of artifacts to return per page (must be between 1-100, inclusive)
    max_pages : int
        The maximum number of pages to retrieve (i.e. the number of requests to make)
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to show verbose output

    Returns
    -------
        A list of dictionaries, each containing information
        about an artifact as returned by the GitHub API.
    """

    if "/" not in repo:
        raise ValueError("repo format must be owner/name")

    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive int")

    msg = f"artifact(s) for {repo}" + (f" matching name {name}" if name else "")
    req_url = f"https://api.github.com/repos/{repo}/actions/artifacts"
    page = 1
    params = {}

    if name is not None:
        if not isinstance(name, str) or len(name) == 0:
            raise ValueError("name must be a non-empty string")
        params["name"] = name

    if per_page is not None:
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        params["per_page"] = int(per_page)

    def get_response_json():
        tries = 0
        params["page"] = page
        request = get_request(req_url, params=params)
        while True:
            tries += 1
            try:
                if verbose:
                    print(f"Fetching {msg} (page {page}, {per_page} per page)")
                with urllib.request.urlopen(request, timeout=10) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as err:
                if err.code == 401 and os.environ.get("GITHUB_TOKEN"):
                    raise ValueError("GITHUB_TOKEN env is invalid") from err
                elif err.code == 403 and "rate limit exceeded" in err.reason:
                    raise ValueError(
                        f"use GITHUB_TOKEN env to bypass rate limit ({err})"
                    ) from err
                elif err.code in (404, 503) and tries < retries:
                    # GitHub sometimes returns this error for valid URLs, so retry
                    warn(f"URL request try {tries} failed ({err})")
                    continue
                raise RuntimeError(f"cannot retrieve data from {req_url}") from err

    artifacts = []
    diff = 1
    max_pages = max_pages if max_pages else sys.maxsize
    while diff > 0 and page <= max_pages:
        result = get_response_json()
        total = result["total_count"]
        if page == 1:
            print(f"Repo {repo} has {total} artifact(s)")

        page += 1
        artifacts.extend(result["artifacts"])
        diff = total - len(artifacts)

    if verbose:
        print(f"Found {len(artifacts)} {msg}")

    return artifacts


def download_artifact(
    repo,
    id,
    path: Optional[PathLike] = None,
    delete_zip=True,
    retries=3,
    verbose=False,
):
    """
    Download and unzip a GitHub Actions artifact, selected by its ID.

    Parameters
    ----------
    repo : str
        The repository (format must be owner/name)
    id : str
        The artifact ID
    path : PathLike
        Path where the zip file will be saved (default is current path)
    delete_zip : bool
        Whether the zip file should be deleted after it is unzipped (default is True)
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to show verbose output
    """

    if "/" not in repo:
        raise ValueError("repo format must be owner/name")

    if not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be a positive int")

    req_url = f"https://api.github.com/repos/{repo}/actions/artifacts/{id}/zip"
    request = urllib.request.Request(req_url)
    if "github.com" in req_url:
        github_token = os.environ.get("GITHUB_TOKEN", None)
        if github_token:
            request.add_header("Authorization", f"Bearer {github_token}")

    zip_path = Path(path).expanduser().absolute() / f"{uuid4()!s}.zip"
    tries = 0
    while True:
        tries += 1
        try:
            with (
                urllib.request.urlopen(request) as url_file,
                zip_path.open("wb") as out_file,
            ):
                content = url_file.read()
                out_file.write(content)
                break
        except urllib.error.HTTPError as err:
            if tries < retries:
                warn(f"URL request try {tries} failed ({err})")
                continue
            else:
                raise RuntimeError(f"cannot retrieve data from {req_url}") from err

    if verbose:
        print(f"Uncompressing: {zip_path}")

    z = MFZipFile(zip_path)
    z.extractall(str(path))
    z.close()

    if delete_zip:
        if verbose:
            print(f"Deleting zipfile {zip_path}")
        zip_path.unlink()


def download_and_unzip(
    url: str,
    path: Optional[PathLike] = None,
    delete_zip=True,
    retries=3,
    verbose=False,
) -> Path:
    """
    Download and unzip a zip file from a URL.
    The filename must be the last element in the URL.

    Parameters
    ----------
    url : str
        The zipfile's download URL
    path : PathLike
        Path where the zip file will be saved (default is current path)
    delete_zip : bool
        Whether the zip file should be deleted after it is unzipped (default is True)
    retries : int
        The maximum number of retries for each request
    verbose : bool
        Whether to show verbose output

    Returns
    -------
    Path
        The path to the directory where the zip file was unzipped
    """
    if path:
        path = Path(path)
    else:
        path = Path.cwd()
    path.mkdir(exist_ok=True)

    if verbose:
        print(f"Downloading {url}")

    tic = timeit.default_timer()

    # download zip file
    file_path = path / url.split("/")[-1]
    request = urllib.request.Request(url)
    if "github.com" in url:
        github_token = os.environ.get("GITHUB_TOKEN", None)
        if github_token:
            request.add_header("Authorization", f"Bearer {github_token}")

    tries = 0
    while True:
        tries += 1
        try:
            with (
                urllib.request.urlopen(request) as url_file,
                file_path.open("wb") as out_file,
            ):
                content = url_file.read()
                out_file.write(content)

                # if verbose, print content length (if available)
                tag = "Content-length"
                if verbose and tag in url_file.headers:
                    file_size = url_file.headers[tag]
                    len_file_size = len(file_size)
                    file_size = int(file_size)

                    bfmt = "{:" + f"{len_file_size}" + ",d}"
                    sbfmt = "{:>" + f"{len(bfmt.format(int(file_size)))}" + "s} bytes"
                    print(f"   file size: {sbfmt.format(bfmt.format(int(file_size)))}")

                break
        except urllib.error.HTTPError as err:
            if tries < retries:
                warn(f"URL request try {tries} failed ({err})")
                continue

    # write the total download time
    toc = timeit.default_timer()
    tsec = round(toc - tic, 2)
    if verbose:
        print(f"\ntotal download time: {tsec} seconds")

    # Unzip the file, and delete zip file if successful.
    if "zip" in file_path.suffix or "exe" in file_path.suffix:
        z = MFZipFile(file_path)
        try:
            if verbose:
                print(f"Uncompressing: {file_path}")

            # extract the files
            z.extractall(str(path))
        except:  # noqa: E722
            p = "Could not unzip the file. Stopping."
            raise Exception(p)
        z.close()

        # delete the zipfile
        if delete_zip:
            if verbose:
                print(f"Deleting zipfile {file_path}")
            file_path.unlink()
    elif "tar" in file_path.suffix:
        ar = tarfile.open(file_path)
        ar.extractall(path=str(path))
        ar.close()

        # delete the zipfile
        if delete_zip:
            if verbose:
                print(f"Deleting zipfile {file_path}")
            file_path.unlink()

    if verbose:
        print(f"Done downloading and extracting {file_path.name} to {path}")

    return path
