"""Research domain models.

Citations are referenced by stable UUID everywhere (never by list index), so
the synthesizer can dedupe sources across sub-queries without invalidating
references.
"""

from __future__ import annotations

from enum import IntEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Priority(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class SubQuery(BaseModel):
    model_config = ConfigDict(frozen=False)

    id: UUID = Field(default_factory=uuid4)
    question: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    priority: Priority


class ResearchPlan(BaseModel):
    original_question: str = Field(min_length=1)
    sub_queries: list[SubQuery] = Field(min_length=3, max_length=7)


class Source(BaseModel):
    """A citable web source. `id` is stable across dedup operations."""

    id: UUID = Field(default_factory=uuid4)
    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)


class KeyFact(BaseModel):
    """A discrete fact extracted by a researcher, keyed to its sources."""

    statement: str = Field(min_length=1)
    citation_ids: list[UUID] = Field(default_factory=list)


class SubQueryFinding(BaseModel):
    """Output of a single researcher agent for one sub-query.

    A degraded finding (research failure) has an explanatory summary and
    empty key_facts / sources; the synthesizer handles this gracefully.
    """

    sub_query_id: UUID
    summary: str = Field(min_length=1)
    key_facts: list[KeyFact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class ReportSection(BaseModel):
    heading: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    citation_ids: list[UUID] = Field(default_factory=list)


class FinalReport(BaseModel):
    report_id: UUID
    original_question: str
    executive_summary: str = Field(min_length=1)
    sections: list[ReportSection] = Field(min_length=1)
    citations: list[Source] = Field(default_factory=list)
