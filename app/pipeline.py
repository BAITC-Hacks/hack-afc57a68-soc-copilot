"""Единая точка входа для API и UI: запуск агента, хранение запусков, инструменты чата."""
from __future__ import annotations

import json
import os
from typing import Callable
from pathlib import Path

from app import config
from app.agent.graph import run_agent
from app.models import Report
from app.report import build_report
from app.runtime import analysis_mode
from app.storage import cache_identity, database, deserialize_run, serialize_state
from app.agent.similarity import Similarity, EmbeddingUnavailable
from app.uploads import DocumentInputError, MAX_UPLOAD_BYTES

RUNS: dict[str, dict] = {}          # run_id -> {"report": Report, "state": AgentState}


def analyze(before_path: str, after_path: str,
            on_step: Callable[[dict], None] | None = None,
            mode: str = 'deterministic') -> Report:
    for path in (before_path, after_path):
        if not Path(path).is_file() or not 0 < Path(path).stat().st_size <= MAX_UPLOAD_BYTES:
            raise DocumentInputError('Документ отсутствует, пуст или превышает 25 МБ.')
    with analysis_mode(mode), database() as db:
        key, settings = cache_identity(before_path, after_path, mode)
        # A transaction prevents duplicate paid requests from concurrent workers.
        db.execute('BEGIN IMMEDIATE')
        cached = deserialize_run(db.execute('SELECT report, state FROM analyses WHERE cache_key=?', (key,)).fetchone())
        if cached:
            report = cached['report'].model_copy(deep=True)
            report.meta['cache_hit'] = True
            if on_step:
                on_step({'step': 'cache', 'tool': 'Кэш результатов', 'summary': 'Документы и настройки совпадают. Восстановлен сохранённый анализ.', 'ms': 0})
            return report
        try:
            state = run_agent(before_path, after_path, on_step=on_step)
            report = build_report(state)
        except EmbeddingUnavailable:
            # Restart the whole comparison; never mix TF-IDF and embedding vectors/thresholds.
            with analysis_mode('deterministic'):
                state = run_agent(before_path, after_path, on_step=on_step)
                state.setdefault('warnings', []).append('Эмбеддинги OpenAI недоступны. Анализ полностью выполнен в детерминированном режиме.')
                report = build_report(state)
        report.meta.update({'cache_key': key, 'cache_hit': False, 'analysis_settings': settings})
        for item, digest in zip(report.meta['documents'], settings['sha256']):
            item['sha256'] = digest
        db.execute('INSERT INTO analyses VALUES (?, ?, ?, ?)',
                   (key, report.meta['run_id'], report.model_dump_json(), serialize_state(state)))
    # Sources are persisted in SQLite; keep only a small compatibility memory cache.
    if len(RUNS) >= 8:
        RUNS.pop(next(iter(RUNS)))
    RUNS[report.meta['run_id']] = {'report': report, 'state': state}
    Path('runs').mkdir(exist_ok=True)
    Path(f"runs/{report.meta['run_id']}.json").write_text(report.model_dump_json(indent=2), encoding='utf-8')
    return report


def get_run(run_id: str) -> dict | None:
    if run_id in RUNS:
        return RUNS[run_id]
    with database() as db:
        return deserialize_run(db.execute('SELECT report, state FROM analyses WHERE run_id=?', (run_id,)).fetchone())


def load_cached_report() -> Report | None:
    if not os.path.exists(config.DEMO_CACHE_FILE):
        return None
    with open(config.DEMO_CACHE_FILE, encoding="utf-8") as f:
        return Report(**json.load(f))


def chat_tools(run_id: str) -> dict:
    """Реализации инструментов для Function Calling (см. app/agent/llm.py: TOOLS)."""
    run = get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    state, report = run["state"], run["report"]
    docs = state["docs"]
    sim = Similarity('tfidf').fit([c.text for d in docs.values() for c in d.clauses])

    def resolve_doc_id(doc_id: str) -> str:
        return {"D_BEFORE": state["before_id"], "D_AFTER": state["after_id"]}.get(doc_id, doc_id)

    def search_clauses(query: str, doc_id: str = "", top_k: int = 5):
        doc_id = resolve_doc_id(doc_id)
        if doc_id and doc_id not in docs:
            return {"error": "документ не найден", "available_doc_ids": list(docs)}
        pool = [c for d in docs.values() if not doc_id or d.doc_id == doc_id for c in d.clauses]
        if not pool:
            return []
        sims = sim.matrix([query], [c.text for c in pool])[0]
        idx = sims.argsort(kind='stable')[::-1][:max(1, min(top_k, 10000))]
        return [{"doc_id": pool[i].doc_id, "number": pool[i].number, "page": pool[i].page,
                 "owner": pool[i].owner_units, "text": pool[i].text[:600],
                 "score": round(float(sims[i]), 3)} for i in idx]

    def get_clause(doc_id: str, number: str):
        d = docs.get(resolve_doc_id(doc_id))
        c = d.get(number) if d else None
        return c.model_dump() if c else {"error": "пункт не найден"}

    def list_findings(category: str):
        items = {"structure": report.structure_changes, "function": report.function_findings,
                 "duplication": report.duplications, "conflict": report.conflicts_of_interest,
                 "defect": report.document_defects}.get(category, [])
        return [f.model_dump() for f in items]

    return {"search_clauses": search_clauses, "get_clause": get_clause, "list_findings": list_findings}
