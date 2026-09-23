"""Золотой набор: изменения ред. 8 → ред. 9, которые агент обязан найти (раздел 11 кейса)."""


def _ids(findings, **kw):
    return [f for f in findings if all(getattr(f, k) == v for k, v in kw.items())]


def test_reorganization(report):
    reorg = _ids(report.structure_changes, type="reorganized")
    assert reorg and set(reorg[0].units_after) == {"ДИТААД", "ДОА"}
    created = {u for f in _ids(report.structure_changes, type="created") for u in f.units_after}
    kept = {u for f in _ids(report.structure_changes, type="kept") for u in f.units_after}
    assert created == {"ДИТААД", "ДОА"} and kept == {"ДНМ", "ДККМ"}


def test_lost_functions(report):
    lost = {f.evidence[0].clause for f in report.function_findings if f.type == "lost"}
    assert {"5.6.2", "5.6.3", "5.7.2"} <= lost


def test_partial_losses(report):
    partial = {f.evidence[0].clause for f in report.function_findings if f.type == "partially_lost"}
    assert {"5.3.4.б", "5.5.5", "5.7.1"} <= partial


def test_moved_not_lost(report):
    moved = {f.evidence[0].clause for f in report.function_findings if f.type == "moved"}
    assert {"5.4.4.а", "5.4.4.б"} <= moved


def test_duplication(report):
    pairs = {frozenset(e.clause for e in f.evidence) for f in report.duplications}
    assert frozenset({"5.3.8", "5.4.5"}) in pairs
    assert frozenset({"5.3.7", "5.5.5"}) in pairs


def test_conflicts(report):
    types = {f.type for f in report.conflicts_of_interest}
    assert {"cross_subordination", "self_review", "governance_role"} <= types


def test_broken_cross_reference(report):
    x = [f for f in report.document_defects if f.type == "broken_cross_reference"]
    assert any(f.evidence[0].clause == "5.10.2" for f in x)


def test_everything_verified(report):
    assert report.unverified_findings == []
    all_f = (report.structure_changes + report.function_findings + report.duplications
             + report.conflicts_of_interest + report.document_defects)
    assert all(f.verified and f.evidence for f in all_f)
