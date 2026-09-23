"""Проверка дословного вхождения цитат и адресов; смысл вывода оценивает эксперт."""
from __future__ import annotations

import re
from app.models import Clause, Document, Finding


def literal_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def quote_page(clause: Clause, quote: str) -> int | None:
    """Locate the entire literal quote, including its actual starting page."""
    q = literal_text(quote)
    if not q or q not in literal_text(clause.text):
        return None
    if not clause.source_pages:
        return clause.page
    parts = [(p, literal_text(t)) for p, t in clause.source_pages.items() if literal_text(t)]
    offset = ' '.join(t for _, t in parts).find(q)
    if offset < 0:
        return None
    cursor = 0
    for page, text in parts:
        if offset < cursor + len(text):
            return page
        cursor += len(text) + 1
    return None


def _empty_evidence(f: Finding, clause: Clause, quote: str) -> bool:
    return (f.category == 'defect' and f.type == 'empty_clause'
            and not literal_text(quote) and not clause.text.strip(' \t\n;.,'))


def _find(docs: dict[str, Document], doc_id: str, number: str):
    d = docs.get(doc_id)
    return d.get(number) if d else None


def verify(findings: list[Finding], docs: dict[str, Document]) -> tuple[list[Finding], list[Finding]]:
    """Возвращает (прошедшие, не прошедшие). Меняет поля verified/verify_note."""
    ok, bad = [], []
    for f in findings:
        problems = []
        if not f.evidence:
            problems.append("нет доказательств")
        for e in f.evidence:
            c = _find(docs, e.doc_id, e.clause)
            if c is None:
                problems.append(f"пункт {e.doc_id}:{e.clause} не найден")
                continue
            page = c.page if _empty_evidence(f, c, e.quote) else quote_page(c, e.quote)
            if page is None:
                problems.append(f"дословная цитата не найдена в п. {e.clause}")
            elif page != e.page:
                problems.append(f"страница {e.page} ≠ {page} для п. {e.clause}")
        f.verified = not problems
        f.verify_note = "; ".join(problems) if problems else "цитаты сверены с текстом пунктов"
        (ok if f.verified else bad).append(f)
    return ok, bad


def repair(findings: list[Finding], docs: dict[str, Document]) -> list[Finding]:
    """Исправляет страницу только существующей дословной цитаты, не подменяя текст."""
    for f in findings:
        for e in f.evidence:
            c = _find(docs, e.doc_id, e.clause)
            if c is None:
                continue
            page = c.page if _empty_evidence(f, c, e.quote) else quote_page(c, e.quote)
            if page is not None:
                e.page = page
    return findings
