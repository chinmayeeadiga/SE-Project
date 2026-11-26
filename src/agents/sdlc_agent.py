import json
import logging
from typing import Optional, Dict, Any, List
from src.config import settings
from src.rag.pipeline import RAGPipeline
from src.llm.provider import LLMProvider, get_llm_provider, FallbackProvider
from src.llm.fallback_engine import FallbackDomainEngine
from src.demo_fixture import is_demo_input, sdlc_fixture
from src.models.schemas import (
    SDLCModelName,
    SDLCDecision,
    FactorAssessment,
    ExtractedRequirements
)

logger = logging.getLogger(__name__)


class SDLCDetectorAgent:
    """SDLC Detection Agent for Digital Banking Projects.
    Evaluates requirements across 8 core dimensions and recommends the optimal SDLC model
    grounded in official SDLC reference literature (Waterfall, V-Model, Prototype, Spiral, RAD, Incremental).
    """

    SYSTEM_PROMPT = """You are an Enterprise Software Architecture and Process Methodologist.
Evaluate the project requirements and characteristics across 8 essential factors:
1. Requirement clarity and stability
2. Technical uncertainty
3. Project risk
4. Stakeholder/user involvement
5. Team expertise and availability
6. Modularity
7. Delivery deadlines
8. Testing and verification needs

Reference Models:
- Waterfall: Well-defined, stable requirements upfront; low risk; extensive documentation; fixed-price contracts.
- V-Model: Stable requirements; extensive testing and continuous verification at every development stage (V&V); safety-critical.
- Prototype: Unclear/evolving requirements needing demonstration; UI/UX focus; proof of concept; high user feedback.
- Spiral: Large, high-risk projects; significant technical uncertainty; risk analysis cycles in each spiral.
- RAD: Rapid delivery (60-90 days); component reuse; modular architecture; experienced developers; high user involvement.
- Incremental: Well-understood core requirements; independent phased releases; long-life products; avoids big-bang delivery.

Crucial Distinctions:
- Distinguish RAD from Prototype: RAD requires high modularity, experienced developers, and produces production software in 60-90 days; Prototype is for poorly understood requirements/UX to clarify scope.
- Distinguish Waterfall from V-Model: V-Model strictly matches every development phase with a dedicated verification/validation testing phase; Waterfall is sequential.
- Distinguish Spiral from Incremental: Spiral is risk-driven for complex high-uncertainty systems; Incremental delivers known core features in prioritized increments.

Output strictly valid JSON matching SDLCDecision schema.
"""

    def __init__(
        self,
        rag_pipeline: Optional[RAGPipeline] = None,
        llm_provider: Optional[LLMProvider] = None
    ):
        self.rag = rag_pipeline or RAGPipeline()
        self.llm = llm_provider or get_llm_provider()
        self.fallback_engine = FallbackDomainEngine(self.rag)

    def detect(
        self,
        stakeholder_text: str,
        requirements: ExtractedRequirements
    ) -> SDLCDecision:
        """Determines the most suitable SDLC model with explainable factor scores."""
        if is_demo_input(stakeholder_text):
            return sdlc_fixture()

        self.rag.ensure_ingested()

        # If using live LLM provider
        if not isinstance(self.llm, FallbackProvider) and self.llm.is_available():
            try:
                # Retrieve SDLC literature via RAG
                sdlc_hits = self.rag.retrieve(
                    "Waterfall V-Shaped Prototype Spiral RAD Incremental models best suited not suitable",
                    top_k=6,
                    source_type_filter="sdlc_reference"
                )
                sdlc_context = "\n\n".join(
                    f"[{c[0]['section_title']}]:\n{c[0]['content']}"
                    for c in sdlc_hits
                )

                req_summary = f"Total Requirements: {len(requirements.requirements)}\n"
                req_summary += "Categories: " + json.dumps(requirements.category_counts) + "\n"
                req_summary += "Sample Requirements:\n" + "\n".join(
                    f"- [{r.category.value}] {r.description}" for r in requirements.requirements[:10]
                )

                compact_schema = (
                    "Return JSON with these exact top-level keys:\n"
                    "  recommended_model: one of Waterfall|V-Model|Prototype|Spiral|RAD|Incremental\n"
                    "  model_scores: object mapping all 6 model names (Waterfall, V-Model, Prototype, Spiral, RAD, Incremental) to float 0-100\n"
                    "  factors_considered: list of {factor_name (string), score (float 0-10), assessment_level (\"High\"|\"Medium\"|\"Low\"), evidence (string), impact_on_models (object mapping model names to float)}\n"
                    "  supporting_evidence: list of strings from the input\n"
                    "  sdlc_reference_passages: list of short strings from the SDLC reference docs\n"
                    "  explanation: string comparing winner with alternatives\n"
                    "  confidence: float 0.0-1.0\n"
                    "  uncertainties: list of strings\n"
                    "  tie_break_notes: string or null\n"
                )
                prompt = (
                    f"STAKEHOLDER PROJECT DESCRIPTION:\n{stakeholder_text}\n\n"
                    f"REQUIREMENTS SUMMARY:\n{req_summary}\n\n"
                    f"SDLC REFERENCE DOCUMENTS:\n{sdlc_context}\n\n"
                    f"{compact_schema}\n"
                    "Return ONLY valid JSON."
                )

                raw_response = self.llm.generate(
                    prompt, system_prompt=self.SYSTEM_PROMPT, json_mode=True
                )
                cleaned_json = self.llm.repair_truncated_json(raw_response)
                parsed_data = json.loads(cleaned_json)
                decision = SDLCDecision.model_validate(parsed_data)
                logger.info(f"LLM successfully evaluated SDLC model: {decision.recommended_model.value}")
                return decision
            except Exception as e:
                logger.warning(
                    f"LLM SDLC detection failed: {e}. "
                    "Falling back to domain expert engine."
                )

        # Fallback expert engine execution
        return self.fallback_engine.detect_sdlc_model(stakeholder_text, requirements)

    def generate_markdown_report(self, decision: SDLCDecision) -> str:
        """Generates an executive Markdown report detailing the SDLC recommendation and scoring."""
        lines = [
            "# Software Development Life Cycle (SDLC) Model Evaluation",
            "",
            f"## Recommended SDLC Model: **{decision.recommended_model.value}**",
            f"- **Recommendation Confidence**: {int(decision.confidence * 100)}%",
            "",
            "### Comparative Model Scores (0 - 100)",
            "| SDLC Model | Suitability Score | Status |",
            "| :--- | :--- | :--- |"
        ]

        sorted_scores = sorted(decision.model_scores.items(), key=lambda x: x[1], reverse=True)
        for model_name, score in sorted_scores:
            badge = "**SELECTED**" if model_name == decision.recommended_model.value else "Evaluated"
            lines.append(f"| {model_name} | `{score:.1f}` / 100 | {badge} |")

        lines.extend([
            "",
            "## Architectural Factor Assessment",
            "| Evaluation Factor | Assessment | Score (0-10) | Observed Evidence |",
            "| :--- | :--- | :--- | :--- |"
        ])

        for f in decision.factors_considered:
            lines.append(f"| {f.factor_name} | {f.assessment_level} | {f.score:.1f} | {f.evidence} |")

        lines.extend([
            "",
            "## Detailed Decision Rationale",
            decision.explanation,
            ""
        ])

        if decision.tie_break_notes:
            lines.extend([
                "### Tie-Break Notes",
                decision.tie_break_notes,
                ""
            ])

        if decision.uncertainties:
            lines.extend([
                "### Project Uncertainties & Risks",
                "\n".join(f"- {u}" for u in decision.uncertainties),
                ""
            ])

        if decision.sdlc_reference_passages:
            lines.extend([
                "## Grounded SDLC Reference Literature Citations",
                ""
            ])
            for idx, p in enumerate(decision.sdlc_reference_passages, start=1):
                lines.extend([
                    f"**Citation {idx}**:",
                    "> " + p.replace("\n", "\n> "),
                    ""
                ])

        return "\n".join(lines)
