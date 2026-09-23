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
    assert any('brand-logo' in e.proto.body and 'alt="OrgTrace"' in e.proto.body
               for e in at.sidebar.get('html'))
    next(b for b in at.button if b.label == 'Открыть демо').click().run()
    assert not at.exception
    assert at.session_state['step'] == 3
    assert len(at.tabs) == 5
    original_picker_key = at.multiselect[0].key
    at.button(key='metric_Потери').click().run()
    assert not at.exception
    assert at.multiselect[0].value == ['Потери']
    assert at.multiselect[0].key != original_picker_key
    assert at.session_state['active_filters'] == ['Потери']
    assert at.button(key='metric_Потери').proto.type == 'primary'
    assert all(b.key.startswith('finding_L') for b in at.button if b.key and b.key.startswith('finding_'))
    # Multiple cards activate in ONE run, including a card earlier in the grid.
    at.button(key='metric_Создано').click().run()
    at.button(key='metric_Конфликты').click().run()
    assert set(at.multiselect[0].value) == {'Потери', 'Создано', 'Конфликты'}
    for name in ('Создано', 'Потери', 'Конфликты'):
        assert at.button(key='metric_' + name).proto.type == 'primary'
    assert len([b for b in at.button if b.key and b.key.startswith('finding_')]) == 8
    # Deselect every card: the empty selection restores all findings.
    for name in ('Создано', 'Потери', 'Конфликты'):
        at.button(key='metric_' + name).click().run()
        assert at.button(key='metric_' + name).proto.type == 'secondary'
    assert at.multiselect[0].value == []
    assert len([b for b in at.button if b.key and b.key.startswith('finding_')]) == 24
    # Picker and cards share state. Removed duplicates have their own category.
    at.multiselect[0].set_value(['Переносы']).run()
    assert at.session_state['active_filters'] == ['Переносы']
    assert at.button(key='metric_Переносы').proto.type == 'primary'
    assert len([b for b in at.button if b.key and b.key.startswith('finding_')]) == 2
    at.button(key='finding_M2').click().run()
    assert at.session_state['selected_finding'] == 'M2'
    assert at.button(key='finding_M2').proto.type == 'primary'
    assert at.button(key='finding_M1').proto.type == 'secondary'
    next(t for t in at.text_input if t.label == 'Поиск по выводам и цитатам').set_value('ничего_не_найдено_123').run()
    assert not at.exception
    assert any('изменений нет' in i.value for i in at.info)
    at.button(key='reset_filters').click().run()
    assert not at.exception
    assert at.text_input(key='finding_query').value == ''
    assert at.multiselect[0].value == []
    assert len([b for b in at.button if b.key and b.key.startswith('finding_')]) == 24


def test_new_comparison_resets_filters():
    at = AppTest.from_file(Path('ui/app.py').resolve(), default_timeout=90).run()
    next(b for b in at.button if b.label == 'Открыть демо').click().run()
    at.button(key='metric_Дефекты').click().run()
    next(b for b in at.button if b.label == 'Новое сравнение').click().run()
    assert not at.exception
    assert at.session_state['step'] == 1
    assert not any('data-org-theme-choice' in e.proto.body for e in at.sidebar.get('html'))
    theme = next(e for e in at.get('html') if 'orgTraceThemeController' in e.proto.body)
    assert theme.proto.unsafe_allow_javascript
    assert '<div class="theme-control"' in theme.proto.body
    assert at.session_state['active_filters'] == []
    assert 'report' not in at.session_state


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
