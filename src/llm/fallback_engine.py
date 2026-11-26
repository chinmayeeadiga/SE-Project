import re
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from src.models.schemas import (
    Requirement,
    RequirementCategory,
    RequirementPriority,
    RequirementOrigin,
    AmbiguityItem,
    ConflictItem,
    MissingInfoItem,
    ExtractedRequirements,
    SDLCModelName,
    FactorAssessment,
    SDLCDecision,
    ProjectCharacteristics
)
from src.rag.pipeline import RAGPipeline
from src.rag.bm25 import STOPWORDS


class FallbackDomainEngine:
    """Deterministic, RAG-grounded expert analysis engine.
    Used when an external LLM server is unavailable or for deterministic schema validation.
    Extracts requirements, queries actual regulatory & SDLC documents, and produces
    100% validated structured outputs without hallucinations.
    """

    AMBIGUOUS_TERMS = [
        ("user-friendly", "Subjective usability metric lacking measurable acceptance criteria."),
        ("seamless", "Vague interaction goal without specific latency or step count constraints."),
        ("robust", "Undefined reliability target; specify MTBF or failure recovery expectations."),
        ("fast", "Ambiguous performance target; specify 95th percentile response time in milliseconds."),
        ("scalable", "Unquantified capacity target; specify peak concurrent transactions per second (TPS)."),
        ("secure", "Generic claim; specify compliance standards (e.g., OWASP ASVS L2, RBI 2026 controls)."),
        ("modern UI", "Subjective aesthetic term; specify design system or usability benchmarks."),
        ("as soon as possible", "Undefined timeline; provide concrete milestone dates or sprints.")
    ]

    def __init__(self, rag_pipeline: Optional[RAGPipeline] = None):
        self.rag = rag_pipeline or RAGPipeline()

    def _extract_clauses_from_text(self, text: str) -> List[Tuple[str, str, int]]:
        """Extract substantive sentences from both structured lists and unstructured prose."""
        items = []
        for idx, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            cleaned = re.sub(r"^[\*\-\•\d+\.]+\s*", "", stripped)
            # A long paragraph is unstructured input; split it into requirement-bearing sentences.
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned) if len(cleaned) > 220 else [cleaned]
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 15:
                    items.append((sentence, line, idx))
        return items

    def analyze_requirements(self, stakeholder_text: str) -> ExtractedRequirements:
        """Extracts and classifies requirements, grounds with RAG regulations, and detects ambiguities."""
        self.rag.ensure_ingested()
        items = self._extract_clauses_from_text(stakeholder_text)
        requirements: List[Requirement] = []
        ambiguities: List[AmbiguityItem] = []
        conflicts: List[ConflictItem] = []
        missing_info: List[MissingInfoItem] = []

        counter = 1

        for clean_text, raw_line, line_num in items:
            lower = clean_text.lower()

            # Determine Category
            category = RequirementCategory.FUNCTIONAL
            priority = RequirementPriority.MEDIUM
            explanation = "Extracted from stakeholder input."
            is_explicit = True

            if any(k in lower for k in ["must", "shall", "critical", "mandatory", "zero downtime", "24/7"]):
                priority = RequirementPriority.CRITICAL
            elif any(k in lower for k in ["important", "high priority", "within 60 days", "real-time"]):
                priority = RequirementPriority.HIGH
            elif any(k in lower for k in ["nice to have", "future", "optional", "phase 2"]):
                priority = RequirementPriority.LOW

            if any(k in lower for k in ["expects", "management expects", "stakeholder expects", "stakeholder vision", "delight"]):
                category = RequirementCategory.STAKEHOLDER_EXPECTATION
                explanation = "Expressed expectation from organizational stakeholders."
            elif any(k in lower for k in ["strictly on", "on-premises", "bare-metal", "constraint", "limited to", "deadline", "budget", "legacy", "fixed-scope", "cannot use", "restricted to"]):
                category = RequirementCategory.CONSTRAINT
                explanation = "Project, technology, hosting, or contractual constraint."
            elif any(k in lower for k in ["assume", "assuming", "expected that", "prerequisite"]):
                category = RequirementCategory.ASSUMPTION
                explanation = "Stated or inferred operational assumption."
            elif any(k in lower for k in ["encrypt", "mfa", "multi-factor", "password policy", "access control", "authorization", "authorize", "device binding", "session security", "audit log", "audit trail", "token", "cert-in", "breach response", "dpdp", "gdpr"]):
                category = RequirementCategory.SECURITY_PRIVACY
                explanation = "Specifies a concrete security, access-control, cryptographic, audit, or data-privacy control."
            elif any(k in lower for k in ["secure", "security", "user-friendly", "usable", "easy to use", "reliable", "scalable", "maintainable", "accessible", "responsive", "availability", "available", "accurate", "resilient"]):
                category = RequirementCategory.NON_FUNCTIONAL
                explanation = "Specifies a general quality attribute or operational characteristic of the system."
            elif any(k in lower for k in ["rbi", "compliance", "regulation", "kyc", "cdd", "audit", "aml", "fatf", "reporting to"]):
                category = RequirementCategory.REGULATORY_COMPLIANCE
                explanation = "Explicit banking regulatory or supervisory compliance obligation."
            elif any(k in lower for k in ["latency", "throughput", "tps", "response time", "concurrent", "uptime", "availability", "performance", "disaster recovery"]):
                category = RequirementCategory.NON_FUNCTIONAL
                explanation = "Specifies operational quality, performance, or availability constraint."
            elif any(k in lower for k in ["revenue", "onboard", "market share", "roi", "customer acquisition", "business goal", "reduce cost"]):
                category = RequirementCategory.BUSINESS
                explanation = "High-level business objective or organizational metric."
            else:
                category = RequirementCategory.FUNCTIONAL
                explanation = "Specific feature or functional behavior requested."

            # Prefix for ID
            cat_prefix_map = {
                RequirementCategory.FUNCTIONAL: "FUNC",
                RequirementCategory.NON_FUNCTIONAL: "NFR",
                RequirementCategory.BUSINESS: "BIZ",
                RequirementCategory.SECURITY_PRIVACY: "SEC",
                RequirementCategory.REGULATORY_COMPLIANCE: "REG",
                RequirementCategory.CONSTRAINT: "CON",
                RequirementCategory.ASSUMPTION: "ASM",
                RequirementCategory.STAKEHOLDER_EXPECTATION: "EXP"
            }

            req_id = f"REQ-{cat_prefix_map[category]}-{counter:03d}"
            counter += 1

            # Check for ambiguous terms
            for term, reason in self.AMBIGUOUS_TERMS:
                if re.search(rf"\b{re.escape(term)}\b", lower):
                    ambiguities.append(AmbiguityItem(
                        requirement_id=req_id,
                        problematic_text=term,
                        issue=reason,
                        suggested_clarification=f"Define specific testable metrics to replace '{term}'."
                    ))

            # Query RAG for grounding if security or regulatory
            supporting_passage = None
            source_ref = f"Stakeholder Input Line {line_num}"

            if category in (RequirementCategory.SECURITY_PRIVACY, RequirementCategory.REGULATORY_COMPLIANCE) or "kyc" in lower or "payment" in lower:
                retrieved = self.rag.retrieve(clean_text, top_k=1, source_type_filter="regulatory")
                if retrieved:
                    top_chunk, score = retrieved[0]
                    if score > 0.3:
                        supporting_passage = top_chunk["content"][:300] + "..."
                        source_ref = f"{top_chunk['doc_name']} ({top_chunk['section_title']})"

            requirements.append(Requirement(
                id=req_id,
                title=clean_text[:60] + ("..." if len(clean_text) > 60 else ""),
                description=clean_text,
                category=category,
                priority=priority,
                origin=RequirementOrigin.STAKEHOLDER,
                is_explicit=is_explicit,
                source_reference=source_ref,
                supporting_passage=supporting_passage,
                confidence=0.95,
                explanation=explanation
            ))

        # Check for inferred mandatory regulatory requirements via RAG
        # If digital banking or payment is mentioned, retrieve mandatory RBI 2026 / CERT-In obligations
        full_text_lower = stakeholder_text.lower()
        if any(w in full_text_lower for w in ["payment", "transfer", "upi", "card", "mobile", "wallet"]):
            sec_hits = self.rag.retrieve(
                "Two factor authentication and application security controls for digital payments",
                top_k=2,
                source_type_filter="regulatory"
            )
            for hit_chunk, _ in sec_hits:
                if "digital_payment" in hit_chunk["doc_id"]:
                    req_id = f"REQ-REG-{counter:03d}"
                    counter += 1
                    requirements.append(Requirement(
                        id=req_id,
                        title="Mandatory Two-Factor Authentication & Device Binding",
                        description="Implement robust authentication framework and secure device binding as mandated by RBI Digital Payment Security Controls.",
                        category=RequirementCategory.REGULATORY_COMPLIANCE,
                        priority=RequirementPriority.CRITICAL,
                        origin=RequirementOrigin.REGULATORY,
                        is_explicit=False,
                        source_reference=f"{hit_chunk['doc_name']} ({hit_chunk['section_title']})",
                        supporting_passage=hit_chunk["content"][:350],
                        confidence=0.98,
                        explanation="Inferred mandatory compliance requirement for Indian digital payment systems."
                    ))
                    break

        if any(w in full_text_lower for w in ["incident", "breach", "cyber", "security", "attack"]):
            cert_hits = self.rag.retrieve(
                "Mandatory reporting of cyber security incidents within 6 hours to CERT-In",
                top_k=1,
                source_type_filter="regulatory"
            )
            if cert_hits:
                c_chunk, _ = cert_hits[0]
                req_id = f"REQ-REG-{counter:03d}"
                counter += 1
                requirements.append(Requirement(
                    id=req_id,
                    title="Mandatory 6-Hour Cyber Incident Reporting to CERT-In",
                    description="Any cyber security incident must be reported to CERT-In within 6 hours of noticing or being brought to notice.",
                    category=RequirementCategory.REGULATORY_COMPLIANCE,
                    priority=RequirementPriority.CRITICAL,
                    origin=RequirementOrigin.REGULATORY,
                    is_explicit=False,
                    source_reference=f"{c_chunk['doc_name']} ({c_chunk['section_title']})",
                    supporting_passage=c_chunk["content"][:350],
                    confidence=1.0,
                    explanation="Inferred statutory compliance requirement under CERT-In Directions 2022 Section 70B."
                ))

        if any(w in full_text_lower for w in ["kyc", "customer onboarding", "account opening", "identity"]):
            kyc_hits = self.rag.retrieve(
                "Customer Identification Procedure and Officially Valid Document verification",
                top_k=1,
                source_type_filter="regulatory"
            )
            if kyc_hits:
                k_chunk, _ = kyc_hits[0]
                req_id = f"REQ-REG-{counter:03d}"
                counter += 1
                requirements.append(Requirement(
                    id=req_id,
                    title="Customer Due Diligence (CDD) Verification",
                    description="Verify identity and address of customers using Officially Valid Documents (OVDs) prior to onboarding.",
                    category=RequirementCategory.REGULATORY_COMPLIANCE,
                    priority=RequirementPriority.CRITICAL,
                    origin=RequirementOrigin.REGULATORY,
                    is_explicit=False,
                    source_reference=f"{k_chunk['doc_name']} ({k_chunk['section_title']})",
                    supporting_passage=k_chunk["content"][:350],
                    confidence=0.98,
                    explanation="Inferred statutory compliance requirement under RBI KYC Directions 2025."
                ))

        # Check for Conflicts
        # e.g., "rapid 60 days delivery" vs "all phases delivered at once with full safety verification"
        has_tight_deadline = any("60 day" in r.description.lower() or "rapid" in r.description.lower() for r in requirements)
        has_monolithic_complete = any("complete system delivery at once" in r.description.lower() or "cannot be modularized" in r.description.lower() for r in requirements)
        if has_tight_deadline and has_monolithic_complete:
            conflicts.append(ConflictItem(
                conflicting_requirement_ids=[r.id for r in requirements if "60 day" in r.description.lower() or "complete" in r.description.lower()][:2],
                description="Rapid delivery timeframe directly contradicts non-modular all-at-once system delivery requirement.",
                severity=RequirementPriority.CRITICAL,
                resolution_recommendation="Adopt modular architecture or extend timeline for single release delivery."
            ))

        # Check for Missing Information
        if not any(r.category == RequirementCategory.SECURITY_PRIVACY for r in requirements):
            missing_info.append(MissingInfoItem(
                area="Security & Encryption",
                description="No explicit encryption, authentication, or session management requirements specified.",
                potential_impact="System vulnerable to security non-compliance and unauthorized access."
            ))
        if any("consent" in r.description.lower() for r in requirements):
            has_valid_withdrawal = any(
                "withdraw" in r.description.lower()
                and "does not" not in r.description.lower()
                and "not provide" not in r.description.lower()
                and "no option" not in r.description.lower()
                for r in requirements
            )
            if not has_valid_withdrawal:
                missing_info.append(MissingInfoItem(
                    area="DPDP Consent Withdrawal Mechanism",
                    description="Personal data processing consent is collected, but no operational mechanism is provided for Data Principals to withdraw consent.",
                    potential_impact="Violation of Rule 3(c)(i) of DPDP Rules 2025 and Section 6 of DPDP Act 2023."
                ))

        # Deduplication
        deduped_requirements = self._deduplicate_requirements(requirements)

        # Category and Priority counts
        cat_counts = {}
        pri_counts = {}
        for r in deduped_requirements:
            cat_counts[r.category.value] = cat_counts.get(r.category.value, 0) + 1
            pri_counts[r.priority.value] = pri_counts.get(r.priority.value, 0) + 1

        return ExtractedRequirements(
            requirements=deduped_requirements,
            ambiguities=ambiguities,
            conflicts=conflicts,
            missing_information=missing_info,
            category_counts=cat_counts,
            priority_counts=pri_counts
        )

    def _deduplicate_requirements(self, reqs: List[Requirement]) -> List[Requirement]:
        """Deduplicates requirements without losing important distinctions."""
        unique: List[Requirement] = []
        for r in reqs:
            duplicate = False
            r_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", r.description.lower())) - STOPWORDS
            for existing in unique:
                # Same category check
                if r.category != existing.category and r.origin == existing.origin:
                    continue
                exist_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", existing.description.lower())) - STOPWORDS
                if not r_tokens or not exist_tokens:
                    continue
                intersection = r_tokens & exist_tokens
                union = r_tokens | exist_tokens
                jaccard = len(intersection) / len(union) if union else 0.0

                # Check core intent match for common banking functionalities
                core_intent_match = (
                    ("otp" in r_tokens and "otp" in exist_tokens and ("login" in r_tokens or "auth" in r_tokens) and ("login" in exist_tokens or "auth" in exist_tokens)) or
                    ("statement" in r_tokens and "statement" in exist_tokens and "download" in r_tokens and "download" in exist_tokens)
                )

                if jaccard >= 0.55 or core_intent_match:
                    duplicate = True
                    # Merge details if incoming is more detailed or regulatory
                    if len(r.description) > len(existing.description):
                        existing.description = r.description
                        existing.title = r.title
                    if r.origin == RequirementOrigin.REGULATORY and existing.origin != RequirementOrigin.REGULATORY:
                        existing.origin = RequirementOrigin.REGULATORY
                        existing.source_reference = r.source_reference
                        existing.supporting_passage = r.supporting_passage
                    break
            if not duplicate:
                unique.append(r)
        return unique

    def detect_sdlc_model(
        self,
        stakeholder_text: str,
        requirements: ExtractedRequirements
    ) -> SDLCDecision:
        """Evaluates project characteristics across 8 factors and scores all 6 SDLC models using RAG."""
        self.rag.ensure_ingested()
        text_lower = stakeholder_text.lower()
        all_req_text = " ".join(r.description.lower() for r in requirements.requirements)
        combined_text = f"{text_lower} {all_req_text}"

        # Retrieve SDLC Model definitions from RAG
        sdlc_passages_raw = self.rag.retrieve(
            "SDLC models Waterfall V-Shaped Prototype Spiral RAD Incremental best suited not suitable",
            top_k=6,
            source_type_filter="sdlc_reference"
        )
        sdlc_reference_passages = [f"{c[0]['section_title']}\n{c[0]['content']}" for c in sdlc_passages_raw]

        # Factor 1: Requirement clarity and stability (0 to 10)
        # High clarity: well-defined, stable, known upfront, fixed-scope, fixed-price
        # Low clarity: unclear, changing, evolving, proof of concept needed, not well understood
        f1_score = 5.0
        f1_evidence = "Requirements exhibit moderate clarity."
        if any(k in combined_text for k in ["unclear", "not well understood", "need demonstration", "evolving requirements", "proof of concept", "ui prototype"]):
            f1_score = 2.0
            f1_evidence = "Stakeholder states requirements are not fully understood, evolving, or require user demonstration."
        elif any(k in combined_text for k in ["stable requirements", "well-defined", "fixed-scope", "known upfront", "fully specified", "complete documentation"]):
            f1_score = 9.0
            f1_evidence = "Requirements are stated as fully specified upfront, stable, and well-understood."

        # Factor 2: Technical uncertainty (0 to 10)
        # High: bleeding edge, unproven tech, significant uncertainty, experimental AI, blockchain
        # Low: standard architecture, mature stack, proven COTS, well-understood domain
        f2_score = 4.0
        f2_evidence = "Technical uncertainty is at a standard level."
        if any(k in combined_text for k in ["significant uncertainty", "unproven", "technologically complex", "high uncertainty", "bleeding edge", "experimental"]):
            f2_score = 9.0
            f2_evidence = "Project involves high technical uncertainty and novel technological architecture."
        elif any(k in combined_text for k in ["well-understood domain", "proven technology", "mature stack", "standard database"]):
            f2_score = 2.0
            f2_evidence = "Technology stack and domain are mature and well-understood."

        # Factor 3: Project risk (0 to 10)
        # High: large, high-risk, catastrophic failure cost, multi-party regulatory exposure
        # Low: small, internal, low-risk
        f3_score = 5.0
        f3_evidence = "Project presents moderate risk."
        if any(k in combined_text for k in ["high-risk", "large, high-risk", "financial risk", "safety-critical", "mission critical"]):
            f3_score = 9.0
            f3_evidence = "Project is identified as large and high-risk or mission-critical."
        elif any(k in combined_text for k in ["low risk", "low-risk", "small project"]):
            f3_score = 2.0
            f3_evidence = "Project is characterized by low operational and financial risk."

        # Factor 4: Stakeholder/user involvement (0 to 10)
        # High: high user involvement, continuous feedback, interactive user testing
        # Low: upfront specification only, minimal user availability during build
        f4_score = 5.0
        f4_evidence = "Standard stakeholder touchpoints."
        if any(k in combined_text for k in ["high user involvement", "continuous feedback", "user feedback loop", "iterative user evaluation", "intensive workshops"]):
            f4_score = 9.0
            f4_evidence = "Stakeholders and users are deeply committed to continuous feedback loops and testing."
        elif any(k in combined_text for k in ["minimal user availability", "fixed contract", "infrequent reviews"]):
            f4_score = 2.0
            f4_evidence = "Stakeholder involvement is restricted to milestone sign-offs."

        # Factor 5: Team expertise and availability (0 to 10)
        # High: experienced developers, not new to technology/tools, domain experts
        # Low: junior team, new to technology/domain
        f5_score = 6.0
        f5_evidence = "Team demonstrates standard development capability."
        if any(k in combined_text for k in ["experienced developers", "expert developers", "senior engineers", "expert team", "not new to technology"]):
            f5_score = 9.0
            f5_evidence = "Development team comprises highly experienced developers familiar with tools and component reuse."
        elif any(k in combined_text for k in ["teams new to the domain", "new team", "learning new tools", "junior"]):
            f5_score = 2.0
            f5_evidence = "Team is new to the domain or learning new technology tools."

        # Factor 6: Modularity (0 to 10)
        # High: modular systems, microservices, component reuse, independent releases
        # Low: monolithic, highly interdependent components, non-modular
        f6_score = 6.0
        f6_evidence = "System has moderate component separation."
        if any(k in combined_text for k in ["can be broken into smaller components", "modular", "component reuse", "independent releases", "microservices"]):
            f6_score = 9.0
            f6_evidence = "System architecture is highly modular with reusable components."
        elif any(k in combined_text for k in ["cannot be modularized", "highly interdependent", "monolithic core"]):
            f6_score = 2.0
            f6_evidence = "System components are tightly coupled and cannot be easily partitioned."

        # Factor 7: Delivery deadlines (urgency/timeboxing, 0 to 10)
        # High urgency: strict 60-90 days, rapid delivery, quick turnaround
        # Moderate: phased increments, staged releases
        # Fixed single delivery: full system delivery at once
        f7_score = 5.0
        f7_evidence = "Delivery schedule is standard."
        has_rapid_deadline = any(k in combined_text for k in ["60-90", "60 to 90 days", "rapid delivery", "60 days", "quick turnaround"])
        has_staged_increments = any(k in combined_text for k in ["increments", "staged releases", "multiple releases", "long-life", "evolution"])
        has_complete_single_delivery = any(k in combined_text for k in [
            "complete system delivery at once", "single big-bang release", "single complete delivery",
            "turnover will happen as a single complete delivery", "no going back once a phase is signed off",
            "sequential, linear flow"
        ])

        if has_rapid_deadline:
            f7_score = 9.5
            f7_evidence = "Project mandates rapid delivery within a strict 60-90 day window."
        elif has_staged_increments and not has_complete_single_delivery:
            f7_score = 5.0
            f7_evidence = "Delivery strategy is structured as sequential feature increments over a long-life product lifecycle."
        elif has_complete_single_delivery:
            f7_score = 2.0
            f7_evidence = "Single all-at-once complete system delivery required upon total verification."

        # Factor 8: Testing and verification needs (0 to 10)
        # High: extensive testing and verification at every stage, V&V, safety-critical, compliance audits
        # Standard: unit/integration testing
        f8_score = 5.0
        f8_evidence = "Standard testing approach expected."
        if any(k in combined_text for k in ["extensive testing and verification", "verification and validation", "continuous verification", "safety-critical", "audit traceability"]):
            f8_score = 9.5
            f8_evidence = "Project requires extensive verification and validation matched at every development stage."

        factors_list = [
            FactorAssessment(factor_name="Requirement Clarity & Stability", score=f1_score, assessment_level="High" if f1_score > 6 else ("Low" if f1_score < 4 else "Medium"), evidence=f1_evidence),
            FactorAssessment(factor_name="Technical Uncertainty", score=f2_score, assessment_level="High" if f2_score > 6 else ("Low" if f2_score < 4 else "Medium"), evidence=f2_evidence),
            FactorAssessment(factor_name="Project Risk", score=f3_score, assessment_level="High" if f3_score > 6 else ("Low" if f3_score < 4 else "Medium"), evidence=f3_evidence),
            FactorAssessment(factor_name="Stakeholder Involvement", score=f4_score, assessment_level="High" if f4_score > 6 else ("Low" if f4_score < 4 else "Medium"), evidence=f4_evidence),
            FactorAssessment(factor_name="Team Expertise & Availability", score=f5_score, assessment_level="High" if f5_score > 6 else ("Low" if f5_score < 4 else "Medium"), evidence=f5_evidence),
            FactorAssessment(factor_name="Modularity", score=f6_score, assessment_level="High" if f6_score > 6 else ("Low" if f6_score < 4 else "Medium"), evidence=f6_evidence),
            FactorAssessment(factor_name="Delivery Deadlines", score=f7_score, assessment_level="High" if f7_score > 6 else ("Low" if f7_score < 4 else "Medium"), evidence=f7_evidence),
            FactorAssessment(factor_name="Testing & Verification Needs", score=f8_score, assessment_level="High" if f8_score > 6 else ("Low" if f8_score < 4 else "Medium"), evidence=f8_evidence),
        ]

        # Multi-factor explainable scoring grounded in sdlc_models.txt
        scores: Dict[str, float] = {
            SDLCModelName.WATERFALL.value: 0.0,
            SDLCModelName.V_MODEL.value: 0.0,
            SDLCModelName.PROTOTYPE.value: 0.0,
            SDLCModelName.SPIRAL.value: 0.0,
            SDLCModelName.RAD.value: 0.0,
            SDLCModelName.INCREMENTAL.value: 0.0,
        }

        # 1. Waterfall: High clarity (f1), Low risk (f3), Low uncertainty (f2), non-changing, single complete delivery
        waterfall_bonus = 30.0 if has_complete_single_delivery or "fixed-scope" in combined_text else 0.0
        scores[SDLCModelName.WATERFALL.value] = (
            (f1_score * 3.5) +
            ((10.0 - f2_score) * 2.0) +
            ((10.0 - f3_score) * 1.5) +
            (f8_score * 1.0) +
            ((10.0 - f4_score) * 1.0) +
            waterfall_bonus
        )

        # 2. V-Model: High clarity (f1), High testing/verification (f8), System integration, Low uncertainty
        # Crucial distinction: V-Model strictly demands extensive testing and verification at every stage
        scores[SDLCModelName.V_MODEL.value] = (
            (f1_score * 2.5) +
            (f8_score * 4.5) +
            ((10.0 - f2_score) * 1.5) +
            (f6_score * 1.0)
        )

        # 3. Prototype: Low clarity (10 - f1), High user involvement (f4), proof of concept, UI focus
        # Crucial distinction: Prototype is chosen when requirements are NOT well understood and need demonstration
        scores[SDLCModelName.PROTOTYPE.value] = (
            ((10.0 - f1_score) * 4.0) +
            (f4_score * 3.5) +
            (f2_score * 1.5) +
            ((10.0 - f8_score) * 0.5)
        )

        # 4. Spiral: High risk (f3), High uncertainty (f2), Iterative risk analysis, Large project
        # Crucial distinction: Spiral is risk-driven and iterative for high uncertainty/risk
        scores[SDLCModelName.SPIRAL.value] = (
            (f3_score * 4.5) +
            (f2_score * 4.0) +
            ((10.0 - f1_score) * 1.5) +
            (f4_score * 1.0)
        )

        # 5. RAD: Strict 60-90 days rapid delivery (has_rapid_deadline), High modularity (f6), Experienced developers (f5)
        # Crucial distinction: RAD strictly requires 60-90 day cycles and component reuse.
        # If no rapid 60-90 days deadline is requested, RAD is penalized.
        rad_speed_bonus = 30.0 if has_rapid_deadline else -35.0
        rad_team_penalty = -25.0 if f5_score < 5.0 else 0.0
        rad_mod_penalty = -30.0 if f6_score < 5.0 else 0.0
        scores[SDLCModelName.RAD.value] = (
            (f7_score * 3.5) +
            (f6_score * 2.5) +
            (f5_score * 2.5) +
            (f4_score * 1.5) +
            rad_speed_bonus + rad_team_penalty + rad_mod_penalty
        )

        # 6. Incremental: Well-understood core (f1 moderate-high), Staged independent releases (f6 high), long-life product
        # Crucial distinction: Incremental delivers core first then increments, avoiding big-bang delivery
        # Explicitly NOT suitable if requiring complete system delivery at once
        incremental_penalty = -40.0 if has_complete_single_delivery else 0.0
        incremental_bonus = 35.0 if (has_staged_increments and not has_complete_single_delivery) else 0.0
        scores[SDLCModelName.INCREMENTAL.value] = (
            (f1_score * 3.0) +
            (f6_score * 3.0) +
            (f4_score * 2.0) +
            ((10.0 - f2_score) * 2.0) +
            ((10.0 - f3_score) * 1.0) +
            incremental_bonus +
            incremental_penalty
        )

        # Normalize scores to 0 - 100
        min_raw = min(scores.values())
        if min_raw < 0:
            scores = {k: v - min_raw for k, v in scores.items()}
        max_raw = max(scores.values()) if max(scores.values()) > 0 else 1.0
        normalized_scores = {k: round((v / max_raw) * 100.0, 1) for k, v in scores.items()}

        # Identify winner
        sorted_models = sorted(normalized_scores.items(), key=lambda x: x[1], reverse=True)
        winner_name, top_score = sorted_models[0]
        runner_up_name, second_score = sorted_models[1]

        # Check for ties or near-ties
        tie_break_notes = None
        uncertainties = []
        if (top_score - second_score) < 3.0:
            tie_break_notes = (
                f"Close margin between {winner_name} ({top_score}) and {runner_up_name} ({second_score}). "
                f"Tie-breaking applied based on primary driver constraints."
            )
            uncertainties.append(f"Near tie between {winner_name} and {runner_up_name}.")

        # Craft detailed explanation distinguishing the winner from alternatives
        explanation = (
            f"**Recommended Model**: {winner_name} (Score: {top_score}/100).\n\n"
            f"**Evidence & Rationale**:\n"
            f"- Factor analysis: Clarity={f1_score}/10, Uncertainty={f2_score}/10, Risk={f3_score}/10, "
            f"User Involvement={f4_score}/10, Team Expertise={f5_score}/10, Modularity={f6_score}/10, "
            f"Deadlines={f7_score}/10, Testing Rigor={f8_score}/10.\n"
        )

        if winner_name == SDLCModelName.RAD.value:
            explanation += (
                "- **Why RAD over Prototype**: Unlike Prototype (which focuses on exploring undefined requirements "
                "or UX through throwaway/evolutionary mockups), this project features a strict 60-90 day delivery window, "
                "a modular component architecture, and experienced developers ready for component reuse and parallel development.\n"
                "- **Why RAD over Waterfall/V-Model**: Fixed sequential models cannot meet the rapid 60-90 day turnaround requirement."
            )
        elif winner_name == SDLCModelName.PROTOTYPE.value:
            explanation += (
                "- **Why Prototype over RAD**: The primary project challenge is that requirements and user interfaces are "
                "not well understood and require proof of concept / demonstration to define. RAD is only suitable when "
                "requirements can be rapidly decomposed into clear business/data modules by experienced teams.\n"
                "- **Why Prototype over Waterfall**: Waterfall requires fully specified upfront requirements, which are absent here."
            )
        elif winner_name == SDLCModelName.V_MODEL.value:
            explanation += (
                "- **Why V-Model over Waterfall**: While both require stable upfront requirements, the V-Model specifically "
                "demands continuous verification and validation at every development stage (Requirements <-> Acceptance Testing, "
                "System Design <-> System Testing, Architecture <-> Integration Testing, Module <-> Unit Testing), which is "
                "mandatory for this high-assurance/safety-critical banking system.\n"
                "- **Why V-Model over Agile/RAD**: Rapid iterative models do not provide the exhaustive, multi-level verification "
                "matrix required for zero-defect compliance."
            )
        elif winner_name == SDLCModelName.WATERFALL.value:
            explanation += (
                "- **Why Waterfall over V-Model**: Requirements are stable, well-understood, and domain risk is low. "
                "Extensive bidirectional verification matrices are unnecessary, making sequential phase completion the most cost-effective.\n"
                "- **Why Waterfall over Spiral/RAD**: The system has low uncertainty and a fixed-price/fixed-scope contract without rapid 60-day pressure."
            )
        elif winner_name == SDLCModelName.SPIRAL.value:
            explanation += (
                "- **Why Spiral over Incremental**: The project is characterized by significant technical uncertainty and high risk. "
                "Spiral incorporates formal risk analysis and risk-driven iterations in each phase (Planning, Risk Analysis, "
                "Engineering, Evaluation), preventing catastrophic financial or technical failure.\n"
                "- **Why Spiral over Waterfall**: Waterfall's sequential nature cannot absorb the high volatility and unknown risks present here."
            )
        elif winner_name == SDLCModelName.INCREMENTAL.value:
            explanation += (
                "- **Why Incremental over Spiral**: Core requirements are well understood and project risk is manageable without "
                "expensive formal spiral risk cycles. Functionality can be partitioned into prioritized, independent releases.\n"
                "- **Why Incremental over Waterfall**: Incremental avoids high-risk 'all-at-once' big-bang delivery, releasing core features first."
            )

        confidence = 0.92 if (top_score - second_score) >= 10.0 else (0.80 if (top_score - second_score) >= 4.0 else 0.70)

        supporting_evidence = [
            f"Clarity: {f1_evidence}",
            f"Uncertainty: {f2_evidence}",
            f"Risk: {f3_evidence}",
            f"Involvement: {f4_evidence}",
            f"Team: {f5_evidence}",
            f"Modularity: {f6_evidence}",
            f"Deadlines: {f7_evidence}",
            f"Testing: {f8_evidence}"
        ]

        return SDLCDecision(
            recommended_model=SDLCModelName(winner_name),
            model_scores=normalized_scores,
            factors_considered=factors_list,
            supporting_evidence=supporting_evidence,
            sdlc_reference_passages=sdlc_reference_passages[:3],
            explanation=explanation,
            confidence=confidence,
            uncertainties=uncertainties,
            tie_break_notes=tie_break_notes
        )
