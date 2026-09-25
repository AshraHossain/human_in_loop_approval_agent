import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path_factory, monkeypatch):
    """Keep the developer's own environment out of the tests.

    `load_config` reads `HITL_*` from the environment and `.env` from the
    working directory. Both are correct for a CLI and both would make the
    suite pass or fail depending on whose laptop it runs on, so every test
    starts from a clean environment in an empty directory.
    """
    for key in [k for k in os.environ if k.startswith("HITL_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
