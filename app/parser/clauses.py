"""Нарезка текста нормативного документа на пункты с сохранением страницы.

Учитывает особенности PDF-выгрузок положений:
* номер страницы — отдельная последняя строка страницы (удаляется);
* пункты бывают склеены в одну строку: «...Общества. 3.10.Работники могут...»;
* разделы тоже склеиваются: «...мероприятий. 10.Контроль качества»;
* выровненный по ширине текст даёт по слову на строку;
* подпункты «а.», «б.» ... привязываются к последнему номерному пункту;
* оглавление в конце документа игнорируется.
"""
from __future__ import annotations

import re
from typing import Iterable

from app.models import Clause

NUM_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.\s*(.*)$")
LETTER_RE = re.compile(r"^([а-яё])\.(?:\s+(.*))?$")
# Вставной номер пункта внутри строки (после точки/точки с запятой/двоеточия)
INLINE_CLAUSE_RE = re.compile(
    r"(?<=[^\d.][.;:»)])\s+(?=\d{1,2}(?:\.\d{1,2}){1,3}\.\s?[А-ЯЁа-яё])"
)
# Вставной заголовок раздела: «... мероприятий. 10.Контроль качества»
INLINE_LETTER_RE = re.compile(r"(?<=[:;])\s+(?=[а-яё]\.\s)")
INLINE_SECTION_RE = re.compile(r"(?<=[^\d.][.;:])\s+(?=\d{1,2}\.\s?[А-ЯЁ][а-яё])")
TOC_MARKERS = ("оглавление",)


def _split_inline(line: str) -> list[str]:
    parts = INLINE_CLAUSE_RE.split(line)
    out: list[str] = []
    for p in parts:
        for q in INLINE_SECTION_RE.split(p):
            out.extend(INLINE_LETTER_RE.split(q))
    return [p.strip() for p in out if p and p.strip()]


def _parent_of(number: str) -> str | None:
    if "." not in number:
        return None
    return number.rsplit(".", 1)[0]


def split_into_clauses(
    pages: Iterable[tuple[int, str]], doc_id: str, edition: str
) -> tuple[list[Clause], list[dict]]:
    """pages: [(page_no, text)]. Возвращает (пункты, аномалии нумерации)."""
    clauses: list[Clause] = []
    anomalies: list[dict] = []
    seen: dict[str, int] = {}
    current: Clause | None = None
    last_numbered: Clause | None = None
    section_title = ""
    section_top = 0

    def uniq(number: str) -> str:
        if number in seen:
            seen[number] += 1
            return f"{number}#{seen[number]}"
        seen[number] = 1
        return number

    for page_no, text in pages:
        lines = [l.strip() for l in text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        if lines and lines[-1].isdigit():          # номер страницы
            lines.pop()
        stop = False
        for raw in lines:
            if not raw:
                continue
            if raw.lower().strip() in TOC_MARKERS:
                stop = True
                break
            for line in _split_inline(raw):
                m = NUM_RE.match(line)
                if m and (
                    "." in m.group(1) or re.match(r"^[А-ЯЁ]", m.group(2) or "")
                ):
                    number, body = m.group(1), m.group(2)
                    top = int(number.split(".")[0])
                    if "." not in number:                       # заголовок раздела
                        section_top = top
                        section_title = f"{top}. {body.split('  ')[0]}".strip()
                    elif section_top and top != section_top and top != section_top + 1:
                        anomalies.append({"number": number, "page": page_no,
                                          "expected_section": section_top, "text": body[:120]})
                    else:
                        section_top = top
                    number = uniq(number)
                    current = Clause(
                        clause_id=f"{doc_id}:{number}", doc_id=doc_id, edition=edition,
                        number=number, text=body, page=page_no, section=section_title,
                        parent=_parent_of(number.split("#")[0]), depth=number.count(".") + 1,
                        source_pages={page_no: body},
                    )
                    clauses.append(current)
                    last_numbered = current
                    continue
                lm = LETTER_RE.match(line)
                if lm and last_numbered is not None:
                    number = uniq(f"{last_numbered.number.split('#')[0]}.{lm.group(1)}")
                    current = Clause(
                        clause_id=f"{doc_id}:{number}", doc_id=doc_id, edition=edition,
                        number=number, text=lm.group(2) or "", page=page_no, section=section_title,
                        parent=last_numbered.number, depth=last_numbered.depth + 1,
                        source_pages={page_no: lm.group(2) or ""},
                    )
                    clauses.append(current)
                    continue
                if current is not None:                    # продолжение пункта
                    current.text = (current.text + " " + line).strip()
                    current.source_pages[page_no] = (current.source_pages.get(page_no, '') + ' ' + line).strip()
        if stop:
            break

    for c in clauses:
        c.text = re.sub(r"\s+", " ", c.text).strip()
    parents = {c.parent for c in clauses if c.parent}
    for c in clauses:
        c.is_leaf = c.number not in parents
    return clauses, anomalies
