"""Формирование итогового отчёта: JSON (модель Report) и Markdown для эксперта."""
from __future__ import annotations

import datetime as dt
import uuid

from app import config
from app.runtime import llm_enabled, similarity_backend
from app.models import Finding, Report

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
SEV_RU = {"high": "🔴 высокая", "medium": "🟠 средняя", "low": "🟡 низкая", "info": "⚪ инфо"}
DISCLAIMER = ("Выводы носят рекомендательный характер и требуют проверки ответственным сотрудником. "
              "Дословность цитат и адреса источников проверяются программно. Это не является проверкой "
              "смысловой интерпретации; неподтверждённые выводы вынесены отдельно.")


def build_report(state: dict) -> Report:
    findings: list[Finding] = sorted(state.get("findings", []),
                                     key=lambda f: (SEV_ORDER[f.severity], f.id))
    docs = state["docs"]
    by = lambda cat: [f for f in findings if f.category == cat]
    struct, func = by("structure"), by("function")
    summary = {
        "units": {t: sum(1 for f in struct if f.type == t)
                  for t in ("created", "kept", "reorganized", "removed")},
        "functions": {t: sum(1 for f in func if f.type == t)
                      for t in ("lost", "partially_lost", "moved", "removed_duplicate")},
        "duplications": len(by("duplication")),
        "conflicts_of_interest": len(by("conflict")),
        "document_defects": len(by("defect")),
        "unverified": len(state.get("unverified", [])),
    }
    meta = {
        "run_id": f"{dt.datetime.now(dt.timezone.utc).replace(tzinfo=None):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
        "mode": "llm" if llm_enabled() else "deterministic",
        "llm_model": config.LLM_MODEL if llm_enabled() else None,
        "similarity_backend": similarity_backend(),
        "warnings": state.get('warnings', []),
        "documents": [{"doc_id": d.doc_id, "file": d.file, "title": d.title, "edition": d.edition,
                       "approved": d.approved, "clauses": len(d.clauses), "kind": d.kind,
                       "role": "before" if d.doc_id == state["before_id"] else "after"}
                      for d in docs.values()],
        "disclaimer": DISCLAIMER,
    }
    return Report(meta=meta, summary=summary, structure_changes=struct, function_findings=func,
                  duplications=by("duplication"), conflicts_of_interest=by("conflict"),
                  document_defects=by("defect"), unverified_findings=state.get("unverified", []),
                  agent_trace=state.get("trace", []),
                  executive_summary=state.get("executive_summary", ""))


def _src(f: Finding) -> str:
    return "; ".join(f"{e.doc_id} п. {e.clause}, стр. {e.page}" for e in f.evidence)


def _quotes(f: Finding) -> str:
    role = {"source": "Источник", "target": "Новая редакция", "closest": "Ближайший аналог", "support": "См. также"}
    return "\n".join(f"> **{role.get(e.role, e.role)} ({e.doc_id}, п. {e.clause}, стр. {e.page}):** «{e.quote}»"
                     for e in f.evidence)


def _block(f: Finding) -> str:
    return (f"#### {f.id}. {f.title}\n\n"
            f"Критичность: {SEV_RU[f.severity]} · метод: {f.method} · "
            f"{'✔ проверено' if f.verified else '✖ не подтверждено'}\n\n"
            f"{_quotes(f)}\n\n**Обоснование.** {f.rationale}\n\n"
            + (f"**Рекомендация.** {f.recommendation}\n" if f.recommendation else ""))


def to_markdown(r: Report) -> str:
    d = {x["role"]: x for x in r.meta["documents"]}
    b, a = d.get("before", {}), d.get("after", {})
    s = r.summary
    out = [f"# Заключение OrgTrace: сравнение редакций «{a.get('title', '')}»\n",
           f"**До:** {b.get('file')} (ред. {b.get('edition')}, {b.get('approved')})  \n"
           f"**После:** {a.get('file')} (ред. {a.get('edition')}, {a.get('approved')})  \n"
           f"Режим: {r.meta['mode']}, запуск {r.meta['generated_at']}\n",
           "## 1. Резюме\n",
           f"| Показатель | Значение |\n|---|---|\n"
           f"| Подразделения: создано / сохранено / реорганизовано / упразднено | "
           f"{s['units']['created']} / {s['units']['kept']} / {s['units']['reorganized']} / {s['units']['removed']} |\n"
           f"| Потеряно функций / частично | {s['functions']['lost']} / {s['functions']['partially_lost']} |\n"
           f"| Перенесено функций | {s['functions']['moved']} |\n"
           f"| Дублирование | {s['duplications']} |\n"
           f"| Конфликты интересов | {s['conflicts_of_interest']} |\n"
           f"| Дефекты документа | {s['document_defects']} |\n"
           f"| Непроверенные выводы | {s['unverified']} |\n"]
    if r.executive_summary:
        out.append(r.executive_summary + "\n")

    out.append("## 2. Изменения оргструктуры\n")
    out.append("| Было | Стало | Статус | Источник |\n|---|---|---|---|")
    st = {"created": "создано", "kept": "сохранено", "reorganized": "реорганизовано", "removed": "упразднено"}
    for f in r.structure_changes:
        out.append(f"| {', '.join(f.units_before) or '—'} | {', '.join(f.units_after) or '—'} | "
                   f"{st.get(f.type, f.type)} | {_src(f)} |")
    out.append("")
    for f in r.structure_changes:
        out.append(_block(f))
    out.append("")

    sections = [
        ("3. Потери функций", [f for f in r.function_findings if f.type in ("lost", "partially_lost")]),
        ("4. Перенесённые функции и устранённое дублирование",
         [f for f in r.function_findings if f.type in ("moved", "removed_duplicate")]),
        ("5. Дублирование функций", r.duplications),
        ("6. Конфликты интересов", r.conflicts_of_interest),
        ("7. Дефекты документа", r.document_defects),
    ]
    for title, items in sections:
        out.append(f"## {title}\n")
        out.append("\n".join(_block(f) for f in items) if items else "_Не выявлено._\n")

    out.append("## 8. Рекомендации\n")
    recs = [f for f in r.function_findings + r.duplications + r.conflicts_of_interest + r.document_defects
            if f.severity in ("high", "medium") and f.recommendation]
    for f in recs:
        out.append(f"- [{f.id}] {f.recommendation} ({_src(f)})")
    if r.unverified_findings:
        out.append("\n## Непроверенные выводы\n")
        out += [_block(f) + '\nПричина: ' + f.verify_note for f in r.unverified_findings]
    if r.meta.get('warnings'):
        out.append('\n## Ограничения этого анализа\n')
        out.extend('- ' + w for w in r.meta['warnings'])
    out.append("\n## 9. Методология\n")
    out.append("Шаги агента: " + " → ".join(f"{t['tool']} ({t['summary']})" for t in r.agent_trace) + "\n")
    out.append(f"_{r.meta['disclaimer']}_\n")
    return "\n".join(out)
