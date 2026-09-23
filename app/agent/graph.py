"""Agent-Orchestrator на LangGraph.

parse → plan → structure → struct_compare → loss → duplication → conflict → crossref
      → [llm_review, если есть ключ] → verify ⇄ repair (до MAX_VERIFY_RETRIES) → report
"""
from __future__ import annotations

import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from app import config
from app.agent import llm
from app.agent.detectors import Toolkit
from app.agent.structure import assign_owners, extract_units
from app.agent.verifier import repair, verify
from app.models import Document, Finding
from app.parser.loader import load_any


class AgentState(TypedDict, total=False):
    before_path: str
    after_path: str
    docs: dict[str, Document]
    before_id: str
    after_id: str
    plan: list[str]
    toolkit: Any
    findings: list[Finding]
    gray: list[dict]
    dup_cands: list[dict]
    unverified: list[Finding]
    retries: int
    trace: list[dict]
    anomalies: list[dict]
    executive_summary: str
    on_step: Callable[[dict], None] | None


def _log(state: AgentState, step: str, tool: str, summary: str, t0: float) -> list[dict]:
    rec = {"step": step, "tool": tool, "summary": summary, "ms": int((time.time() - t0) * 1000)}
    if state.get("on_step"):
        state["on_step"](rec)
    return state.get("trace", []) + [rec]


def _rename(doc: Document, new_id: str) -> Document:
    doc.doc_id = new_id
    for c in doc.clauses:
        c.doc_id = new_id
        c.clause_id = f"{new_id}:{c.number}"
    return doc


# ------------------------------------------------------------------ nodes
def node_parse(state: AgentState) -> dict:
    t0 = time.time()
    b, an_b = load_any(state["before_path"], "BEFORE")
    a, an_a = load_any(state["after_path"], "AFTER")
    bid = f"D{b.edition}" if b.edition else "D_BEFORE"
    aid = f"D{a.edition}" if a.edition and a.edition != b.edition else "D_AFTER"
    _rename(b, bid), _rename(a, aid)
    return {"docs": {bid: b, aid: a}, "before_id": bid, "after_id": aid,
            "anomalies": an_b + an_a,
            "trace": _log(state, "parse", "Parser",
                          f"{b.file}: {len(b.clauses)} пунктов (ред. {b.edition or '?'}); "
                          f"{a.file}: {len(a.clauses)} пунктов (ред. {a.edition or '?'})", t0)}


def node_plan(state: AgentState) -> dict:
    """Планировщик: решает, какие инструменты применимы к загруженным документам."""
    t0 = time.time()
    b, a = state["docs"][state["before_id"]], state["docs"][state["after_id"]]
    plan = []
    has_struct = all(any("структурных подразделений" in c.text for c in d.clauses) for d in (b, a))
    has_funcs = all(d.get("5") is not None for d in (b, a))
    if has_struct:
        plan.append("struct_compare")
    if has_funcs:
        plan += ["loss", "duplication"]
    plan += ["conflict", "crossref"]
    if config.USE_LLM:
        plan.append("llm_review")
    return {"plan": plan, "trace": _log(state, "plan", "Planner", " → ".join(plan), t0)}


def node_structure(state: AgentState) -> dict:
    t0 = time.time()
    b, a = state["docs"][state["before_id"]], state["docs"][state["after_id"]]
    ub, ua = extract_units(b), extract_units(a)
    assign_owners(b, ub), assign_owners(a, ua)
    tk = Toolkit(b, a, ub, ua)
    return {"toolkit": tk, "findings": [],
            "trace": _log(state, "structure", "extract_units + assign_owners",
                          f"до: {', '.join(ub)}; после: {', '.join(ua)}", t0)}


def _tool_node(name: str, label: str, fn: Callable[[Toolkit], Any]):
    def node(state: AgentState) -> dict:
        t0 = time.time()
        if name not in state.get("plan", []) and name not in ("conflict", "crossref"):
            return {"trace": _log(state, name, label, "пропущено планировщиком", t0)}
        res = fn(state["toolkit"])
        extra = {}
        if isinstance(res, tuple):
            res, side = res
            extra = {"gray" if name == "loss" else "dup_cands": side}
        found = state.get("findings", []) + res
        return {"findings": found, **extra,
                "trace": _log(state, name, label, f"найдено: {len(res)}", t0)}
    return node


def node_llm_review(state: AgentState) -> dict:
    t0 = time.time()
    findings = state["findings"]
    by_id = {f.id: f for f in findings}
    notes = []
    verdicts = llm.review_gray(state.get("gray", []))
    if verdicts:
        for fid, v in verdicts.items():
            f = by_id.get(fid)
            if not f:
                continue
            if v.get("verdict") == "reworded":
                f.type, f.severity = "reworded", "info"
            elif v.get("verdict") in ("lost", "partially_lost", "moved"):
                f.type = v["verdict"]
            f.rationale += f" LLM: {v.get('rationale', '')}"
            f.method = "similarity+llm"
        notes.append(f"пограничных случаев: {len(verdicts)}")
    dv = llm.review_dups(state.get("dup_cands", []))
    if dv:
        for fid, v in dv.items():
            f = by_id.get(fid)
            if f and v.get("is_duplication") is False:
                f.type, f.severity = "not_duplication", "info"
            if f:
                f.rationale += f" LLM: {v.get('rationale', '')}"
                f.method = "similarity+llm"
        notes.append(f"кандидатов в дублирование: {len(dv)}")
    kept = [f for f in findings if f.type not in ("reworded", "not_duplication")]
    return {"findings": kept,
            "trace": _log(state, "llm_review", config.LLM_MODEL,
                          "; ".join(notes) or "LLM недоступен — оставлены детерминированные выводы", t0)}


def node_verify(state: AgentState) -> dict:
    t0 = time.time()
    ok, bad = verify(state["findings"] + state.get("unverified", []), state["docs"])
    return {"findings": ok, "unverified": bad,
            "trace": _log(state, "verify", "CitationVerifier",
                          f"подтверждено: {len(ok)}, не подтверждено: {len(bad)}", t0)}


def node_repair(state: AgentState) -> dict:
    t0 = time.time()
    fixed = repair(state.get("unverified", []), state["docs"])
    return {"unverified": fixed, "retries": state.get("retries", 0) + 1,
            "trace": _log(state, "repair", "CitationRepair",
                          f"попытка {state.get('retries', 0) + 1}: исправлено {len(fixed)}", t0)}


def route_after_verify(state: AgentState) -> str:
    if state.get("unverified") and state.get("retries", 0) < config.MAX_VERIFY_RETRIES:
        return "repair"
    return "report"


def node_report(state: AgentState) -> dict:
    t0 = time.time()
    brief = [{"id": f.id, "type": f.type, "title": f.title,
              "clauses": [f"{e.doc_id} п. {e.clause}" for e in f.evidence]}
             for f in state["findings"] if f.severity != "info"]
    summary = llm.executive_summary({"findings": brief}) if config.USE_LLM else None
    return {"executive_summary": summary or "",
            "trace": _log(state, "report", "ReportGenerator", "отчёт сформирован", t0)}


# ------------------------------------------------------------------ graph
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("parse", node_parse)
    g.add_node("plan", node_plan)
    g.add_node("structure", node_structure)
    g.add_node("struct_compare", _tool_node("struct_compare", "StructComparator",
                                            lambda tk: tk.struct_comparator()))
    g.add_node("loss", _tool_node("loss", "LossDetector", lambda tk: tk.loss_detector()))
    g.add_node("duplication", _tool_node("duplication", "DuplicationDetector",
                                         lambda tk: tk.duplication_detector()))
    g.add_node("conflict", _tool_node("conflict", "ConflictDetector", lambda tk: tk.conflict_detector()))
    g.add_node("crossref", _tool_node("crossref", "CrossRefChecker",
                                      lambda tk: tk.crossref_checker() + tk.defect_detector()))
    g.add_node("llm_review", node_llm_review)
    g.add_node("verify", node_verify)
    g.add_node("repair", node_repair)
    g.add_node("report", node_report)

    g.set_entry_point("parse")
    for a, b in [("parse", "plan"), ("plan", "structure"), ("structure", "struct_compare"),
                 ("struct_compare", "loss"), ("loss", "duplication"),
                 ("duplication", "conflict"), ("conflict", "crossref")]:
        g.add_edge(a, b)
    g.add_conditional_edges("crossref", lambda s: "llm_review" if "llm_review" in s.get("plan", []) else "verify",
                            {"llm_review": "llm_review", "verify": "verify"})
    g.add_edge("llm_review", "verify")
    g.add_conditional_edges("verify", route_after_verify, {"repair": "repair", "report": "report"})
    g.add_edge("repair", "verify")
    g.add_edge("report", END)
    return g.compile()


def run_agent(before_path: str, after_path: str, on_step=None) -> AgentState:
    graph = build_graph()
    return graph.invoke({"before_path": before_path, "after_path": after_path,
                         "retries": 0, "trace": [], "unverified": [], "on_step": on_step},
                        {"recursion_limit": 40})
