"""Единая точка входа для API и UI: запуск агента, хранение запусков, инструменты чата."""
from __future__ import annotations

import json
import os
from typing import Callable

from app import config
from app.agent.graph import run_agent
from app.models import Report
from app.report import build_report

RUNS: dict[str, dict] = {}          # run_id -> {"report": Report, "state": AgentState}


def analyze(before_path: str, after_path: str,
            on_step: Callable[[dict], None] | None = None) -> Report:
    state = run_agent(before_path, after_path, on_step=on_step)
    report = build_report(state)
    RUNS[report.meta["run_id"]] = {"report": report, "state": state}
    os.makedirs("runs", exist_ok=True)
    with open(f"runs/{report.meta['run_id']}.json", "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    return report


def load_cached_report() -> Report | None:
    if not os.path.exists(config.DEMO_CACHE_FILE):
        return None
    with open(config.DEMO_CACHE_FILE, encoding="utf-8") as f:
        return Report(**json.load(f))


def chat_tools(run_id: str) -> dict:
    """Реализации инструментов для Function Calling (см. app/agent/llm.py: TOOLS)."""
    run = RUNS[run_id]
    state, report = run["state"], run["report"]
    docs, tk = state["docs"], state["toolkit"]

    def resolve_doc_id(doc_id: str) -> str:
        return {"D_BEFORE": state["before_id"], "D_AFTER": state["after_id"]}.get(doc_id, doc_id)

    def search_clauses(query: str, doc_id: str = "", top_k: int = 5):
        doc_id = resolve_doc_id(doc_id)
        if doc_id and doc_id not in docs:
            return {"error": "документ не найден", "available_doc_ids": list(docs)}
        pool = [c for d in docs.values() if not doc_id or d.doc_id == doc_id for c in d.clauses]
        if not pool:
            return []
        sims = tk.sim.matrix([query], [c.text for c in pool])[0]
        idx = sims.argsort()[::-1][:top_k]
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
