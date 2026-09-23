import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ['USE_LLM'] = '0'          # Never send external requests from tests, even with a local .env.
os.environ['SIMILARITY_BACKEND'] = 'tfidf'


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, 'CACHE_DIR', str(tmp_path / 'cache'))

BEFORE = "data/samples/polozhenie_red08_protocol13.pdf"
AFTER = "data/samples/polozhenie_red09_protocol7.pdf"


@pytest.fixture(scope="session")
def state():
    from app.agent.graph import run_agent
    return run_agent(BEFORE, AFTER)


@pytest.fixture(scope="session")
def report(state):
    from app.report import build_report
    return build_report(state)
