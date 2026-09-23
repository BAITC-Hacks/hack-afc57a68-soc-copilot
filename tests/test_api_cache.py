from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, pipeline
from app.main import app
from app.parser.loader import load_any
from app.uploads import DocumentInputError, save_upload
from tests.conftest import BEFORE, AFTER


def test_same_filenames_preserve_both_editions():
    response = TestClient(app).post('/api/analyze', files={
        'before': ('document.pdf', Path(BEFORE).read_bytes(), 'application/pdf'),
        'after': ('document.pdf', Path(AFTER).read_bytes(), 'application/pdf')})
    assert response.status_code == 200
    data = response.json()
    assert [d['edition'] for d in data['meta']['documents']] == ['8', '9']
    assert data['summary']['functions']['lost'] == 3


def test_results_survive_restart_and_identical_inputs_skip_graph(monkeypatch):
    first = pipeline.analyze(BEFORE, AFTER)
    pipeline.RUNS.clear()
    def unexpected(*args, **kwargs):
        pytest.fail('A cached analysis must not run the graph or call a model')
    monkeypatch.setattr(pipeline, 'run_agent', unexpected)
    again = pipeline.analyze(BEFORE, AFTER)
    assert again.meta['cache_hit']
    assert first.meta['run_id'] == again.meta['run_id']
    assert first.summary == again.summary
    assert pipeline.chat_tools(first.meta['run_id'])['get_clause']('D_BEFORE', '5.6.2')['page'] == 10
    assert TestClient(app).get(f'/api/report/{first.meta["run_id"]}.md').status_code == 200


def test_concurrent_same_inputs_run_once(monkeypatch):
    real, calls = pipeline.run_agent, []
    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(pipeline, 'run_agent', spy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: pipeline.analyze(BEFORE, AFTER), range(2)))
    assert len(calls) == 1
    assert reports[0].meta['run_id'] == reports[1].meta['run_id']


def test_cache_key_tracks_order_settings_and_content(tmp_path, monkeypatch):
    from app.storage import cache_identity
    from app.runtime import analysis_mode
    with analysis_mode('deterministic'):
        first, _ = cache_identity(BEFORE, AFTER, 'deterministic')
        reverse, _ = cache_identity(AFTER, BEFORE, 'deterministic')
    assert first != reverse
    monkeypatch.setattr(config, 'USE_LLM', True)
    with analysis_mode('llm'):
        other, _ = cache_identity(BEFORE, AFTER, 'llm')
    assert other != first
    changed = tmp_path / 'new.pdf'
    changed.write_bytes(Path(AFTER).read_bytes() + b'\n')
    with analysis_mode('deterministic'):
        edited, _ = cache_identity(BEFORE, str(changed), 'deterministic')
    assert edited != first


@pytest.mark.parametrize('filename,data', [('bad.pdf', b'broken'), ('empty.pdf', b''), ('bad.txt', b'text')])
def test_invalid_upload_is_actionable(filename, data):
    response = TestClient(app).post('/api/analyze', files={
        'before': (filename, data), 'after': ('after.pdf', Path(AFTER).read_bytes())})
    assert response.status_code == 400
    assert response.json()['detail']


def test_empty_workbook_is_rejected_before_tfidf(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / 'empty.xlsx'
    Workbook().save(path)
    with pytest.raises(DocumentInputError, match='не найдены'):
        load_any(str(path), 'D')


def test_upload_is_confined_and_size_limited(tmp_path, monkeypatch):
    import io
    from app import uploads
    path = save_upload(io.BytesIO(b'file'), '../../source.pdf', str(tmp_path), 'before')
    assert Path(path).resolve().is_relative_to(tmp_path.resolve())
    monkeypatch.setattr(uploads, 'MAX_UPLOAD_BYTES', 3)
    with pytest.raises(DocumentInputError, match='25'):
        save_upload(io.BytesIO(b'file'), 'large.pdf', str(tmp_path), 'after')


def test_structure_without_new_functions_does_not_crash(state):
    from app.agent.detectors import Toolkit
    from app.agent.structure import extract_units
    before = state['docs'][state['before_id']]
    after = state['docs'][state['after_id']].model_copy(deep=True)
    after.clauses = [c for c in after.clauses if not c.number.startswith('5.')]
    findings = Toolkit(before, after, extract_units(before), extract_units(after)).struct_comparator()
    assert any(f.type == 'removed' for f in findings)
