import json
import pytest
from pathlib import Path
from src.orchestrator import Orchestrator
from src.llm.provider import LLMProvider


class BrokenLLMProvider(LLMProvider):
    """Simulates an LLM returning broken, unparseable, non-JSON output."""
    def generate(self, prompt: str, system_prompt=None) -> str:
        return "I am an AI and I cannot generate valid JSON right now. Here is random text: {broken json..."


def test_orchestrator_end_to_end_flow(tmp_path, shared_rag_pipeline):
    orchestrator = Orchestrator(
        rag_pipeline=shared_rag_pipeline,
        output_dir=tmp_path
    )

    stakeholder_input = """
    # Fast-Track SME Working Capital Loan Portal
    The bank requires rapid delivery within a strict 60-90 days window.
    The system architecture is completely modular with high component reuse.
    The team has assembled highly experienced developers expert in cloud tools.
    Stakeholders will engage in continuous daily user feedback loops.
    The portal must verify business applicant KYC and financial statements.
    """

    report = orchestrator.run(
        stakeholder_input=stakeholder_input,
        project_title="SME Loan Test Project",
        save_outputs=True
    )

    assert report.project_title == "SME Loan Test Project"
    assert len(report.requirements_analysis.requirements) > 0
    assert report.sdlc_recommendation.recommended_model.value == "RAD"
    assert len(report.traceability_matrix) > 0
    assert len(report.summary_markdown) > 500

    # Verify saved files
    json_files = list(tmp_path.glob("*.json"))
    md_files = list(tmp_path.glob("*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1

    # Verify JSON file structure
    with open(json_files[0], "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["project_title"] == "SME Loan Test Project"
    assert "requirements_analysis" in saved_data
    assert "sdlc_recommendation" in saved_data


def test_orchestrator_input_validation(shared_rag_pipeline):
    orchestrator = Orchestrator(rag_pipeline=shared_rag_pipeline)

    # Empty input
    with pytest.raises(ValueError, match="non-empty string"):
        orchestrator.run(stakeholder_input="")

    # Too short input
    with pytest.raises(ValueError, match="too brief"):
        orchestrator.run(stakeholder_input="Too short.")


def test_orchestrator_recovers_from_broken_llm(tmp_path, shared_rag_pipeline):
    broken_llm = BrokenLLMProvider()
    orchestrator = Orchestrator(
        rag_pipeline=shared_rag_pipeline,
        llm_provider=broken_llm,
        output_dir=tmp_path
    )

    stakeholder_input = """
    # High Assurance Mission Critical Switch
    The system is safety-critical and requires continuous verification and validation at every development stage.
    Requirements are stable and well-defined upfront.
    Traceability between requirements and acceptance testing is mandatory.
    """

    # Orchestrator must not crash; it catches broken LLM response and gracefully uses domain fallback
    report = orchestrator.run(
        stakeholder_input=stakeholder_input,
        project_title="Resilience Test Project",
        save_outputs=True
    )

    assert report is not None
    assert len(report.requirements_analysis.requirements) > 0
    assert report.sdlc_recommendation.recommended_model.value == "V-Model"
