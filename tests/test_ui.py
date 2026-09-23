from pathlib import Path
from streamlit.testing.v1 import AppTest

from ui.components import word_diff


def test_diff_escapes_source_and_marks_changes():
    left, right = word_diff('Срок 10 дней <script>', 'Срок 5 дней <b>')
    assert 'diff-change' in left and 'diff-change' in right
    assert '<script>' not in left and '<b>' not in right
    assert '&lt;' in left


def test_demo_metrics_filters_and_sources():
    at = AppTest.from_file(Path('ui/app.py').resolve(), default_timeout=90).run()
    assert not at.exception
    assert at.session_state['step'] == 1
    next(b for b in at.button if b.label == 'Открыть демо').click().run()
    assert not at.exception
    assert at.session_state['step'] == 3
    assert len(at.tabs) == 5
    at.button(key='metric_Потери').click().run()
    assert not at.exception
    assert at.selectbox(key='active_filter').value == 'Потери'
    assert all(b.key.startswith('finding_L') for b in at.button if b.key and b.key.startswith('finding_'))
    next(t for t in at.text_input if t.label == 'Поиск по выводам и цитатам').set_value('ничего_не_найдено_123').run()
    assert not at.exception
    assert any('изменений нет' in i.value for i in at.info)


def test_wizard_mode_step_and_run():
    at = AppTest.from_file(Path('ui/app.py').resolve(), default_timeout=90)
    at.session_state['step'] = 2
    at.session_state['sources'] = [
        {'name': 'same.pdf', 'data': Path('data/samples/polozhenie_red08_protocol13.pdf').read_bytes()},
        {'name': 'same.pdf', 'data': Path('data/samples/polozhenie_red09_protocol7.pdf').read_bytes()},
    ]
    at.run()
    assert not at.exception
    assert at.radio[0].value == 'deterministic'
    next(b for b in at.button if b.label == 'Назад к документам').click().run()
    assert at.session_state['step'] == 1
    assert not next(b for b in at.button if b.label == 'Продолжить').disabled
    next(b for b in at.button if b.label == 'Продолжить').click().run()
    assert at.session_state['step'] == 2
    next(b for b in at.button if b.label == 'Сравнить документы').click().run()
    assert not at.exception
    assert [d['edition'] for d in at.session_state['report'].meta['documents']] == ['8', '9']
