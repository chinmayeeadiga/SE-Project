import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.config import settings
from src.rag.pipeline import RAGPipeline
from src.llm.provider import LLMProvider, get_llm_provider
from src.agents.requirement_agent import RequirementAnalysisAgent
from src.agents.sdlc_agent import SDLCDetectorAgent
from src.agents.compliance_agent import ComplianceAgent
from src.models.schemas import (
    CombinedReport,
    ExtractedRequirements,
    SDLCDecision,
    ProjectCharacteristics,
    TraceabilityEntry,
    RequirementOrigin,
    RequirementCategory
)

logger = logging.getLogger(__name__)


class Orchestrator:
    """End-to-end Orchestrator for Digital Banking Requirements Engineering and SDLC Decisioning."""

    def __init__(
        self,
        rag_pipeline: Optional[RAGPipeline] = None,
        llm_provider: Optional[LLMProvider] = None,
        output_dir: Optional[Path] = None
    ):
        self.rag = rag_pipeline or RAGPipeline()
        self.llm = llm_provider or get_llm_provider()
        self.output_dir = Path(output_dir or settings.OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize agents with shared RAG pipeline and LLM
        self.req_agent = RequirementAnalysisAgent(rag_pipeline=self.rag, llm_provider=self.llm)
        self.compliance_agent = ComplianceAgent(rag_pipeline=self.rag, llm_provider=self.llm)
        self.sdlc_agent = SDLCDetectorAgent(rag_pipeline=self.rag, llm_provider=self.llm)

    def validate_input(self, stakeholder_text: str) -> str:
        """Validates stakeholder text for substantive content."""
        if not stakeholder_text or not isinstance(stakeholder_text, str):
            raise ValueError("Stakeholder input must be a non-empty string.")

        cleaned = stakeholder_text.strip()
        if len(cleaned) < 30:
            raise ValueError(
                f"Stakeholder input is too brief ({len(cleaned)} chars) to analyze. "
                "Please provide substantive project requirements."
            )
        return cleaned

    def derive_project_characteristics(
        self,
        stakeholder_text: str,
        requirements: ExtractedRequirements
    ) -> ProjectCharacteristics:
        """Derives structured project traits from requirements and input."""
        lower_input = stakeholder_text.lower()
        req_texts = " ".join(r.description.lower() for r in requirements.requirements)
        combined = f"{lower_input} {req_texts}"

        # Risk level
        risk_level = "Medium"
        if any(w in combined for w in ["high-risk", "mission-critical", "safety-critical", "zero tolerance"]):
            risk_level = "High"
        elif any(w in combined for w in ["low risk", "internal prototype", "pilot"]):
            risk_level = "Low"

        # Modular architecture
        modular = True
        if "cannot be modularized" in combined or "monolithic core" in combined:
            modular = False

        # Timeline
        timeline = None
        if "60-90" in combined or "60 days" in combined:
            timeline = "Strict 60-90 days"
        elif "phased" in combined or "staged" in combined or "increments" in combined:
            timeline = "Phased increments"

        # User interaction focus
        ui_focus = any(w in combined for w in ["ui", "user interface", "ux", "mobile app", "interactive", "prototype"])

        return ProjectCharacteristics(
            domain="Digital Banking & Payments",
            estimated_size="Large" if len(requirements.requirements) > 15 else "Medium",
            timeline_constraint=timeline,
            risk_level=risk_level,
            testing_criticality="High" if any(r.priority.value == "Critical" for r in requirements.requirements) else "Medium",
            modular_architecture=modular,
            team_experience="Experienced" if "experienced" in combined else "Standard",
            user_interaction_focus=ui_focus
        )

    def build_traceability_matrix(
        self,
        requirements: ExtractedRequirements,
        sdlc_decision: SDLCDecision
    ) -> List[TraceabilityEntry]:
        """Maps each requirement to banking standards and SDLC verification phases."""
        matrix: List[TraceabilityEntry] = []
        rec_model = sdlc_decision.recommended_model.value

        for r in requirements.requirements:
            reg_standard = None
            clause_info = None

            if r.origin == RequirementOrigin.REGULATORY or "kyc" in r.description.lower():
                reg_standard = "RBI KYC Directions 2025"
                clause_info = r.source_reference
            elif "incident" in r.description.lower() or "6 hour" in r.description.lower():
                reg_standard = "CERT-In Directions 2022"
                clause_info = "Sub-section (6) Section 70B"
            elif "dpdp" in r.description.lower() or "consent" in r.description.lower():
                reg_standard = "DPDP Act 2023 / DPDP Rules 2025"
                clause_info = r.source_reference
            elif "payment" in r.description.lower() or "auth" in r.description.lower() or "device" in r.description.lower():
                reg_standard = "RBI Digital Payment Security Directions 2026"
                clause_info = r.source_reference
            elif r.category == RequirementCategory.SECURITY_PRIVACY:
                reg_standard = "OWASP ASVS 5.0 / NIST CSF 2.0"
                clause_info = "Application Security Verification"

            # Determine SDLC verification phase based on model
            if rec_model == "V-Model":
                if r.category in (RequirementCategory.FUNCTIONAL, RequirementCategory.BUSINESS):
                    phase = "Acceptance Testing & User Validation"
                elif r.category in (RequirementCategory.SECURITY_PRIVACY, RequirementCategory.REGULATORY_COMPLIANCE):
                    phase = "System Security Testing & Regulatory Audit"
                elif r.category == RequirementCategory.NON_FUNCTIONAL:
                    phase = "Integration & Performance Testing"
                else:
                    phase = "Unit & Module Verification"
            elif rec_model == "RAD":
                phase = "Application Generation & Turnover"
            elif rec_model == "Spiral":
                phase = "Risk Analysis & Evaluation Spiral"
            elif rec_model == "Incremental":
                phase = "Target Release Increment Verification"
            elif rec_model == "Prototype":
                phase = "Stakeholder Prototype Evaluation"
            else:
                phase = "Verification & Acceptance"

            matrix.append(TraceabilityEntry(
                requirement_id=r.id,
                origin=r.origin,
                regulatory_standard=reg_standard,
                clause_or_section=clause_info,
                sdlc_phase=phase,
                validation_status="Passed Verification" if r.confidence >= 0.8 else "Needs Clarification"
            ))

        return matrix

    def run(
        self,
        stakeholder_input: str,
        project_title: str = "Digital Banking Requirements Engineering Project",
        save_outputs: bool = True
    ) -> CombinedReport:
        """Executes full end-to-end requirements engineering and SDLC detection workflow."""
        logger.info(f"Starting Requirements Engineering Workflow for: '{project_title}'")

        # 1 & 2. Validate input
        valid_text = self.validate_input(stakeholder_input)

        # 3, 4, 5. Extract and classify requirements with RAG
        logger.info("Executing Requirement Analysis Agent...")
        extracted_reqs = self.req_agent.analyze(valid_text)

        # 6. Compliance verification
        logger.info("Executing Compliance Agent...")
        compliance_result = self.compliance_agent.analyze(valid_text, extracted_reqs)

        # 7. Derive project characteristics
        logger.info("Deriving Project Characteristics...")
        proj_chars = self.derive_project_characteristics(valid_text, extracted_reqs)

        # 8. Run SDLC detection
        logger.info("Executing SDLC Detection Agent...")
        sdlc_result = self.sdlc_agent.detect(valid_text, extracted_reqs)

        # 9. Build traceability matrix
        traceability = self.build_traceability_matrix(extracted_reqs, sdlc_result)

        # Generate markdown report
        req_md = self.req_agent.generate_markdown_report(extracted_reqs)
        sdlc_md = self.sdlc_agent.generate_markdown_report(sdlc_result)

        full_markdown = (
            f"# {project_title}\n\n"
            f"**Execution Timestamp**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
            f"**Recommended SDLC Model**: **{sdlc_result.recommended_model.value}** ({int(sdlc_result.confidence * 100)}% confidence)  \n"
            f"**Total Requirements**: {len(extracted_reqs.requirements)}  \n\n"
            "## Agent 1: Requirement Analyser — Completed\n\n"
            f"{req_md}\n\n"
            "---\n\n"
            "## Agent 2: Compliance Agent — Completed\n\n"
            f"{self.compliance_agent.generate_markdown_report(compliance_result)}\n\n"
            "---\n\n"
            "## Agent 3: SDLC Determiner — Completed\n\n"
            f"{sdlc_md}\n\n"
            "---\n\n"
            "## 6. End-to-End Compliance & SDLC Traceability Matrix\n\n"
            "| Requirement ID | Standard / Regulation | Clause / Section Citation | Target SDLC Phase | Status |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
        )

        for t in traceability:
            std = t.regulatory_standard or "Stakeholder Specification"
            clause = t.clause_or_section or "N/A"
            full_markdown += f"| `{t.requirement_id}` | {std} | {clause} | {t.sdlc_phase} | {t.validation_status} |\n"

        report = CombinedReport(
            project_title=project_title,
            timestamp=datetime.now().isoformat(),
            execution_mode="Production (Shared RAG + Multi-Agent)",
            project_characteristics=proj_chars,
            requirements_analysis=extracted_reqs,
            compliance_report=compliance_result,
            sdlc_recommendation=sdlc_result,
            traceability_matrix=traceability,
            summary_markdown=full_markdown
        )

        # 9. Save JSON and Markdown outputs
        if save_outputs:
            slug = project_title.lower().replace(" ", "_").replace("-", "_")[:40]
            json_path = self.output_dir / f"{slug}_report.json"
            md_path = self.output_dir / f"{slug}_report.md"

            with open(json_path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))

            with open(md_path, "w", encoding="utf-8") as f:
                f.write(full_markdown)

            logger.info(f"Outputs successfully saved to:\n  - {json_path}\n  - {md_path}")

        return report
