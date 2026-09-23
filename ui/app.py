"""OrgTrace workspace: upload → choose a mode → explore traceable changes."""
from __future__ import annotations

import io
import logging
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config
from app.agent import llm
from app.pipeline import analyze, chat_tools, get_run
from app.report import to_markdown
from app.uploads import save_upload
from ui.branding import favicon_svg, logo_html
from ui.components import SEVERITIES, all_findings, safe, show_finding, source_panel, style, theme_switcher, word_diff
from ui.filters import FILTERS, METRICS, filter_findings, toggle_selection

st.set_page_config(page_title='OrgTrace · Сравнение документов', page_icon=favicon_svg(), layout='wide')
style()
theme_switcher()
st.session_state.setdefault('step', 1)
st.session_state.setdefault('history', {})
st.session_state.setdefault('active_filters', [])
st.session_state.setdefault('filter_revision', 0)


def clear_finding():
    st.session_state.pop('selected_finding', None)


def reset_filters():
    st.session_state.update(active_filters=[], finding_query='', finding_severity='Все уровни')
    st.session_state['filter_revision'] += 1
    clear_finding()


def toggle_filter(name):
    # Callbacks execute BEFORE rerendering, so every card immediately reflects
    # its new state (including cards rendered earlier in the same row).
    st.session_state['active_filters'] = toggle_selection(st.session_state['active_filters'], name)
    st.session_state['filter_revision'] += 1
    clear_finding()


def change_categories(revision):
    # Ignore delayed events from a picker rendered before the last card click.
    # A new widget identity prevents stale browser state from undoing that click.
    if revision != st.session_state['filter_revision']:
        return
    st.session_state['active_filters'] = list(st.session_state[f'filter_categories_{revision}'])
    clear_finding()


def select_finding(finding_id):
    st.session_state['selected_finding'] = finding_id


def reset():
    st.session_state['step'] = 1
    for key in ('report', 'sources', 'selected_finding', 'chat_messages', 'before_upload', 'after_upload', 'analysis_mode'):
        st.session_state.pop(key, None)
    reset_filters()


def execute(demo=False):
    mode = 'deterministic' if demo else st.session_state.get('analysis_mode', 'deterministic')
    try:
        with st.status('Сравниваем документы…', expanded=True) as status:
            progress = st.progress(0, text='Подготовка документов')
            phases = ['parse', 'plan', 'structure', 'struct_compare', 'loss', 'duplication', 'conflict', 'crossref', 'llm_review', 'verify', 'repair', 'report']
            def on_step(rec):
                value = 1.0 if rec['step'] == 'cache' else min((phases.index(rec['step']) + 1) / len(phases), 1.0)
                progress.progress(value, text=rec['summary'])
                status.write(rec['summary'])
            if demo:
                report = analyze(str(ROOT / 'data/samples/polozhenie_red08_protocol13.pdf'),
                                 str(ROOT / 'data/samples/polozhenie_red09_protocol7.pdf'), on_step, mode=mode)
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    paths = [save_upload(io.BytesIO(source['data']), source['name'], tmp, role)
                             for source, role in zip(st.session_state['sources'], ['before', 'after'])]
                    report = analyze(*paths, on_step=on_step, mode=mode)
            progress.progress(1.0, text='Источники проверены. Результаты готовы.')
            status.update(label='Анализ завершён', state='complete', expanded=False)
        st.session_state.update(report=report, step=3, chat_messages=[])
        reset_filters()
        st.session_state['history'][report.meta['run_id']] = report
        st.rerun()
    except ValueError as exc:
        st.error(str(exc), icon=':material/error:')
    except Exception:
        logging.getLogger(__name__).exception('Analysis failed')
        st.error('Не удалось завершить анализ. Проверьте документы и повторите запуск. Предыдущий результат сохранён.')


with st.sidebar:
    st.html(logo_html())
    st.caption('РАБОЧЕЕ ПРОСТРАНСТВО')
    st.button('Новое сравнение', icon=':material/add:', width='stretch', on_click=reset)
    demo_clicked = st.button('Открыть демо', icon=':material/play_circle:', width='stretch',
                             help='Контрольная пара: Положение о внутреннем аудите, редакции 8 и 9. Работает без OpenAI.')
    st.divider()
    st.caption('КАК ЭТО РАБОТАЕТ')
    st.markdown('**01** Загрузите две редакции\n\n**02** Выберите режим\n\n**03** Проверьте изменения')
    with st.expander('Что означает «цитата проверена»?'):
        st.write('Код проверяет, что вся цитата есть в указанном пункте и соответствует странице. Оценка потери или конфликта остаётся выводом для эксперта.')
    if st.session_state['history']:
        st.divider()
        st.caption('В ЭТОЙ СЕССИИ')
        for rid, item in reversed(list(st.session_state['history'].items())[-5:]):
            label = item.meta['generated_at'].replace('T', ' ')[:16] + ' · ' + ('AI' if item.meta['mode'] == 'llm' else 'Правила')
            if st.button(label, key='history_' + rid, width='stretch'):
                st.session_state.update(report=item, step=3, chat_messages=[])
                reset_filters()
                st.rerun()
    st.divider()
    st.caption('PDF · DOCX · XLSX\n\nДословные цитаты. Прозрачные источники.')

if demo_clicked:
    execute(demo=True)

step = st.session_state['step']
st.html('<div class="eyebrow">АНАЛИЗ ОРГАНИЗАЦИОННЫХ ИЗМЕНЕНИЙ</div>')
titles = {1: 'Каждое изменение — на виду', 2: 'Выберите глубину анализа', 3: 'Что изменилось в документах'}
st.title(titles[step])
st.html('<div class="stepper">' + ''.join(
    f'<div class="step {"active" if step == i else "done" if step > i else ""}"><small>0{i}</small>{label}</div>'
    for i, label in enumerate(['Документы', 'Режим анализа', 'Результаты'], 1)) + '</div>')

if step == 1:
    st.html('<div class="hero-copy">Сравните две редакции положения. Найдите потерянные функции, изменения структуры и противоречия — с цитатой для каждого вывода.</div>')
    uploads = []
    saved_sources = st.session_state.get('sources', [])
    for index, (col, label, hint, key) in enumerate(zip(st.columns(2, gap='large'),
            ['До реорганизации', 'После реорганизации'],
            ['Исходная редакция документа', 'Новая редакция для сравнения'],
            ['before_upload', 'after_upload'])):
        with col, st.container(border=True):
            st.subheader(label)
            st.caption(hint)
            up = st.file_uploader('Перетащите файл или выберите на компьютере', type=['pdf', 'docx', 'xlsx'],
                                  key=key, help='До 25 МБ. PDF должен содержать текстовый слой. Для точных страниц предпочтителен PDF.')
            saved = saved_sources[index] if index < len(saved_sources) else None
            uploads.append({'name': up.name, 'data': up.getvalue()} if up else saved)
            if up:
                st.caption(f'{up.name} · {up.size / 1024:.0f} КБ')
            elif saved:
                st.caption(f'Сохранён файл: {saved["name"]}. Загрузите другой, чтобы заменить его.')
    left, right = st.columns([2, 1])
    with left:
        st.caption('Одинаковые имена допустимы: документы сохраняются раздельно. Для первого знакомства откройте демо в боковой панели.')
    with right:
        if st.button('Продолжить', icon=':material/arrow_forward:', type='primary', width='stretch', disabled=not all(uploads)):
            if any(not 0 < len(up['data']) <= 25 * 1024 * 1024 for up in uploads):
                st.error('Выберите непустые файлы размером до 25 МБ.')
            else:
                st.session_state['sources'] = uploads
                st.session_state['step'] = 2
                st.rerun()
    st.html('<div class="footer">OrgTrace / Изменения структуры · Потери и переносы функций · Дублирование · Конфликты интересов · Дефекты документа</div>')
    st.stop()

if step == 2:
    sources = st.session_state['sources']
    for col, source, label in zip(st.columns(2), sources, ['ДО', 'ПОСЛЕ']):
        with col:
            st.html(f'<div class="document-chip"><span class="eyebrow">{label}</span><strong>{safe(source["name"])}</strong><small>{len(source["data"]) / 1024:.0f} КБ · готов к анализу</small></div>')
    if sources[0]['data'] == sources[1]['data']:
        st.warning('Вы загрузили одинаковые файлы. Изменений между редакциями не будет; внутренние дефекты всё ещё могут быть найдены.')
    labels = {'deterministic': 'Точный повтор · правила и сравнение текста', 'llm': 'AI-проверка · дополнительная оценка пограничных случаев'}
    with st.container(border=True):
        st.radio('Режим анализа', options=['deterministic', 'llm'] if config.USE_LLM else ['deterministic'],
                 format_func=labels.get, key='analysis_mode', help='Результаты сохраняются по содержимому файлов, версии алгоритма и режиму анализа.')
        if st.session_state.get('analysis_mode') == 'llm':
            st.info('Фрагменты документов будут переданы в OpenAI. Повтор этой пары с теми же настройками вернёт сохранённый результат без нового обращения к модели.')
        else:
            st.write('Воспроизводимый анализ без внешних запросов. Подходит для контрольной проверки и конфиденциальных документов.')
        if not config.USE_LLM:
            st.caption('AI-режим появится после настройки OPENAI_API_KEY и USE_LLM=1 на сервере.')
    st.caption('Поддерживается текстовый шаблон положения с функциями в разделе 5. Если часть структуры не распознана, вы увидите ограничение в отчёте.')
    a, b = st.columns([1, 2])
    with a:
        if st.button('Назад к документам', width='stretch'):
            st.session_state['step'] = 1
            st.rerun()
    with b:
        if st.button('Сравнить документы', type='primary', icon=':material/compare_arrows:', width='stretch'):
            execute()
    st.stop()

report = st.session_state['report']
run = get_run(report.meta['run_id'])
findings = all_findings(report)
summary = report.summary
for col, doc in zip(st.columns(2), report.meta['documents']):
    with col:
        label = 'ДО' if doc['role'] == 'before' else 'ПОСЛЕ'
        st.html(f'<div class="document-chip"><span class="eyebrow">{label} / РЕДАКЦИЯ {safe(doc["edition"] or "—")}</span><strong>{safe(doc["file"])}</strong><small>{doc["clauses"]} пунктов · {safe(doc.get("approved", ""))}</small></div>')
mode_label = 'Правила · без внешних запросов' if report.meta['mode'] == 'deterministic' else 'AI-проверка + правила'
st.caption(f'{mode_label} · {"Восстановлено из кэша" if report.meta.get("cache_hit") else "Анализ завершён"} · {len(findings)} выводов · {summary["unverified"]} без подтверждения')
for warning in report.meta.get('warnings', []):
    st.warning(warning)
st.caption('Выберите одну или несколько карточек. Категории объединяются; повторный клик снимает выбор. Без выбора показаны все категории.')
with st.container(key='metrics'):
    for offset in (0, 4):
        for col, (label, filter_name) in zip(st.columns(4), METRICS[offset:offset + 4]):
            value = sum(FILTERS[filter_name](finding) for finding in findings)
            active = filter_name in st.session_state['active_filters']
            with col:
                st.button(f'**{value}**\n\n{label}', key='metric_' + filter_name, width='stretch',
                          type='primary' if active else 'secondary', on_click=toggle_filter, args=(filter_name,),
                          help='Убрать категорию из фильтра' if active else 'Добавить категорию к фильтру')

overview, compare, export, trace, chat_tab = st.tabs(['Обзор изменений', 'Сравнение документов', 'Отчёт', 'Ход анализа', 'Вопрос агенту'])

with overview:
    c1, c2, c3 = st.columns([1.2, 1, 2])
    revision = st.session_state['filter_revision']
    c1.multiselect('Типы изменений', list(FILTERS), key=f'filter_categories_{revision}',
                   default=st.session_state['active_filters'], placeholder='Все категории',
                   on_change=change_categories, args=(revision,))
    active_filters = st.session_state['active_filters']
    severity = c2.selectbox('Критичность', ['Все уровни'] + list(SEVERITIES.values()), key='finding_severity')
    query = c3.text_input('Поиск по выводам и цитатам', placeholder='Подразделение, функция или номер пункта…', key='finding_query')
    severity_key = next((key for key, label in SEVERITIES.items() if label == severity), None)
    selected = filter_findings(findings, active_filters, severity_key, query)
    selected.sort(key=lambda f: (list(SEVERITIES).index(f.severity), f.id))
    st.button('Сбросить все фильтры', key='reset_filters', on_click=reset_filters,
              disabled=not (active_filters or query or severity_key))
    st.caption(f'Показано {len(selected)} из {len(findings)} выводов. Выберите вывод, чтобы проверить доказательства.')
    if not selected:
        st.info('По выбранным фильтрам изменений нет. Выберите другую категорию или очистите поиск.')
    else:
        if st.session_state.get('selected_finding') not in [f.id for f in selected]:
            st.session_state['selected_finding'] = selected[0].id
        left, right = st.columns([1, 2.2], gap='large')
        with left, st.container(height=590, key='finding_list'):
            for f in selected:
                st.button(f'{f.id} · {f.title}', key='finding_' + f.id, width='stretch',
                          type='primary' if st.session_state['selected_finding'] == f.id else 'secondary',
                          on_click=select_finding, args=(f.id,))
        with right:
            show_finding(next(f for f in selected if f.id == st.session_state['selected_finding']), run)

with compare:
    st.subheader('Две редакции рядом')
    st.caption('Сравните любой пункт с любым пунктом другой редакции. Красный — удалено, зелёный — добавлено, жёлтый — заменено.')
    if run:
        state = run['state']
        bdoc, adoc = state['docs'][state['before_id']], state['docs'][state['after_id']]
        current = next((f for f in findings if f.id == st.session_state.get('selected_finding')), None)
        choices = []
        for col, doc, label in zip(st.columns(2), [bdoc, adoc], ['Пункт в старой редакции', 'Пункт в новой редакции']):
            numbers = [c.number for c in doc.clauses]
            evidence = next((e for e in current.evidence if e.doc_id == doc.doc_id), None) if current else None
            initial = numbers.index(evidence.clause) if evidence and evidence.clause in numbers else 0
            with col:
                number = st.selectbox(label, numbers, index=initial,
                    format_func=lambda n, d=doc: f'{n} · {d.get(n).text[:75]}',
                    key=f'clause_{report.meta["run_id"]}_{doc.doc_id}_{current.id if current else "all"}')
                choices.append(doc.get(number))
        lh, rh = word_diff(choices[0].text, choices[1].text)
        for col, clause, content, doc, label in zip(st.columns(2), choices, [lh, rh], [bdoc, adoc], ['ДО', 'ПОСЛЕ']):
            with col:
                source_panel(label + ' · ' + doc.file, clause, content, doc)
    else:
        st.warning('Источники этого запуска недоступны. Выполните анализ повторно.')

with export:
    st.subheader('Заключение для эксперта')
    st.write('Отчёт включает изменения, дословные цитаты, рекомендации и ограничения анализа.')
    a, b = st.columns(2)
    md = to_markdown(report)
    a.download_button('Скачать Markdown', md, 'orgtrace_report.md', mime='text/markdown', width='stretch', icon=':material/download:')
    b.download_button('Скачать JSON', report.model_dump_json(indent=2), 'orgtrace_report.json', mime='application/json', width='stretch', icon=':material/data_object:')
    with st.expander('Предпросмотр отчёта'):
        st.markdown(md)

with trace:
    st.subheader('Как получен результат')
    st.caption('Журнал исходного анализа сохраняется вместе с результатом. Повторный запуск может восстановить его из кэша.')
    # A DOM table follows the live CSS theme, unlike the dataframe's canvas.
    st.table([{'Этап': r['tool'], 'Результат': r['summary'], 'Время, мс': r['ms']} for r in report.agent_trace])
    with st.expander('Идентификаторы и воспроизводимость'):
        st.code(report.meta['run_id'], language=None)
        st.json(report.meta.get('analysis_settings', {}))

with chat_tab:
    st.subheader('Уточните вывод по документам')
    st.caption('Например: «Какие функции ДККМ исчезли?» Ответы сопровождаются проверяемыми дословными цитатами.')
    if not config.USE_LLM:
        st.info('Для вопросов агенту настройте OPENAI_API_KEY и USE_LLM=1. Все результаты и сравнение доступны без ключа.')
    elif not run:
        st.warning('Для вопросов нужны исходные пункты. Выполните анализ повторно.')
    else:
        messages = st.session_state.setdefault('chat_messages', [])
        for msg in messages:
            with st.chat_message(msg['role']):
                st.markdown(msg['content'])
        with st.form('question_form', clear_on_submit=True):
            question = st.text_input('Ваш вопрос', max_chars=4000, placeholder='Что изменилось в обязанностях подразделения?')
            submitted = st.form_submit_button('Спросить агента', icon=':material/send:')
            st.caption('Вопрос и найденные фрагменты отправляются в OpenAI только после нажатия кнопки.')
        if submitted and question.strip():
            with st.spinner('Ищем пункты и проверяем цитаты…'):
                result = llm.chat(question.strip(), chat_tools(report.meta['run_id']), history=messages[-8:])
            if not result or result.get('error'):
                st.error(result['answer'] if result else 'AI-сервис недоступен.')
            else:
                messages.extend([{'role': 'user', 'content': question.strip()}, {'role': 'assistant', 'content': result['answer']}])
                st.rerun()

st.html('<div class="footer">OrgTrace / Цитата подтверждает источник. Решение по организационным изменениям принимает эксперт.</div>')
