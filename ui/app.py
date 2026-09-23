"""Streamlit-интерфейс OrgTrace. Агент запускается в том же процессе (без отдельного API),
чтобы деплой был одним сервисом."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import config  # noqa: E402
from app.agent import llm  # noqa: E402
from app.pipeline import RUNS, analyze, chat_tools, load_cached_report  # noqa: E402
from app.report import SEV_RU, to_markdown  # noqa: E402

st.set_page_config(page_title="OrgTrace", page_icon="🧭", layout="wide")
st.title("🧭 OrgTrace — анализ оргструктуры и функционала")
st.caption("Сравнение документов «до» и «после» реорганизации: потери, переносы и дублирование функций, "
           "конфликты интересов. Каждый вывод — со ссылкой на пункт и страницу, цитаты сверены программно.")

SAMPLES = ROOT / "data" / "samples"

with st.sidebar:
    st.header("Документы")
    before = st.file_uploader("ДО реорганизации (PDF/DOCX/XLSX)", type=["pdf", "docx", "xlsx"])
    after = st.file_uploader("ПОСЛЕ реорганизации (PDF/DOCX/XLSX)", type=["pdf", "docx", "xlsx"])
    run_btn = st.button("▶ Запустить агента", type="primary", disabled=not (before and after))
    st.divider()
    demo_btn = st.button("Демо: Положение о ВА, ред. 8 → ред. 9")
    use_cache = st.checkbox("Использовать сохранённый результат демо", value=config.USE_CACHE)
    st.divider()
    st.write(f"Режим: **{'LLM + правила' if config.USE_LLM else 'детерминированный'}**")
    st.write(f"Сходство: **{config.SIMILARITY_BACKEND}**")


def run(before_path: str, after_path: str):
    with st.status("Агент работает…", expanded=True) as status:
        def on_step(rec: dict):
            status.write(f"**{rec['tool']}** — {rec['summary']} ({rec['ms']} мс)")
        report = analyze(before_path, after_path, on_step=on_step)
        status.update(label="Анализ завершён", state="complete", expanded=False)
    st.session_state["report"] = report


if run_btn and before and after:
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for up in (before, after):
            p = os.path.join(tmp, up.name)
            Path(p).write_bytes(up.getvalue())
            paths.append(p)
        run(*paths)

if demo_btn:
    cached = load_cached_report() if use_cache else None
    if cached:
        st.session_state["report"] = cached
        st.info("Показан сохранённый результат демо (demo_cache/report_08_09.json).")
    else:
        run(str(SAMPLES / "polozhenie_red08_protocol13.pdf"), str(SAMPLES / "polozhenie_red09_protocol7.pdf"))

report = st.session_state.get("report")
if not report:
    st.info("Загрузите два документа или нажмите «Демо» в боковой панели.")
    st.stop()

s = report.summary
c = st.columns(6)
c[0].metric("Создано подразделений", s["units"]["created"])
c[1].metric("Реорганизовано", s["units"]["reorganized"])
c[2].metric("Потеряно функций", s["functions"]["lost"], f"+{s['functions']['partially_lost']} частично",
            delta_color="off")
c[3].metric("Дублирование", s["duplications"])
c[4].metric("Конфликты интересов", s["conflicts_of_interest"])
c[5].metric("Дефекты документа", s["document_defects"])
st.caption(f"Непроверенных выводов: {s['unverified']} · run_id: {report.meta['run_id']}")
if report.executive_summary:
    st.success(report.executive_summary)


def show(findings):
    if not findings:
        st.write("_Не выявлено._")
    for f in findings:
        badge = "✔" if f.verified else "✖"
        with st.expander(f"{badge} {f.id} · {SEV_RU[f.severity]} · {f.title}"):
            cols = st.columns(len(f.evidence) or 1)
            for col, e in zip(cols, f.evidence):
                role = {"source": "Было", "target": "Стало", "closest": "Ближайший аналог",
                        "support": "См. также"}.get(e.role, e.role)
                col.markdown(f"**{role}** · `{e.doc_id}` п. **{e.clause}**, стр. {e.page}")
                col.markdown(f"> {e.quote}")
            st.markdown(f"**Обоснование.** {f.rationale}")
            if f.recommendation:
                st.markdown(f"**Рекомендация.** {f.recommendation}")
            st.caption(f"Метод: {f.method} · уверенность {f.confidence:.2f} · {f.verify_note}")


tabs = st.tabs(["Структура", "Потери функций", "Переносы", "Дублирование", "Конфликты интересов",
                "Дефекты", "Ход агента", "Отчёт", "Вопрос агенту"])
with tabs[0]:
    rows = [{"Было": ", ".join(f.units_before) or "—", "Стало": ", ".join(f.units_after) or "—",
             "Статус": f.type, "Источник": "; ".join(f"{e.doc_id} п.{e.clause} стр.{e.page}" for e in f.evidence)}
            for f in report.structure_changes]
    st.dataframe(rows, width="stretch", hide_index=True)
    show(report.structure_changes)
with tabs[1]:
    show([f for f in report.function_findings if f.type in ("lost", "partially_lost")])
with tabs[2]:
    show([f for f in report.function_findings if f.type in ("moved", "removed_duplicate")])
with tabs[3]:
    show(report.duplications)
with tabs[4]:
    show(report.conflicts_of_interest)
with tabs[5]:
    show(report.document_defects)
with tabs[6]:
    st.dataframe(report.agent_trace, width="stretch", hide_index=True)
with tabs[7]:
    md = to_markdown(report)
    st.download_button("Скачать отчёт (Markdown)", md, file_name="orgtrace_report.md")
    st.download_button("Скачать отчёт (JSON)", report.model_dump_json(indent=2), file_name="orgtrace_report.json")
    st.markdown(md)
with tabs[8]:
    if not config.USE_LLM:
        st.warning("Для чата с агентом (Function Calling) задайте OPENAI_API_KEY.")
    elif report.meta["run_id"] not in RUNS:
        st.warning("Чат доступен после живого запуска анализа (не для кэшированного результата).")
    else:
        q = st.text_input("Например: «Какие права ДККМ исчезли в новой редакции?»")
        if q:
            with st.spinner("Агент вызывает инструменты…"):
                res = llm.chat(q, chat_tools(report.meta["run_id"]))
            st.markdown(res["answer"])
            st.caption("Вызовы инструментов: " + ", ".join(f"{t['tool']}({t['args']})" for t in res["tool_calls"]))
