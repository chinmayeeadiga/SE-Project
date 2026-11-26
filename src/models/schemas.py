from __future__ import annotations
from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class RequirementCategory(str, Enum):
    FUNCTIONAL = "Functional"
    NON_FUNCTIONAL = "Non-functional"
    BUSINESS = "Business"
    SECURITY_PRIVACY = "Security and privacy"
    REGULATORY_COMPLIANCE = "Regulatory/compliance"
    CONSTRAINT = "Constraint"
    ASSUMPTION = "Assumption"
    STAKEHOLDER_EXPECTATION = "Stakeholder expectation"


class RequirementPriority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class RequirementOrigin(str, Enum):
    STAKEHOLDER = "stakeholder"
    REGULATORY = "regulatory"


class Requirement(BaseModel):
    id: str = Field(..., description="Unique requirement ID, e.g., REQ-FUNC-001")
    title: str = Field(..., description="Concise title of the requirement")
    description: str = Field(..., description="Full requirement text")
    category: RequirementCategory = Field(..., description="Classification category")
    priority: RequirementPriority = Field(default=RequirementPriority.MEDIUM, description="Priority level")
    origin: RequirementOrigin = Field(..., description="Origin: stakeholder or regulatory")
    is_explicit: bool = Field(True, description="True if explicitly stated, False if inferred")
    source_reference: str = Field(..., description="Citation of stakeholder text or regulatory section")
    supporting_passage: Optional[str] = Field(None, description="Verbatim retrieved passage backing this requirement")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    explanation: str = Field(..., description="Explanation of why this requirement was created and categorized")


class AmbiguityItem(BaseModel):
    requirement_id: Optional[str] = None
    problematic_text: str
    issue: str
    suggested_clarification: str


class ConflictItem(BaseModel):
    conflicting_requirement_ids: List[str]
    description: str
    severity: RequirementPriority
    resolution_recommendation: str


class MissingInfoItem(BaseModel):
    area: str
    description: str
    potential_impact: str


class ExtractedRequirements(BaseModel):
    requirements: List[Requirement] = Field(default_factory=list)
    ambiguities: List[AmbiguityItem] = Field(default_factory=list)
    conflicts: List[ConflictItem] = Field(default_factory=list)
    missing_information: List[MissingInfoItem] = Field(default_factory=list)
    category_counts: Dict[str, int] = Field(default_factory=dict)
    priority_counts: Dict[str, int] = Field(default_factory=dict)


class ComplianceStatus(str, Enum):
    COMPLIANT = "Compliant"
    NEEDS_REVIEW = "Needs Review"
    NOT_APPLICABLE = "Not Applicable"


class ComplianceCheck(BaseModel):
    requirement_id: str
    requirement: str
    status: ComplianceStatus
    standard: str
    section: Optional[str] = None
    evidence: Optional[str] = None
    notes: str


class ComplianceReport(BaseModel):
    summary: str
    checks: List[ComplianceCheck] = Field(default_factory=list)
    verified_requirement_count: int = 0
    domain_derived_count: int = 0
    compliant_count: int = 0
    needs_review_count: int = 0
    not_applicable_count: int = 0


class SDLCModelName(str, Enum):
    WATERFALL = "Waterfall"
    V_MODEL = "V-Model"
    PROTOTYPE = "Prototype"
    SPIRAL = "Spiral"
    RAD = "RAD"
    INCREMENTAL = "Incremental"


class FactorAssessment(BaseModel):
    factor_name: str
    score: float = Field(..., description="Rating or intensity 0.0 to 10.0")
    assessment_level: str = Field(..., description="e.g. High, Medium, Low")
    evidence: str = Field(..., description="Observed evidence from input and requirements")
    impact_on_models: Dict[str, float] = Field(default_factory=dict, description="Impact score per SDLC model")


class SDLCDecision(BaseModel):
    recommended_model: SDLCModelName
    model_scores: Dict[str, float] = Field(..., description="Normalized scores (0-100) for all 6 SDLC models")
    factors_considered: List[FactorAssessment] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    sdlc_reference_passages: List[str] = Field(default_factory=list)
    explanation: str = Field(..., description="In-depth rationale comparing winner with alternatives")
    confidence: float = Field(..., ge=0.0, le=1.0)
    uncertainties: List[str] = Field(default_factory=list)
    tie_break_notes: Optional[str] = None


class ProjectCharacteristics(BaseModel):
    domain: str = "Digital Banking"
    estimated_size: str = "Medium"
    timeline_constraint: Optional[str] = None
    risk_level: str = "Medium"
    testing_criticality: str = "High"
    modular_architecture: bool = True
    team_experience: str = "Experienced"
    user_interaction_focus: bool = False


class TraceabilityEntry(BaseModel):
    requirement_id: str
    origin: RequirementOrigin
    regulatory_standard: Optional[str] = None
    clause_or_section: Optional[str] = None
    sdlc_phase: str
    validation_status: str


class CombinedReport(BaseModel):
    project_title: str
    timestamp: str
    execution_mode: str
    project_characteristics: ProjectCharacteristics
    requirements_analysis: ExtractedRequirements
    compliance_report: Optional[ComplianceReport] = None
    sdlc_recommendation: SDLCDecision
    traceability_matrix: List[TraceabilityEntry] = Field(default_factory=list)
    summary_markdown: str
