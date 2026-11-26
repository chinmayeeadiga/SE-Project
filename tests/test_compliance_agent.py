from src.agents.compliance_agent import ComplianceAgent
from src.models.schemas import (
    ExtractedRequirements,
    Requirement,
    RequirementCategory,
    RequirementOrigin,
    RequirementPriority,
    ComplianceStatus,
)


class FakeRAG:
    def ensure_ingested(self):
        pass

    def retrieve(self, query, top_k=2, source_type_filter=None):
        return [
            ({
                "doc_name": "rbi_kyc_directions_2025.txt",
                "section_title": "Customer Identification",
                "content": "Banks shall follow applicable customer identification and due diligence requirements.",
            }, 0.9)
        ]


def test_compliance_agent_verifies_and_derives():
    req = Requirement(
        id="REQ-FUNC-001",
        title="KYC onboarding",
        description="The bank shall perform KYC during customer onboarding.",
        category=RequirementCategory.FUNCTIONAL,
        priority=RequirementPriority.HIGH,
        origin=RequirementOrigin.STAKEHOLDER,
        source_reference="Stakeholder Input Line 1",
        explanation="Stakeholder requirement.",
    )
    result = ComplianceAgent(rag_pipeline=FakeRAG()).analyze(
        "The bank shall perform KYC during customer onboarding.",
        ExtractedRequirements(requirements=[req]),
    )

    assert result.verified_requirement_count == 1
    assert result.domain_derived_count == 1
    assert result.checks[0].status == ComplianceStatus.COMPLIANT
    assert result.checks[1].requirement_id == "REG-DERIVED-KYC"
