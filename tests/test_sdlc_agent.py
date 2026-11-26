import pytest
from pathlib import Path
from src.agents.requirement_agent import RequirementAnalysisAgent
from src.agents.sdlc_agent import SDLCDetectorAgent
from src.models.schemas import SDLCModelName


def load_sample(filename: str) -> str:
    path = Path("sample_inputs") / filename
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_sdlc_all_six_models(shared_rag_pipeline):
    req_agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)
    sdlc_agent = SDLCDetectorAgent(rag_pipeline=shared_rag_pipeline)

    test_matrix = [
        ("waterfall_core_banking.md", SDLCModelName.WATERFALL),
        ("vmodel_highassurance_atm.md", SDLCModelName.V_MODEL),
        ("prototype_wealth_ui.md", SDLCModelName.PROTOTYPE),
        ("spiral_crossborder_crypto_ai.md", SDLCModelName.SPIRAL),
        ("rad_loan_approval_portal.md", SDLCModelName.RAD),
        ("incremental_retail_neobank.md", SDLCModelName.INCREMENTAL),
    ]

    for filename, expected_model in test_matrix:
        text = load_sample(filename)
        reqs = req_agent.analyze(text)
        decision = sdlc_agent.detect(text, reqs)
        assert decision.recommended_model == expected_model, (
            f"Failed on {filename}: expected {expected_model.value}, got {decision.recommended_model.value}. "
            f"Scores: {decision.model_scores}"
        )
        assert len(decision.factors_considered) == 8
        assert len(decision.supporting_evidence) > 0
        assert decision.confidence >= 0.70


def test_distinguish_rad_from_prototype(shared_rag_pipeline):
    req_agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)
    sdlc_agent = SDLCDetectorAgent(rag_pipeline=shared_rag_pipeline)

    # RAD Case
    rad_text = load_sample("rad_loan_approval_portal.md")
    rad_reqs = req_agent.analyze(rad_text)
    rad_decision = sdlc_agent.detect(rad_text, rad_reqs)
    assert rad_decision.recommended_model == SDLCModelName.RAD
    assert rad_decision.model_scores[SDLCModelName.RAD.value] > rad_decision.model_scores[SDLCModelName.PROTOTYPE.value]

    # Prototype Case
    proto_text = load_sample("prototype_wealth_ui.md")
    proto_reqs = req_agent.analyze(proto_text)
    proto_decision = sdlc_agent.detect(proto_text, proto_reqs)
    assert proto_decision.recommended_model == SDLCModelName.PROTOTYPE
    assert proto_decision.model_scores[SDLCModelName.PROTOTYPE.value] > proto_decision.model_scores[SDLCModelName.RAD.value]


def test_distinguish_waterfall_from_vmodel(shared_rag_pipeline):
    req_agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)
    sdlc_agent = SDLCDetectorAgent(rag_pipeline=shared_rag_pipeline)

    # Waterfall Case
    wf_text = load_sample("waterfall_core_banking.md")
    wf_reqs = req_agent.analyze(wf_text)
    wf_decision = sdlc_agent.detect(wf_text, wf_reqs)
    assert wf_decision.recommended_model == SDLCModelName.WATERFALL
    assert wf_decision.model_scores[SDLCModelName.WATERFALL.value] > wf_decision.model_scores[SDLCModelName.V_MODEL.value]

    # V-Model Case
    vm_text = load_sample("vmodel_highassurance_atm.md")
    vm_reqs = req_agent.analyze(vm_text)
    vm_decision = sdlc_agent.detect(vm_text, vm_reqs)
    assert vm_decision.recommended_model == SDLCModelName.V_MODEL
    assert vm_decision.model_scores[SDLCModelName.V_MODEL.value] > vm_decision.model_scores[SDLCModelName.WATERFALL.value]


def test_distinguish_spiral_from_incremental(shared_rag_pipeline):
    req_agent = RequirementAnalysisAgent(rag_pipeline=shared_rag_pipeline)
    sdlc_agent = SDLCDetectorAgent(rag_pipeline=shared_rag_pipeline)

    # Spiral Case
    sp_text = load_sample("spiral_crossborder_crypto_ai.md")
    sp_reqs = req_agent.analyze(sp_text)
    sp_decision = sdlc_agent.detect(sp_text, sp_reqs)
    assert sp_decision.recommended_model == SDLCModelName.SPIRAL
    assert sp_decision.model_scores[SDLCModelName.SPIRAL.value] > sp_decision.model_scores[SDLCModelName.INCREMENTAL.value]

    # Incremental Case
    inc_text = load_sample("incremental_retail_neobank.md")
    inc_reqs = req_agent.analyze(inc_text)
    inc_decision = sdlc_agent.detect(inc_text, inc_reqs)
    assert inc_decision.recommended_model == SDLCModelName.INCREMENTAL
    assert inc_decision.model_scores[SDLCModelName.INCREMENTAL.value] > inc_decision.model_scores[SDLCModelName.SPIRAL.value]
