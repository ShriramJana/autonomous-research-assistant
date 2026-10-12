"""Research domain models.

Citations are referenced by stable UUID everywhere (never by list index), so
the synthesizer can dedupe sources across sub-queries without invalidating
references.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

SourceKind = Literal["web", "scholarly"]
MAX_SEARCH_TERMS = 4
MAX_SOURCE_TITLE_CHARS = 500


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
    # Short keyword phrases for scholarly catalogs (planner-supplied; may be empty).
    search_terms: list[str] = Field(default_factory=list, max_length=MAX_SEARCH_TERMS)


class ResearchPlan(BaseModel):
    original_question: str = Field(min_length=1)
    sub_queries: list[SubQuery] = Field(min_length=3, max_length=7)
    web_search_enabled: bool = True
    scholarly_enabled: bool = False


class Source(BaseModel):
    """A citable source. `id` is stable across dedup operations.

    `kind="scholarly"` sources carry catalog metadata filled by the backend
    from its own fetched-paper registry — never by the model.
    """

    id: UUID = Field(default_factory=uuid4)
    url: HttpUrl
    title: str = Field(min_length=1, max_length=MAX_SOURCE_TITLE_CHARS)
    kind: SourceKind = "web"
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    citation_count: int | None = None


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
    web_search_enabled: bool = True
    scholarly_enabled: bool = False


ReportEnvelope = FinalReport
