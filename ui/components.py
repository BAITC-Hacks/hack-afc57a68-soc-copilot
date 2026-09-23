"""Safe presentation helpers: source text is always HTML-escaped."""
from __future__ import annotations

import difflib
import html
import re
from pathlib import Path

import streamlit as st

TYPE_LABELS = {
    'created': 'Создано', 'kept': 'Сохранено', 'reorganized': 'Реорганизовано',
    'removed': 'Упразднено', 'lost': 'Потеря функции', 'partially_lost': 'Частичная потеря',
    'moved': 'Перенос функции', 'removed_duplicate': 'Устранено дублирование',
    'duplication': 'Дублирование', 'cross_subordination': 'Перекрёстное подчинение',
    'self_review': 'Риск самопроверки', 'governance_role': 'Управленческая роль',
    'broken_cross_reference': 'Сломанная ссылка', 'dangling_reference': 'Ссылка без адресата',
    'empty_clause': 'Пустой пункт', 'unknown_role': 'Неизвестная должность',
}
SEVERITIES = {'high': 'Высокая', 'medium': 'Средняя', 'low': 'Низкая', 'info': 'Информация'}


def style():
    st.html('<style>' + Path(__file__).with_name('styles.css').read_text(encoding='utf-8') + '</style>')


def safe(text) -> str:
    return html.escape(str(text), quote=True)


def word_diff(before: str, after: str) -> tuple[str, str]:
    """Directional token diff. Whitespace and punctuation remain visible."""
    left, right = re.findall(r'\s+|\w+|[^\w\s]', before), re.findall(r'\s+|\w+|[^\w\s]', after)
    a, b = [], []
    for tag, i, j, k, l in difflib.SequenceMatcher(None, left, right, autojunk=False).get_opcodes():
        old, new = safe(''.join(left[i:j])), safe(''.join(right[k:l]))
        if tag == 'equal':
            a.append(old)
            b.append(new)
        else:
            if old:
                a.append(f'<mark class="diff-{ "change" if tag == "replace" else "remove" }">{old}</mark>')
            if new:
                b.append(f'<mark class="diff-{ "change" if tag == "replace" else "add" }">{new}</mark>')
    return ''.join(a), ''.join(b)


def source_panel(label: str, clause, content: str, doc=None):
    kind = getattr(doc, 'kind', 'pdf')
    location = 'условный блок' if kind == 'docx' else 'лист' if kind == 'xlsx' else 'стр.'
    address = f'Пункт {clause.number} · {location} {clause.page}' if clause else 'Источник не указан'
    st.html(f'<div class="source-panel"><div class="source-label">{safe(label)}</div>'
            f'<div class="source-address">{safe(address)}</div>'
            f'<div class="source-text">{content or "Нет текста для сравнения."}</div></div>')


def all_findings(report):
    return (report.structure_changes + report.function_findings + report.duplications
            + report.conflicts_of_interest + report.document_defects + report.unverified_findings)


def show_finding(finding, run):
    f = finding
    st.html(f'<div class="finding-heading"><span class="severity {safe(f.severity)}">'
            f'{safe(SEVERITIES[f.severity])}</span><span class="eyebrow">{safe(f.id)} / '
            f'{safe(TYPE_LABELS.get(f.type, f.type))}</span></div>')
    st.subheader(f.title, anchor=False)
    st.write(f.rationale)
    if f.recommendation:
        st.info(f.recommendation, icon=':material/lightbulb:')
    if not f.verified:
        st.error('Источник не подтверждён: ' + f.verify_note)
    else:
        st.caption('Цитаты проверены дословно. Смысловой вывод требует оценки эксперта.')
    docs = run['state']['docs'] if run else {}
    before_id = run['state']['before_id'] if run else None
    groups = [[e for e in f.evidence if e.doc_id == before_id],
              [e for e in f.evidence if e.doc_id != before_id]]
    for col, evidence, label in zip(st.columns(2), groups, ['ДО РЕОРГАНИЗАЦИИ', 'ПОСЛЕ РЕОРГАНИЗАЦИИ']):
        with col:
            st.caption(label)
            if not evidence:
                st.caption('В этой редакции источник не указан.')
            for e in evidence:
                doc = docs.get(e.doc_id)
                location = 'условный блок' if doc and doc.kind == 'docx' else 'лист' if doc and doc.kind == 'xlsx' else 'стр.'
                st.html(f'<div class="quote"><div class="source-address">{safe(e.doc_id)} · '
                        f'п. {safe(e.clause)} · {location} {e.page}</div>'
                        f'<blockquote>{safe(e.quote) or "Пустой пункт"}</blockquote></div>')
    if docs and len(f.evidence) >= 2:
        left = next((e for e in f.evidence if e.doc_id == before_id), f.evidence[0])
        right = next((e for e in f.evidence if e.doc_id != left.doc_id), f.evidence[1])
        lc, rc = docs[left.doc_id].get(left.clause), docs[right.doc_id].get(right.clause)
        if lc and rc:
            with st.expander('Сравнить полные тексты пунктов', expanded=False):
                st.caption('Красный — удалено · зелёный — добавлено · жёлтый — заменено. Подсветка показывает текстовое различие, а не правовую оценку.')
                lh, rh = word_diff(lc.text, rc.text)
                for col, clause, content, docid in zip(st.columns(2), [lc, rc], [lh, rh], [left.doc_id, right.doc_id]):
                    with col:
                        source_panel(docid, clause, content, docs[docid])
