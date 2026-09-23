from app.agent.verifier import repair, verify
from app.models import Evidence, Finding


def test_fake_quote_is_rejected_and_repaired(state):
    docs = state["docs"]
    f = Finding(id="T1", category="function", type="lost", title="тест",
                evidence=[Evidence(doc_id="D8", clause="5.6.2", page=3,
                                   quote="полностью выдуманная цитата про бюджетирование ИТ")])
    ok, bad = verify([f], docs)
    assert not ok and bad and "страница" in bad[0].verify_note
    repair(bad, docs)
    ok, bad = verify(bad, docs)
    assert ok and ok[0].evidence[0].page == 10


def test_nonexistent_clause_stays_unverified(state):
    f = Finding(id="T2", category="function", type="lost", title="тест",
                evidence=[Evidence(doc_id="D9", clause="99.9", page=1, quote="нет")])
    repair([f], state["docs"])
    ok, bad = verify([f], state["docs"])
    assert bad and not ok
