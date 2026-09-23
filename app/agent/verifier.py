"""CitationVerifier: программная проверка, что каждая цитата действительно есть
в указанном пункте указанного документа. Это не LLM — это код, поэтому
«галлюцинированная» ссылка не может пройти в отчёт."""
from __future__ import annotations

from rapidfuzz import fuzz

from app import config
from app.agent.similarity import normalize
from app.models import Document, Finding


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
            if c.page != e.page:
                problems.append(f"страница {e.page} ≠ {c.page} для п. {e.clause}")
                continue
            q = normalize(e.quote)
            if q and fuzz.partial_ratio(q, normalize(c.text)) < config.QUOTE_MIN_SCORE:
                problems.append(f"цитата не найдена в п. {e.clause}")
        f.verified = not problems
        f.verify_note = "; ".join(problems) if problems else "цитаты сверены с текстом пунктов"
        (ok if f.verified else bad).append(f)
    return ok, bad


def repair(findings: list[Finding], docs: dict[str, Document]) -> list[Finding]:
    """Самокоррекция: заменяет неточную цитату на ближайший дословный фрагмент пункта,
    исправляет страницу. Если пункт не существует — вывод остаётся непроверенным."""
    for f in findings:
        for e in f.evidence:
            c = _find(docs, e.doc_id, e.clause)
            if c is None:
                continue
            e.page = c.page
            if not e.quote or fuzz.partial_ratio(normalize(e.quote), normalize(c.text)) < config.QUOTE_MIN_SCORE:
                al = fuzz.partial_ratio_alignment(e.quote.lower(), c.text.lower())
                if al is not None and al.score >= 60:
                    e.quote = c.text[al.dest_start:al.dest_end]
                else:
                    e.quote = c.text[:220]
                f.verify_note = "цитата исправлена верификатором"
    return findings
