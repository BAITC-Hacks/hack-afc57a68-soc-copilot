"""FastAPI-бэкенд OrgTrace.

POST /api/analyze        — загрузить документы «до» и «после», получить отчёт JSON
POST /api/analyze/demo   — прогон на контрольном комплекте из data/samples
GET  /api/report/{id}.md — отчёт в Markdown
POST /api/chat           — вопрос эксперта к документам (Function Calling, нужен OPENAI_API_KEY)
GET  /health
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Literal

from app import config
from app.pipeline import analyze, chat_tools, get_run
from app.uploads import save_upload, DocumentInputError
from app.report import to_markdown
from app.agent import llm

app = FastAPI(title="OrgTrace API", version="1.0.0",
              description="ИИ-агент анализа организационной структуры и функционала")

SAMPLES = Path(__file__).resolve().parents[1] / 'data/samples'
DEMO_BEFORE = SAMPLES / "polozhenie_red08_protocol13.pdf"
DEMO_AFTER = SAMPLES / "polozhenie_red09_protocol7.pdf"


@app.get("/health")
def health():
    return {"status": "ok", "llm": config.USE_LLM, "similarity": config.SIMILARITY_BACKEND}


def _save(upload: UploadFile, folder: str, role: str) -> str:
    return save_upload(upload.file, upload.filename, folder, role)


@app.post("/api/analyze")
def analyze_endpoint(before: UploadFile = File(...), after: UploadFile = File(...),
                     mode: Literal['deterministic', 'llm'] = Form('deterministic')):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            report = analyze(_save(before, tmp, 'before'), _save(after, tmp, 'after'), mode=mode)
    except (DocumentInputError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return json.loads(report.model_dump_json())


@app.post("/api/analyze/demo")
def analyze_demo(mode: Literal['deterministic', 'llm'] = 'deterministic'):
    try:
        report = analyze(str(DEMO_BEFORE), str(DEMO_AFTER), mode=mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return json.loads(report.model_dump_json())


@app.get("/api/report/{run_id}.md", response_class=PlainTextResponse)
def report_md(run_id: str):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(404, "run_id не найден")
    return to_markdown(run['report'])


class ChatIn(BaseModel):
    run_id: str
    question: str = Field(min_length=1, max_length=4000)


@app.post("/api/chat")
def chat_endpoint(body: ChatIn):
    if get_run(body.run_id) is None:
        raise HTTPException(404, "Сначала выполните анализ (run_id не найден)")
    res = llm.chat(body.question, chat_tools(body.run_id))
    if res is None:
        raise HTTPException(503, "Чат требует OPENAI_API_KEY")
    if res.get('error'):
        raise HTTPException(503, res['answer'])
    return res
