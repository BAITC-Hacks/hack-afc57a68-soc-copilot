import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("USE_LLM", "0")          # тесты детерминированные, без API-ключа
os.environ.setdefault("SIMILARITY_BACKEND", "tfidf")

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
