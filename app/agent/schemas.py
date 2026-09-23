"""Versioned contracts for model output, validated again locally."""
from typing import Literal
from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class FunctionVerdict(StrictModel):
    finding_id: str
    verdict: Literal['lost', 'partially_lost', 'moved', 'reworded']
    rationale: str
    lost_fragment: str


class FunctionReview(StrictModel):
    items: list[FunctionVerdict]


class DuplicationVerdict(StrictModel):
    finding_id: str
    is_duplication: bool
    rationale: str


class DuplicationReview(StrictModel):
    items: list[DuplicationVerdict]


class SummaryOutput(StrictModel):
    summary: str


class ChatCitation(StrictModel):
    doc_id: str
    clause: str
    page: int
    quote: str


class ChatClaim(StrictModel):
    text: str
    citations: list[ChatCitation]


class ChatAnswer(StrictModel):
    claims: list[ChatClaim]
    insufficient_data: bool
