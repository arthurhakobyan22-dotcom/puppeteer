"""Test isolation: never write the global call log or presets.json of the project, never inherit the offline switch."""
import pytest

@pytest.fixture(autouse=True)
def _isolated_stage_files(monkeypatch,tmp_path):
    import stages.calls,stages.presets
    monkeypatch.setattr(stages.calls,'GLOBAL_LOG',tmp_path/'calls.log')
    monkeypatch.setattr(stages.presets,'PRESETS_FILE',tmp_path/'presets.json')
    monkeypatch.delenv('PUPPETEER_OFFLINE',raising=False)
    yield
