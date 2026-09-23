from app.models import Evidence, Finding
from ui.filters import filter_findings, toggle_selection


def sample_findings():
    return [
        Finding(id='S1', category='structure', type='created', title='Создан ДККМ', severity='info'),
        Finding(id='K1', category='conflict', type='self_review', title='Самопроверка', severity='high'),
        Finding(id='M1', category='function', type='moved', title='Перенос', evidence=[
            Evidence(doc_id='D9', clause='5.3.3', page=8, quote='Аудит данных')]),
        Finding(id='R1', category='function', type='removed_duplicate', title='Устранено дублирование'),
    ]


def test_empty_selection_shows_all_and_preserves_order():
    findings = sample_findings()
    assert filter_findings(findings, []) == findings


def test_categories_are_a_union_without_duplicates():
    result = filter_findings(sample_findings(), ['Создано', 'Структура', 'Конфликты'])
    assert [f.id for f in result] == ['S1', 'K1']


def test_transfers_exclude_removed_duplicates():
    assert [f.id for f in filter_findings(sample_findings(), ['Переносы'])] == ['M1']
    assert [f.id for f in filter_findings(sample_findings(), ['Устранено дублирование'])] == ['R1']


def test_severity_and_query_intersect_category_union():
    assert [f.id for f in filter_findings(sample_findings(), ['Создано', 'Конфликты'], 'high')] == ['K1']
    assert [f.id for f in filter_findings(sample_findings(), [], query='  АУДИТ  ')] == ['M1']
    assert [f.id for f in filter_findings(sample_findings(), [], query='5.3.3')] == ['M1']


def test_toggle_is_immutable_and_deduplicates():
    original = ['Создано']
    assert toggle_selection(original, 'Конфликты') == ['Создано', 'Конфликты']
    assert toggle_selection(original, 'Создано') == []
    assert original == ['Создано']
    assert toggle_selection(['Создано', 'Создано'], 'Потери') == ['Создано', 'Потери']
