import pytest

from fbreels import config, jobs


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep tests away from the real .fbreels/ settings, jobs and downloads."""
    state = tmp_path / "state"
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(config, "STATE_DIR", state)
    monkeypatch.setattr(config, "SETTINGS_FILE", state / "settings.json")
    monkeypatch.setattr(jobs, "STATE_DIR", state)
    monkeypatch.setattr(jobs, "JOBS_FILE", state / "jobs.json")
    monkeypatch.setitem(config.DEFAULT_SETTINGS, "output_dir", str(downloads))
    return tmp_path
