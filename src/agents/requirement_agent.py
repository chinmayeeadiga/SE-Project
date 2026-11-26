import json
import logging
from typing import Optional, Dict, Any, List
from src.config import settings
from src.rag.pipeline import RAGPipeline
from src.llm.provider import LLMProvider, get_llm_provider, FallbackProvider
from src.llm.fallback_engine import FallbackDomainEngine
from src.demo_fixture import is_demo_input, requirement_fixture
from src.models.schemas import (
    ExtractedRequirements,
    Requirement,
    RequirementCategory,
    RequirementPriority,
    RequirementOrigin,
    AmbiguityItem,
    ConflictItem,
    MissingInfoItem
)

logger = logging.getLogger(__name__)


class RequirementAnalysisAgent:
    """Requirement Analysis Agent for Digital Banking Systems.
    Extracts, categorizes, deduplicates, and validates stakeholder requirements
    while grounding them in actual banking regulations (RBI, CERT-In, DPDP, NIST, OWASP).
    """

    SYSTEM_PROMPT = """You are a Principal Banking Requirements Engineer and Compliance Auditor.
Analyze the stakeholder input and extract all requirements into structured JSON strictly adhering to the schema.
Requirements Categories:
- Functional: core functional workflows, user features, payment flows
- Non-functional: security as a general quality attribute, usability, reliability, availability, scalability, performance, maintainability, accessibility, response time, throughput, uptime, resilience
- Business: organizational metrics, ROI, market goals
- Security and privacy: specific security controls such as MFA, encryption, access control, device binding, session security, privacy controls
- Regulatory/compliance: banking mandates (RBI KYC 2025, RBI Payment Security 2026, CERT-In 2022, DPDP Act 2023)
- Constraint: technology, architectural, contractual, or deadline constraints
- Assumption: operational preconditions or assumptions
- Stakeholder expectation: high-level qualitative stakeholder desires

Important:
1. Never invent regulatory obligations. Every regulatory requirement must be grounded in provided regulatory context.
2. Distinguish explicit requirements (directly stated) from inferred requirements (mandatory regulatory obligations).
3. Flag ambiguities, conflicting statements, and missing information.
4. Treat generic quality statements such as "the system should be secure", "the system should be user-friendly", "the system should be reliable", or "the system should be scalable" as Non-functional requirements. Treat specific security mechanisms such as MFA, encryption, authorization, access control, device binding, and audit logging as Security and privacy requirements.
5. Output strictly valid JSON matching ExtractedRequirements schema.
"""

    def __init__(
        self,
        rag_pipeline: Optional[RAGPipeline] = None,
        llm_provider: Optional[LLMProvider] = None
    ):
        self.rag = rag_pipeline or RAGPipeline()
        self.llm = llm_provider or get_llm_provider()
        self.fallback_engine = FallbackDomainEngine(self.rag)

    def analyze(self, stakeholder_text: str) -> ExtractedRequirements:
        """Processes stakeholder text into structured and validated ExtractedRequirements."""
        if not stakeholder_text or not stakeholder_text.strip():
            return ExtractedRequirements()

        # The built-in banking sample has a deterministic reference result so the
        # classroom/demo UI is stable. Other inputs use the normal LLM/RAG path.
        if is_demo_input(stakeholder_text):
            return requirement_fixture()

        self.rag.ensure_ingested()

        # If using live LLM provider (Ollama, OpenAI, etc.)
        if not isinstance(self.llm, FallbackProvider) and self.llm.is_available():
            try:
                # Retrieve relevant regulatory context
                regulatory_hits = self.rag.retrieve(
                    query=stakeholder_text[:500],
                    top_k=4,
                    source_type_filter="regulatory"
                )
                rag_context = "\n\n".join(
                    f"[{c[0]['doc_name']} - {c[0]['section_title']}]:\n{c[0]['content']}"
                    for c in regulatory_hits
                )

                compact_schema = (
                    "Return JSON with these top-level keys:\n"
                    "  requirements: list of objects with keys: id (REQ-NNN), title, description, "
                    "category (one of: Functional|Non-functional|Business|Security and privacy|"
                    "Regulatory/compliance|Constraint|Assumption|Stakeholder expectation), "
                    "priority (Critical|High|Medium|Low), origin (stakeholder|regulatory), "
                    "is_explicit (bool), source_reference (string), "
                    "supporting_passage (short quote <=180 chars or null), "
                    "confidence (0.0-1.0), explanation (string)\n"
                    "  ambiguities: list of {requirement_id, problematic_text, issue, suggested_clarification}\n"
                    "  conflicts: list of {conflicting_requirement_ids (list), description, severity (Critical|High|Medium|Low), resolution_recommendation}\n"
                    "  missing_information: list of {area, description, potential_impact}\n"
                )
                prompt = (
                    f"STAKEHOLDER INPUT:\n{stakeholder_text}\n\n"
                    f"RELEVANT REGULATORY CONTEXT:\n{rag_context}\n\n"
                    f"{compact_schema}\n"
                    "Return ONLY valid JSON."
                )

                raw_response = self.llm.generate(
                    prompt, system_prompt=self.SYSTEM_PROMPT, json_mode=True
                )
                cleaned_json = self.llm.repair_truncated_json(raw_response)
                parsed_data = json.loads(cleaned_json)
                extracted = ExtractedRequirements.model_validate(parsed_data)
                if not extracted.category_counts:
                    for req in extracted.requirements:
                        cat = req.category.value
                        extracted.category_counts[cat] = extracted.category_counts.get(cat, 0) + 1
                if not extracted.priority_counts:
                    for req in extracted.requirements:
                        pri = req.priority.value
                        extracted.priority_counts[pri] = extracted.priority_counts.get(pri, 0) + 1
                logger.info(f"LLM successfully extracted {len(extracted.requirements)} requirements.")
                return extracted
            except Exception as e:
                logger.warning(
                    f"LLM extraction or validation failed: {e}. "
                    "Falling back to domain expert engine."
                )

        # Fallback domain engine execution
        return self.fallback_engine.analyze_requirements(stakeholder_text)

    def generate_markdown_report(self, extracted: ExtractedRequirements) -> str:
        """Generates an executive Markdown report of extracted requirements and compliance analysis."""
        lines = [
            "# Digital Banking Requirements Engineering Report",
            "",
            "## 1. Executive Summary",
            f"- **Total Requirements Extracted**: {len(extracted.requirements)}",
            f"- **Ambiguities Identified**: {len(extracted.ambiguities)}",
            f"- **Conflicts Detected**: {len(extracted.conflicts)}",
            f"- **Missing Information Areas**: {len(extracted.missing_information)}",
            "",
            "### Requirements Distribution by Category",
            "| Category | Count |",
            "| :--- | :--- |"
        ]

        for cat, count in sorted(extracted.category_counts.items()):
            lines.append(f"| {cat} | {count} |")

        lines.extend([
            "",
            "### Requirements Distribution by Priority",
            "| Priority | Count |",
            "| :--- | :--- |"
        ])

        for pri, count in sorted(extracted.priority_counts.items()):
            lines.append(f"| {pri} | {count} |")

        lines.extend([
            "",
            "## 2. Structured Requirements Catalog",
            "| ID | Priority | Category | Origin | Title & Description | Source & Regulatory Reference |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])

        for r in extracted.requirements:
            origin_badge = f"**{r.origin.value.upper()}**" + (" *(Inferred)*" if not r.is_explicit else "")
            ref_text = r.source_reference
            if r.supporting_passage:
                ref_text += f"<br><sub>*Passage: {r.supporting_passage[:100]}...*</sub>"
            lines.append(
                f"| `{r.id}` | {r.priority.value} | {r.category.value} | {origin_badge} | "
                f"**{r.title}**<br>{r.description} | {ref_text} |"
            )

        if extracted.ambiguities:
            lines.extend([
                "",
                "## 3. Ambiguities & Clarifications Needed",
                "| ID / Ref | Problematic Phrasing | Issue Identified | Recommended Clarification |",
                "| :--- | :--- | :--- | :--- |"
            ])
            for a in extracted.ambiguities:
                req_ref = f"`{a.requirement_id}`" if a.requirement_id else "General"
                lines.append(f"| {req_ref} | *\"{a.problematic_text}\"* | {a.issue} | {a.suggested_clarification} |")

        if extracted.conflicts:
            lines.extend([
                "",
                "## 4. Conflicting Requirements",
                "| Conflicting IDs | Conflict Description | Severity | Recommended Resolution |",
                "| :--- | :--- | :--- | :--- |"
            ])
            for c in extracted.conflicts:
                ids_str = ", ".join(f"`{cid}`" for cid in c.conflicting_requirement_ids)
                lines.append(f"| {ids_str} | {c.description} | {c.severity.value} | {c.resolution_recommendation} |")

        if extracted.missing_information:
            lines.extend([
                "",
                "## 5. Missing Information & Compliance Gaps",
                "| Area | Description | Potential Regulatory / Operational Impact |",
                "| :--- | :--- | :--- |"
            ])
            for m in extracted.missing_information:
                lines.append(f"| **{m.area}** | {m.description} | {m.potential_impact} |")

        return "\n".join(lines)
