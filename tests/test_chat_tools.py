"""Regression coverage for document aliases and empty chat searches."""
import pytest

from app.pipeline import RUNS, chat_tools


@pytest.fixture
def tools(state, report, monkeypatch):
    monkeypatch.setitem(RUNS, "chat-test", {"state": state, "report": report})
    return chat_tools("chat-test")


@pytest.mark.parametrize("alias, state_key", [
    ("D_BEFORE", "before_id"), ("D_AFTER", "after_id"),
])
def test_document_alias_search_and_lookup(tools, state, alias, state_key):
    actual_id = state[state_key]
    clause = state["docs"][actual_id].clauses[0]
    results = tools["search_clauses"](clause.text, doc_id=alias)
    assert results
    assert all(item["doc_id"] == actual_id for item in results)
    assert results == tools["search_clauses"](clause.text, doc_id=actual_id)
    assert tools["get_clause"](alias, clause.number) == clause.model_dump()


def test_unknown_document_gives_recoverable_error(tools, state):
    result = tools["search_clauses"]("audit", doc_id="missing-document")
    assert result["error"]
    assert set(result["available_doc_ids"]) == set(state["docs"])


def test_search_without_filter_searches_both_documents(tools, state):
    results = tools["search_clauses"]("audit", top_k=10000)
    assert {item["doc_id"] for item in results} == set(state["docs"])


def test_document_without_clauses_returns_empty_results(state, report, monkeypatch):
    empty_docs = {key: doc.model_copy(update={"clauses": []})
                  for key, doc in state["docs"].items()}
    monkeypatch.setitem(RUNS, "empty-test", {
        "state": {**state, "docs": empty_docs}, "report": report,
    })
    search = chat_tools("empty-test")["search_clauses"]
    assert search("audit") == []
    assert search("audit", doc_id="D_BEFORE") == []
