import json
from types import SimpleNamespace

import pytest

from app import config, pipeline
from app.agent import llm
from app.agent.schemas import FunctionReview
from app.runtime import analysis_mode, llm_enabled, similarity_backend
from tests.conftest import BEFORE, AFTER


def fake_client(monkeypatch, content, finish_reason='stop'):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason,
            message=SimpleNamespace(content=json.dumps(content), refusal=None, tool_calls=None))])
    monkeypatch.setattr(llm, '_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return calls


def test_strict_schema_temperature_and_id_validation(monkeypatch):
    calls = fake_client(monkeypatch, {'items': [{'finding_id': 'L1', 'verdict': 'lost', 'rationale': 'Нет аналога', 'lost_fragment': 'Контроль качества'}]})
    result = llm.review_gray([{'finding_id': 'L1', 'before': 'Контроль качества', 'after': '', 'before_owner': 'A', 'after_owner': ''}])
    assert result['L1']['verdict'] == 'lost'
    assert calls[0]['temperature'] == 0
    assert calls[0]['response_format']['json_schema']['strict'] is True
    assert calls[0]['response_format']['json_schema']['schema']['additionalProperties'] is False


@pytest.mark.parametrize('data', [
    {'items': [{'finding_id': 'L1', 'verdict': 'invented', 'rationale': '', 'lost_fragment': ''}]},
    {'items': [{'finding_id': 'UNKNOWN', 'verdict': 'lost', 'rationale': '', 'lost_fragment': ''}]},
    {'items': [{'finding_id': 'L1', 'verdict': 'lost', 'rationale': '', 'lost_fragment': 'выдумка'}]},
    {'items': []}, {'unexpected': 'field'},
])
def test_invalid_model_result_falls_back(monkeypatch, data):
    fake_client(monkeypatch, data)
    assert llm.review_gray([{'finding_id': 'L1', 'before': 'Контроль качества', 'after': ''}]) is None


def test_model_timeout_keeps_deterministic_findings(monkeypatch):
    monkeypatch.setattr(config, 'USE_LLM', True)
    def fail(**kwargs):
        raise TimeoutError('network unavailable')
    monkeypatch.setattr(llm, '_client', lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail))))
    result = pipeline.analyze(BEFORE, AFTER, mode='llm')
    assert result.summary['functions']['lost'] == 3
    assert any('LLM' in w for w in result.meta['warnings'])


def test_llm_result_is_cached_without_new_model_calls(monkeypatch):
    monkeypatch.setattr(config, 'USE_LLM', True)
    calls = []
    def review(items):
        calls.append(1)
        return {i['finding_id']: {'verdict': 'partially_lost', 'rationale': 'Содержание частично сохранено', 'lost_fragment': ''} for i in items}
    monkeypatch.setattr(llm, 'review_gray', review)
    monkeypatch.setattr(llm, 'review_dups', lambda items: {})
    first = pipeline.analyze(BEFORE, AFTER, mode='llm')
    second = pipeline.analyze(BEFORE, AFTER, mode='llm')
    assert len(calls) == 1
    assert first.summary == second.summary
    assert first.function_findings == second.function_findings


def test_modes_do_not_mutate_global_config(monkeypatch):
    monkeypatch.setattr(config, 'USE_LLM', True)
    monkeypatch.setattr(config, 'SIMILARITY_BACKEND', 'openai')
    with analysis_mode('deterministic'):
        assert not llm_enabled()
        assert similarity_backend() == 'tfidf'
        assert config.USE_LLM
    assert llm_enabled()
    assert similarity_backend() == 'openai'


def test_chat_citations_are_verified(monkeypatch, state, report):
    pipeline.RUNS['test-chat'] = {'state': state, 'report': report}
    clause = state['docs']['D8'].get('5.6.2')
    payload = {'claims': [{'text': 'В документе предусмотрены группы контроля качества.',
                'citations': [{'doc_id': 'D8', 'clause': clause.number, 'page': clause.page, 'quote': clause.text[:100]}]}],
               'insufficient_data': False}
    fake_client(monkeypatch, payload)
    assert llm.chat('Вопрос', pipeline.chat_tools('test-chat'))['citations']
    payload['claims'][0]['citations'][0]['quote'] += ' выдумка'
    fake_client(monkeypatch, payload)
    assert llm.chat('Вопрос', pipeline.chat_tools('test-chat'))['error']
