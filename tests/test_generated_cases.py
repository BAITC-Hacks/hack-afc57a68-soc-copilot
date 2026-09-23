from app.generate_cases import generate
from app.parser.loader import load_any
from app.agent.graph import run_agent
from app.report import build_report


def test_generator_reproducibility_formats_and_ground_truth(tmp_path):
    first = generate(tmp_path / 'first', seed=123, clauses_per_section=2)
    second = generate(tmp_path / 'second', seed=123, clauses_per_section=2)
    assert first == second
    assert len(first['scenarios']) >= 9
    for ext in ('pdf', 'docx'):
        before, _ = load_any(str(tmp_path / 'first' / f'version_a.{ext}'), 'A')
        after, _ = load_any(str(tmp_path / 'first' / f'version_b.{ext}'), 'B')
        assert before.get('5.1.5') and not after.get('5.1.5')
        assert after.get('5.1.1').text == after.get('5.3.1').text
        assert after.get('21.1')
    state = run_agent(str(tmp_path / 'first/version_a.pdf'), str(tmp_path / 'first/version_b.pdf'))
    report = build_report(state)
    assert report.summary['units']['created'] == 2
    assert any(f.type == 'lost' and f.evidence[0].clause == '5.1.5' for f in report.function_findings)
    assert report.duplications
    assert any(f.type == 'dangling_reference' for f in report.document_defects)
    assert not report.unverified_findings


def test_cli_handles_windows_non_unicode_stdout(tmp_path):
    import os
    import subprocess
    import sys
    from tests.conftest import BEFORE, AFTER
    result = subprocess.run([sys.executable, '-m', 'app.cli', BEFORE, AFTER, '--out', str(tmp_path / 'nested/report')],
        env={**os.environ, 'PYTHONIOENCODING': 'cp1251', 'CACHE_DIR': str(tmp_path / 'cache-cli')},
        capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    assert 'Сохранено' in result.stdout.decode('utf-8')
    assert (tmp_path / 'nested/report.json').exists()
