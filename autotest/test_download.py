import pytest
from flaky import flaky

from modflow_devtools.download import (
    download_and_unzip,
    get_release,
    get_releases,
)
from modflow_devtools.markers import requires_github

_repos = [
    "MODFLOW-ORG/modflow6",
    "MODFLOW-ORG/modflow6-nightly-build",
    "MODFLOW-ORG/executables",
]


@pytest.mark.parametrize("per_page", [-1, 0, 1.5, 101, 1000])
@pytest.mark.parametrize("retries", [-1, 0, 1.5])
def test_get_releases_bad_params(per_page, retries):
    with pytest.raises(ValueError):
        get_releases("executables", per_page=per_page, retries=retries, verbose=True)


@flaky
@requires_github
@pytest.mark.parametrize("repo", _repos)
def test_get_releases(repo):
    releases = get_releases(repo, verbose=True)
    assert any(releases)
    assert all("created_at" in r for r in releases)

    assets = [a for aa in [r["assets"] for r in releases] for a in aa]
    assert all(repo in a["browser_download_url"] for a in assets)

    # test page size option
    if repo == "MODFLOW-ORG/modflow6-nightly-build":
        assert len(releases) <= 31  # 30-day retention period


@flaky
@requires_github
@pytest.mark.parametrize("repo", _repos)
def test_get_release(repo):
    tag = "latest"
    release = get_release(repo, tag, verbose=True)
    assets = release["assets"]
    expected_names = ["linux.zip", "mac.zip", "win64.zip"]
    actual_names = [asset["name"] for asset in assets]

    if repo == "MODFLOW-ORG/modflow6":
        # can remove if modflow6 releases follow asset name
        # conventions followed in executables and nightly build repos
        assert {a.rpartition("_")[2] for a in actual_names} >= {
            a for a in expected_names if not a.startswith("win")
        }
    else:
        assert set(actual_names) >= set(expected_names)


@flaky
@requires_github
@pytest.mark.parametrize("delete_zip", [True, False])
def test_download_and_unzip(function_tmpdir, delete_zip):
    zip_name = "mf6.3.0_linux.zip"
    dir_name = zip_name.replace(".zip", "")
    url = f"https://github.com/MODFLOW-ORG/modflow6/releases/download/6.3.0/{zip_name}"
    download_and_unzip(url, function_tmpdir, delete_zip=delete_zip, verbose=True)

    assert (function_tmpdir / zip_name).is_file() != delete_zip

    dir_path = function_tmpdir / dir_name
    assert dir_path.is_dir()

    contents = list(dir_path.rglob("*"))
    assert len(contents) > 0
