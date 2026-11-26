import pytest
from pathlib import Path
from src.agents.requirement_agent import RequirementAnalysisAgent
from src.agents.sdlc_agent import SDLCDetectorAgent
from src.models.schemas import SDLCModelName, RequirementCategory, RequirementOrigin


def test_ambiguous_and_conflicting_synthetic_case(shared_rag_pipeline):
    req_agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)
    sdlc_agent = SDLCDetectorAgent(rag_pipeline=shared_rag_pipeline)

    sample_path = Path("sample_inputs") / "ambiguous_conflicting_sample.md"
    with open(sample_path, "r", encoding="utf-8") as f:
        text = f.read()

    reqs = req_agent.analyze(text)

    # 1. Ambiguity detection
    assert len(reqs.ambiguities) >= 3, "Expected multiple ambiguous terms detected"
    ambiguity_terms = {a.problematic_text for a in reqs.ambiguities}
    assert any(term in ambiguity_terms for term in ["fast", "seamless", "user-friendly", "modern UI", "scalable", "robust"])

    # 2. Conflicting requirements detection
    assert len(reqs.conflicts) >= 1, "Expected architectural conflict between rapid delivery and non-modular complete delivery"
    assert any("60 day" in c.description.lower() or "modular" in c.description.lower() for c in reqs.conflicts)

    # 3. Missing info detection
    assert len(reqs.missing_information) >= 1, "Expected missing DPDP consent withdrawal gap"
    assert any("consent" in m.area.lower() or "dpdp" in m.area.lower() for m in reqs.missing_information)

    # 4. Duplicate requirements deduplication
    otp_reqs = [r for r in reqs.requirements if "otp" in r.description.lower()]
    assert len(otp_reqs) == 1, "Expected duplicate OTP login requirement to be deduplicated"

    # 5. SDLC detection handles uncertainty
    decision = sdlc_agent.detect(text, reqs)
    assert decision.recommended_model is not None
    # Because of contradictory statements (rapid vs monolithic), scores should reflect tension or uncertainties
    assert decision.confidence < 0.95 or len(decision.uncertainties) > 0 or decision.tie_break_notes is not None


def test_unsupported_claims_prevention(shared_rag_pipeline):
    """Ensures regulatory origin requirements always have verifiable citations and supporting passages."""
    req_agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)

    sample_input = """
    The bank is introducing a contactless credit card payments gateway and mobile wallet.
    All payments must undergo 2FA and strict authentication controls.
    """

    reqs = req_agent.analyze(sample_input)
    reg_reqs = [r for r in reqs.requirements if r.origin == RequirementOrigin.REGULATORY]

    assert len(reg_reqs) > 0
    for r in reg_reqs:
        # Must have legitimate document reference
        assert any(
            doc in r.source_reference
            for doc in ["rbi", "cert_in", "dpdp", "owasp", "nist", "Directions", "Act", "Rules"]
        ), f"Unsupported citation: {r.source_reference}"

        # Must have supporting passage
        assert r.supporting_passage is not None and len(r.supporting_passage) > 30, (
            f"Regulatory requirement {r.id} missing supporting passage"
        )
