"""FastAPI-бэкенд OrgTrace.

POST /api/analyze        — загрузить документы «до» и «после», получить отчёт JSON
POST /api/analyze/demo   — прогон на контрольном комплекте из data/samples
GET  /api/report/{id}.md — отчёт в Markdown
POST /api/chat           — вопрос эксперта к документам (Function Calling, нужен OPENAI_API_KEY)
GET  /health
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app import config
from app.pipeline import analyze, chat_tools, load_cached_report, RUNS
from app.report import to_markdown
from app.agent import llm

app = FastAPI(title="OrgTrace API", version="1.0.0",
              description="ИИ-агент анализа организационной структуры и функционала")

SAMPLES = Path("data/samples")
DEMO_BEFORE = SAMPLES / "polozhenie_red08_protocol13.pdf"
DEMO_AFTER = SAMPLES / "polozhenie_red09_protocol7.pdf"


@app.get("/health")
def health():
    return {"status": "ok", "llm": config.USE_LLM, "similarity": config.SIMILARITY_BACKEND}


def _save(upload: UploadFile, folder: str) -> str:
    suffix = Path(upload.filename or "file.pdf").suffix.lower()
    if suffix not in (".pdf", ".docx", ".xlsx", ".xlsm"):
        raise HTTPException(400, f"Формат {suffix} не поддерживается (PDF, DOCX, XLSX)")
    path = os.path.join(folder, Path(upload.filename).name)
    with open(path, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return path


@app.post("/api/analyze")
def analyze_endpoint(before: UploadFile = File(...), after: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as tmp:
        report = analyze(_save(before, tmp), _save(after, tmp))
    return json.loads(report.model_dump_json())


@app.post("/api/analyze/demo")
def analyze_demo():
    if config.USE_CACHE:
        report = load_cached_report()
        if report:
            return json.loads(report.model_dump_json())
    report = analyze(str(DEMO_BEFORE), str(DEMO_AFTER))
    return json.loads(report.model_dump_json())


@app.get("/api/report/{run_id}.md", response_class=PlainTextResponse)
def report_md(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "run_id не найден")
    return to_markdown(RUNS[run_id]["report"])


class ChatIn(BaseModel):
    run_id: str
    question: str


@app.post("/api/chat")
def chat_endpoint(body: ChatIn):
    if body.run_id not in RUNS:
        raise HTTPException(404, "Сначала выполните анализ (run_id не найден)")
    res = llm.chat(body.question, chat_tools(body.run_id))
    if res is None:
        raise HTTPException(503, "Чат требует OPENAI_API_KEY")
    return res
