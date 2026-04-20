"""Synthesizer agent — streams a cited final report from all findings.

Streaming contract:
- Tokens go out live via `SynthesisToken` events (UX: report renders live).
- After the stream ends, the accumulated markdown is parsed into a
  `FinalReport` with structured sections + a master (deduped) citation list.
- Findings that failed (degraded: empty facts + sources) are still passed
  to the model with an explicit "coverage gap" note, so the report can
  acknowledge them instead of silently pretending.

Citation flow:
- Sources are deduped across findings by URL *before* the call so the
  model sees a clean numbered list (`1.`, `2.`, …).
- The model writes inline `[n]` markers referencing those numbers.
- After the stream, markers are scanned per section and translated back
  into stable `Source.id` UUIDs.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import ValidationError

from ara.agents import EventEmitter, SynthesizerError
from ara.llm.client import LLMClient
from ara.models.events import SynthesisToken
from ara.models.research import FinalReport, ReportSection, Source, SubQueryFinding

SYNTHESIZER_SYSTEM_PROMPT = """\
You are the Synthesizer stage of an autonomous research assistant.

You receive the original research question, a deduped list of citations, and \
the findings from multiple research agents. Produce a thorough, well-structured \
Markdown report.

FORMAT (strict — the parser depends on it):
- Begin with `# Executive Summary` followed by a 2-3 paragraph overview.
- Then `# <Section Heading>` for each major section (aim for 3-6 sections).
- Use ONLY level-1 headings (`# `) to delimit report sections. Use level-2 \
  or deeper (`## `, `### `) freely inside sections for subheadings.
- Cite inline with numeric markers like `[1]`, `[2]` — never bracketed URLs.
- Every factual claim should carry at least one citation.
- If a sub-query is marked as a coverage gap, acknowledge the gap in the \
  relevant section ("Evidence on X was incomplete; see Limitations.").
- Do NOT add a final `# References` or `# Citations` section — citations are \
  rendered separately by the UI.

Write for a technical but non-specialist reader. Be concise, accurate, and \
grounded strictly in the provided findings.
"""

_CITATION_RE = re.compile(r"\[(\d+)\]")
_HEADING_RE = re.compile(r"^# (.+?)$", re.MULTILINE)


async def synthesize_report(
    *,
    report_id: UUID,
    original_question: str,
    findings: list[SubQueryFinding],
    llm: LLMClient,
    model: str,
    emit: EventEmitter,
    max_tokens: int = 8192,
) -> FinalReport:
    """Stream the report and return the assembled `FinalReport`.

    Raises `SynthesizerError` if the stream yields nothing usable or the
    output can't be parsed into at least one level-1 section.
    """
    master_citations = _dedupe_sources(findings)
    user_prompt = _build_user_prompt(
        original_question=original_question,
        findings=findings,
        master_citations=master_citations,
    )

    buffer: list[str] = []
    async for token in llm.stream_completion(
        model=model,
        messages=[{"role": "user", "content": user_prompt}],
        system=SYNTHESIZER_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    ):
        buffer.append(token)
        await emit(SynthesisToken(token=token))

    full_text = "".join(buffer).strip()
    if not full_text:
        raise SynthesizerError("Synthesizer produced no text")

    try:
        return _build_report(
            report_id=report_id,
            original_question=original_question,
            text=full_text,
            master_citations=master_citations,
        )
    except (ValidationError, ValueError) as exc:
        raise SynthesizerError(f"Synthesizer output failed validation: {exc}") from exc


def _dedupe_sources(findings: list[SubQueryFinding]) -> list[Source]:
    """Return a first-seen-wins, URL-deduped list of sources across findings."""
    seen: dict[str, Source] = {}
    ordered: list[Source] = []
    for f in findings:
        for s in f.sources:
            url = str(s.url)
            if url not in seen:
                seen[url] = s
                ordered.append(s)
    return ordered


def _build_user_prompt(
    *,
    original_question: str,
    findings: list[SubQueryFinding],
    master_citations: list[Source],
) -> str:
    url_to_num = {str(s.url): i + 1 for i, s in enumerate(master_citations)}

    if master_citations:
        citations_block = "\n".join(
            f"{i + 1}. {s.title} — {s.url}" for i, s in enumerate(master_citations)
        )
    else:
        citations_block = "(no citations available — all sub-queries failed)"

    finding_chunks: list[str] = []
    for i, f in enumerate(findings, start=1):
        is_degraded = not f.key_facts and not f.sources
        header = f"## Sub-query {i}" + (" (COVERAGE GAP — research failed)" if is_degraded else "")
        body_lines = [header, f"Summary: {f.summary}"]
        if f.key_facts:
            body_lines.append("Key facts:")
            for kf in f.key_facts:
                nums = sorted(
                    {url_to_num[str(s.url)] for s in f.sources if s.id in kf.citation_ids}
                )
                cite_str = " " + " ".join(f"[{n}]" for n in nums) if nums else ""
                body_lines.append(f"- {kf.statement}{cite_str}")
        finding_chunks.append("\n".join(body_lines))

    return (
        f"Original question: {original_question}\n\n"
        f"AVAILABLE CITATIONS:\n{citations_block}\n\n"
        f"FINDINGS:\n" + "\n\n".join(finding_chunks) + "\n\n"
        "Write the report now, following the format rules exactly."
    )


def _build_report(
    *,
    report_id: UUID,
    original_question: str,
    text: str,
    master_citations: list[Source],
) -> FinalReport:
    blocks = _split_level1_sections(text)
    if not blocks:
        raise SynthesizerError("Synthesizer output has no level-1 headings")

    exec_heading, exec_content = blocks[0]
    is_exec_block = "executive summary" in exec_heading.lower()

    if is_exec_block:
        executive_summary = exec_content or exec_heading
        section_blocks = blocks[1:]
    else:
        executive_summary = exec_content or exec_heading
        section_blocks = blocks

    sections = [
        ReportSection(
            heading=h,
            content=c or h,
            citation_ids=_extract_citation_ids(c, master_citations),
        )
        for h, c in section_blocks
    ]
    if not sections:
        sections = [
            ReportSection(
                heading=exec_heading,
                content=exec_content or exec_heading,
                citation_ids=_extract_citation_ids(exec_content, master_citations),
            )
        ]

    return FinalReport(
        report_id=report_id,
        original_question=original_question,
        executive_summary=executive_summary,
        sections=sections,
        citations=master_citations,
    )


def _split_level1_sections(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return []
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        blocks.append((heading, content))
    return blocks


def _extract_citation_ids(content: str, master_citations: list[Source]) -> list[UUID]:
    numbers_in_order: list[int] = []
    seen: set[int] = set()
    for m in _CITATION_RE.finditer(content):
        n = int(m.group(1))
        if 1 <= n <= len(master_citations) and n not in seen:
            seen.add(n)
            numbers_in_order.append(n)
    return [master_citations[n - 1].id for n in numbers_in_order]
