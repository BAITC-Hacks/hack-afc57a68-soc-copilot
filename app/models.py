"""Pydantic-модели: пункт документа, доказательство, вывод, отчёт."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class Clause(BaseModel):
    clause_id: str                 # "D8:5.6.2"
    doc_id: str                    # "D8"
    edition: str                   # "8"
    number: str                    # "5.6.2", "3.4.а", "14"
    text: str
    page: int
    section: str = ""              # "5. Права и обязанности"
    parent: Optional[str] = None   # номер родителя
    depth: int = 1
    owner_units: list[str] = Field(default_factory=list)
    is_leaf: bool = True


class Document(BaseModel):
    doc_id: str
    file: str
    title: str = ""
    edition: str = ""
    approved: str = ""
    kind: Literal["pdf", "docx", "xlsx"] = "pdf"
    clauses: list[Clause] = Field(default_factory=list)

    def get(self, number: str) -> Optional[Clause]:
        for c in self.clauses:
            if c.number == number:
                return c
        return None

    def subtree(self, number: str) -> list[Clause]:
        return [c for c in self.clauses if c.number == number or c.number.startswith(number + ".")]


class Evidence(BaseModel):
    doc_id: str
    clause: str
    page: int
    quote: str
    role: str = "source"           # source | target | closest | support


class Finding(BaseModel):
    id: str
    category: Literal["structure", "function", "duplication", "conflict", "defect"]
    type: str                      # created|kept|reorganized|removed|lost|partially_lost|moved|...
    severity: Literal["high", "medium", "low", "info"] = "medium"
    title: str
    units_before: list[str] = Field(default_factory=list)
    units_after: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    similarity: Optional[float] = None
    rationale: str = ""
    recommendation: str = ""
    confidence: float = 0.7
    method: Literal["rule", "similarity", "llm", "similarity+llm"] = "rule"
    verified: bool = False
    verify_note: str = ""


class Report(BaseModel):
    meta: dict
    summary: dict
    structure_changes: list[Finding]
    function_findings: list[Finding]
    duplications: list[Finding]
    conflicts_of_interest: list[Finding]
    document_defects: list[Finding]
    unverified_findings: list[Finding]
    agent_trace: list[dict] = Field(default_factory=list)
    executive_summary: str = ""
