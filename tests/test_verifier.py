from app.agent.verifier import repair, verify
from app.models import Evidence, Finding


def test_fake_quote_remains_rejected_after_repair(state):
    docs = state["docs"]
    f = Finding(id="T1", category="function", type="lost", title="тест",
                evidence=[Evidence(doc_id="D8", clause="5.6.2", page=3,
                                   quote="полностью выдуманная цитата про бюджетирование ИТ")])
    ok, bad = verify([f], docs)
    assert not ok and bad and "цитата" in bad[0].verify_note
    repair(bad, docs)
    ok, bad = verify(bad, docs)
    assert not ok and bad
    assert bad[0].evidence[0].quote == 'полностью выдуманная цитата про бюджетирование ИТ'


def test_real_quote_with_wrong_page_is_repaired(state):
    c = state['docs']['D8'].get('5.6.2')
    f = Finding(id='T', category='function', type='lost', title='test',
                evidence=[Evidence(doc_id='D8', clause=c.number, page=1, quote=c.text[:80])])
    assert verify([f], state['docs'])[1]
    assert verify(repair([f], state['docs']), state['docs'])[0]
    assert f.evidence[0].page == 10


def test_exact_matching_rejects_negation_tail_and_empty():
    from app.models import Clause, Document
    from app.agent.verifier import quote_page
    c = Clause(clause_id='D:1', doc_id='D', edition='', number='1', page=1,
               text='Отдел обязан согласовать годовой план аудита.')
    for quote in ['', 'Отдел не обязан согласовать годовой план аудита.', c.text + ' Придуманный хвост.']:
        assert quote_page(c, quote) is None
    assert quote_page(c, 'Отдел  обязан\nсогласовать годовой план аудита.') == 1


def test_quote_from_continuation_uses_actual_page():
    from app.parser.clauses import split_into_clauses
    from app.agent.verifier import quote_page
    clauses, _ = split_into_clauses([(1, '1. Раздел\n1.1. Начало пункта'), (2, 'продолжение на новой странице')], 'D', '')
    assert quote_page(clauses[-1], 'продолжение на новой странице') == 2


def test_nonexistent_clause_stays_unverified(state):
    f = Finding(id="T2", category="function", type="lost", title="тест",
                evidence=[Evidence(doc_id="D9", clause="99.9", page=1, quote="нет")])
    repair([f], state["docs"])
    ok, bad = verify([f], state["docs"])
    assert bad and not ok
