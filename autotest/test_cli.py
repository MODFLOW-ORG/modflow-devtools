from types import SimpleNamespace

import pytest

from modflow_devtools import cli


class _Registry:
    def __init__(self, release_id, cache_path, error=None):
        self.release_id = release_id
        self.cache_path = cache_path
        self._error = error

    def sync(self):
        if self._error:
            raise self._error


class _ModelConfig:
    def __init__(self, failed):
        self._failed = failed

    def sync(self):
        return {"src": SimpleNamespace(failed=self._failed)}


@pytest.fixture
def fake_registries(monkeypatch, tmp_path):
    def _fake(dfn_error=None, model_failed=()):
        from modflow_devtools.dfns.registry import RemoteDfnRegistry
        from modflow_devtools.models import ModelSourceConfig

        registry = _Registry("owner/repo@1.0", tmp_path, dfn_error)
        monkeypatch.setattr(RemoteDfnRegistry, "load_default", lambda: {"r": registry})
        monkeypatch.setattr(ModelSourceConfig, "load", lambda: _ModelConfig(list(model_failed)))

    return _fake


def test_sync_all_succeeds(fake_registries, capsys):
    fake_registries()
    assert cli._sync_all() == 0
    assert "All registries synced!" in capsys.readouterr().out


def test_sync_all_fails_on_dfn_error(fake_registries, capsys):
    fake_registries(dfn_error=OSError("no network"))
    assert cli._sync_all() == 1
    assert "Failed to sync owner/repo@1.0: no network" in capsys.readouterr().out


def test_sync_all_fails_on_model_error(fake_registries, capsys):
    fake_registries(model_failed=[("current", "models.toml not found")])
    assert cli._sync_all() == 1
    assert "Models synced successfully" not in capsys.readouterr().out
