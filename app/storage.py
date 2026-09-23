"""SQLite result cache shared by UI/API, including recoverable source clauses."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from importlib.metadata import version
from contextlib import contextmanager
from pathlib import Path

from app import config
from app.models import Document, Report
from app.runtime import similarity_backend


def cache_identity(before: str, after: str, mode: str) -> tuple[str, dict]:
    # Code changes invalidate results, including prompts and parsing rules.
    engine = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob('*.py')):
        engine.update(path.relative_to(root).as_posix().encode())
        engine.update(path.read_bytes())
    hashes = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (before, after)]
    settings = {'engine': engine.hexdigest(), 'mode': mode,
                'backend': similarity_backend(), 'llm_model': config.LLM_MODEL if mode == 'llm' else None,
                'embedding_model': config.EMBEDDING_MODEL if similarity_backend() == 'openai' else None,
                'formats': [Path(p).suffix.lower() for p in (before, after)], 'sha256': hashes}
    settings['dependencies'] = {name: version(name) for name in ('pymupdf', 'scikit-learn', 'rapidfuzz', 'langgraph', 'openai', 'python-docx', 'openpyxl')}
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    return key, settings


@contextmanager
def database():
    path = Path(config.CACHE_DIR) / 'orgtrace.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=180)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS analyses (cache_key TEXT PRIMARY KEY, '
                   'run_id TEXT UNIQUE NOT NULL, report TEXT NOT NULL, state TEXT NOT NULL)')
        db.commit()
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def serialize_state(state: dict) -> str:
    return json.dumps({'docs': {k: d.model_dump() for k, d in state['docs'].items()},
                       'before_id': state['before_id'], 'after_id': state['after_id'],
                       'plan': state.get('plan', [])}, ensure_ascii=False)


def deserialize_run(row) -> dict | None:
    if not row:
        return None
    report, raw = Report.model_validate_json(row[0]), json.loads(row[1])
    raw['docs'] = {k: Document.model_validate(d) for k, d in raw['docs'].items()}
    return {'report': report, 'state': raw}
