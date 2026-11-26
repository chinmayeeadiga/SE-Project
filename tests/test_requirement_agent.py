import pytest
from src.agents.requirement_agent import RequirementAnalysisAgent
from src.models.schemas import RequirementCategory, RequirementPriority, RequirementOrigin


def test_requirement_extraction_and_classification(shared_rag_pipeline):
    agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)

    sample_input = """
    # Retail Core Banking System Requirements
    - The customer must be able to view account balance in real-time.
    - System response time must be under 200ms at peak load of 5000 TPS.
    - The bank wants to increase digital customer acquisition by 35% in Year 1.
    - All data at rest must be encrypted using AES-256 and TLS 1.3 in transit.
    - The system must verify Customer Due Diligence (CDD) using Aadhaar e-KYC.
    - The system must be deployed strictly on on-premises bare-metal servers.
    - We assume high-speed fiber connectivity is available at all bank branches.
    - Management expects zero regulatory penalties during RBI annual audit inspections.
    """

    res = agent.analyze(sample_input)
    assert len(res.requirements) >= 8

    categories_found = {r.category for r in res.requirements}
    assert RequirementCategory.FUNCTIONAL in categories_found
    assert RequirementCategory.NON_FUNCTIONAL in categories_found
    assert RequirementCategory.BUSINESS in categories_found
    assert RequirementCategory.SECURITY_PRIVACY in categories_found
    assert RequirementCategory.REGULATORY_COMPLIANCE in categories_found
    assert RequirementCategory.CONSTRAINT in categories_found
    assert RequirementCategory.ASSUMPTION in categories_found
    assert RequirementCategory.STAKEHOLDER_EXPECTATION in categories_found


def test_explicit_vs_inferred_requirements(shared_rag_pipeline):
    agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)

    sample_input = """
    We are building a mobile payment app for peer-to-peer UPI transfers.
    Users will log in and transfer funds between accounts.
    """

    res = agent.analyze(sample_input)
    explicit_reqs = [r for r in res.requirements if r.is_explicit]
    inferred_reqs = [r for r in res.requirements if not r.is_explicit]

    assert len(explicit_reqs) > 0
    # Mandatory banking regulations (2FA / CERT-In) should be inferred for digital payments
    assert len(inferred_reqs) > 0
    for inf in inferred_reqs:
        assert inf.origin == RequirementOrigin.REGULATORY
        assert inf.supporting_passage is not None
        assert len(inf.supporting_passage) > 0


def test_deduplication_without_losing_information(shared_rag_pipeline):
    agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)

    sample_input = """
    - Customers must be able to download monthly account statement in PDF format.
    - Customers must be able to download monthly account statement in PDF format.
    - System must support OTP login for user authentication.
    - System must support OTP login for user authentication with SMS gateway.
    """

    res = agent.analyze(sample_input)
    descriptions = [r.description for r in res.requirements]
    # Identical statement requirement should be deduplicated
    pdf_reqs = [d for d in descriptions if "monthly account statement" in d.lower()]
    assert len(pdf_reqs) == 1


def test_regulatory_traceability_no_hallucination(shared_rag_pipeline):
    agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)

    sample_input = """
    The bank must comply with CERT-In directions for reporting cyber incidents.
    """

    res = agent.analyze(sample_input)
    cert_reqs = [r for r in res.requirements if "cert-in" in r.description.lower() or "cert-in" in r.source_reference.lower()]
    assert len(cert_reqs) > 0
    for r in cert_reqs:
        assert "cert_in_directions_2022" in r.source_reference or "CERT-In" in r.source_reference
        if r.supporting_passage:
            assert "6 hours" in r.supporting_passage or "incident" in r.supporting_passage


def test_ambiguity_and_conflict_detection(shared_rag_pipeline):
    agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)

    sample_input = """
    The mobile banking app must be super fast, seamless, and user-friendly.
    The executive board mandates rapid delivery within a strict 60 days window.
    The system cannot be modularized and requires complete system delivery at once in a single release.
    """

    res = agent.analyze(sample_input)
    assert len(res.ambiguities) >= 2
    ambiguous_terms = [a.problematic_text for a in res.ambiguities]
    assert "fast" in ambiguous_terms or "seamless" in ambiguous_terms or "user-friendly" in ambiguous_terms

    assert len(res.conflicts) >= 1
    assert any("60 day" in c.description.lower() or "modular" in c.description.lower() for c in res.conflicts)
