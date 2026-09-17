import json
from unittest.mock import MagicMock, patch

import pytest
from flaky import flaky

from modflow_devtools.dfns.registry import LocalDfnRegistry, RemoteDfnRegistry


def test_latest_tag_exact_tag():
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@6.6.0")
    assert registry.latest_tag() == "6.6.0"
    assert registry._latest is None  # no network call, nothing cached


def test_latest_tag_resolves_via_api():
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"tag_name": "v6.6.1"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch(
        "modflow_devtools.dfns.registry.urllib.request.urlopen",
        return_value=mock_response,
    ) as mock_open:
        tag = registry.latest_tag()

    assert tag == "v6.6.1"
    assert registry._latest == "v6.6.1"
    mock_open.assert_called_once_with(
        "https://api.github.com/repos/MODFLOW-ORG/modflow6/releases/latest"
    )


def test_latest_tag_cached():
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"tag_name": "v6.6.1"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch(
        "modflow_devtools.dfns.registry.urllib.request.urlopen",
        return_value=mock_response,
    ) as mock_open:
        registry.latest_tag()
        registry.latest_tag()

    mock_open.assert_called_once()  # second call uses cached _latest


def test_cache_path_latest_uses_resolved_tag():
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"tag_name": "v6.6.1"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("modflow_devtools.dfns.registry.urllib.request.urlopen", return_value=mock_response):
        cache_dir = registry.cache_path

    assert "latest" not in str(cache_dir)
    assert "v6.6.1" in str(cache_dir)
    assert "modflow6" in str(cache_dir)


def test_cached_tag_exact_not_cached(tmp_path):
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@6.6.0")
    with patch.object(
        type(registry),
        "cache_path",
        new_callable=lambda: property(lambda self: tmp_path / "empty"),
    ):
        assert registry.cached_tag() is None


def test_cached_tag_exact_cached(tmp_path):
    cache_dir = tmp_path / "populated"
    cache_dir.mkdir()
    (cache_dir / "gwf-chd.toml").write_text("name = 'gwf-chd'")
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@6.6.0")
    with patch.object(
        type(registry),
        "cache_path",
        new_callable=lambda: property(lambda self: cache_dir),
    ):
        assert registry.cached_tag() == "6.6.0"


def test_cached_tag_latest_not_cached(tmp_path):
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")
    with patch.object(RemoteDfnRegistry, "base_cache_path", return_value=tmp_path):
        assert registry.cached_tag() is None


def test_cached_tag_latest_cached(tmp_path):
    repo_cache = tmp_path / "MODFLOW-ORG" / "modflow6"
    tag_dir = repo_cache / "6.7.0"
    tag_dir.mkdir(parents=True)
    (tag_dir / "gwf-chd.toml").write_text("name = 'gwf-chd'")

    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")
    with patch.object(RemoteDfnRegistry, "base_cache_path", return_value=tmp_path):
        assert registry.cached_tag() == "6.7.0"


def test_cmd_info_no_network(tmp_path, capsys):
    from modflow_devtools.dfns.__main__ import cmd_info

    repo_cache = tmp_path / "MODFLOW-ORG" / "modflow6"
    tag_dir = repo_cache / "6.7.0"
    tag_dir.mkdir(parents=True)
    (tag_dir / "gwf-chd.toml").write_text("name = 'gwf-chd'")

    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")

    with (
        patch.object(
            RemoteDfnRegistry,
            "load_default",
            return_value={"MODFLOW-ORG/modflow6@latest": registry},
        ),
        patch.object(RemoteDfnRegistry, "base_cache_path", return_value=tmp_path),
        patch("modflow_devtools.dfns.registry.urllib.request.urlopen") as mock_open,
    ):
        import argparse

        result = cmd_info(argparse.Namespace())

    mock_open.assert_not_called()
    assert result == 0
    out = capsys.readouterr().out
    assert "Cached" in out
    assert "6.7.0" in out
    assert "latest" in out


@pytest.mark.skip(reason="Requires network access to GitHub API")
@flaky(max_runs=3, min_passes=1)
def test_latest_tag_live():
    registry = RemoteDfnRegistry(release_id="MODFLOW-ORG/modflow6@latest")
    tag = registry.latest_tag()
    assert tag.startswith("v") or tag[0].isdigit()
    assert registry._latest == tag


def test_local_dfn_registry(dfn_dir):
    registry = LocalDfnRegistry(path=dfn_dir)
    assert registry.path == dfn_dir.resolve()

    spec = registry.spec()
    assert spec.schema_version == "2.0.0.dev3"
    assert len(spec.components) > 100
    assert "gwf-chd" in spec.components
    assert "sim-nam" in spec.components

    dfn = spec.components["gwf-chd"]
    assert dfn.name == "gwf-chd"
    assert dfn.parent == "gwf-nam"

    path = registry.get_path("gwf-chd")
    assert path.exists()
    assert path.name == "gwf-chd.dfn"

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        registry.get_path("nonexistent")


def test_remote_dfn_registry_init():
    release_id = "MODFLOW-ORG/modflow6@6.6.0"
    registry = RemoteDfnRegistry(release_id=release_id)
    assert registry.release_id == release_id

    cache_dir = registry.cache_path
    assert "modflow6" in str(cache_dir)
    assert "6.6.0" in str(cache_dir)


@pytest.mark.skip(reason="Requires dfns.zip release asset on GitHub")
@flaky(max_runs=3, min_passes=1)
def test_remote_dfn_registry_sync():
    release_id = "MODFLOW-ORG/modflow6@6.6.0"
    registry = RemoteDfnRegistry(release_id=release_id)
    registry.sync(force=True)

    cache_dir = registry.cache_path
    assert cache_dir.exists()
    assert any(cache_dir.iterdir())

    path = registry.get_path("gwf-chd")
    assert path.exists()

    spec = registry.spec()
    assert "gwf-chd" in spec.components
    assert "sim-nam" in spec.components

    dfn = spec.components["gwf-chd"]
    assert dfn.name == "gwf-chd"
