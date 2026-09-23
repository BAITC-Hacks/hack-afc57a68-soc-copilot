"""One source of truth for metric counts and OR-based category filtering."""
from __future__ import annotations

from collections.abc import Iterable

from app.models import Finding


FILTERS = {
    'Создано': lambda f: f.type == 'created',
    'Реорганизовано': lambda f: f.type == 'reorganized',
    'Структура': lambda f: f.category == 'structure',
    'Потери': lambda f: f.type == 'lost',
    'Частичные потери': lambda f: f.type == 'partially_lost',
    'Переносы': lambda f: f.type == 'moved',
    'Устранено дублирование': lambda f: f.type == 'removed_duplicate',
    'Дублирование': lambda f: f.category == 'duplication',
    'Конфликты': lambda f: f.category == 'conflict',
    'Дефекты': lambda f: f.category == 'defect',
    'Не подтверждено': lambda f: not f.verified,
}

METRICS = (
    ('Создано подразделений', 'Создано'),
    ('Реорганизовано', 'Реорганизовано'),
    ('Потеряно функций', 'Потери'),
    ('Частично потеряно', 'Частичные потери'),
    ('Перенесено функций', 'Переносы'),
    ('Дублирование', 'Дублирование'),
    ('Конфликты интересов', 'Конфликты'),
    ('Дефекты документа', 'Дефекты'),
)


def toggle_selection(selected: Iterable[str], name: str) -> list[str]:
    """Return a new selection; clicking an active card switches it off."""
    values = list(dict.fromkeys(value for value in selected if value in FILTERS))
    if name not in FILTERS:
        return values
    return [value for value in values if value != name] if name in values else [*values, name]


def filter_findings(findings: Iterable[Finding], categories: Iterable[str],
                    severity: str | None = None, query: str = '') -> list[Finding]:
    predicates = [FILTERS[name] for name in categories if name in FILTERS]
    needle = query.strip().casefold()
    return [finding for finding in findings
            if (not predicates or any(matches(finding) for matches in predicates))
            and (not severity or finding.severity == severity)
            and (not needle or needle in ' '.join([
                finding.title, finding.rationale, *finding.units_before, *finding.units_after,
                *[e.clause + ' ' + e.quote for e in finding.evidence],
            ]).casefold())]
