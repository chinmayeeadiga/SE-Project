import re
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass


@dataclass
class RetrievalTestCase:
    query: str
    target_doc_id: str
    required_concepts: List[str]
    description: str


# Realistic test cases grounded in the actual documents
REGULATORY_RAG_EVAL_BENCHMARK: List[RetrievalTestCase] = [
    RetrievalTestCase(
        query="What is the mandatory timeline for reporting cyber security incidents to CERT-In?",
        target_doc_id="cert_in_directions_2022",
        required_concepts=["6 hours", "report|reporting", "incident"],
        description="CERT-In 6-hour mandatory cyber incident reporting requirement"
    ),
    RetrievalTestCase(
        query="What are the customer due diligence CDD measures for individuals under RBI KYC Directions?",
        target_doc_id="rbi_kyc_directions_2025",
        required_concepts=["CDD|due diligence|KYC", "customer|individual", "bank|account"],
        description="RBI KYC individual customer due diligence and identification requirements"
    ),
    RetrievalTestCase(
        query="What are the requirements for mobile payment application security and device binding under RBI Digital Payment Security Directions?",
        target_doc_id="rbi_digital_payment_security_directions_2026",
        required_concepts=["Mobile Payments|mobile", "device|binding", "application|security"],
        description="RBI Digital Payment Security controls for mobile payment apps"
    ),
    RetrievalTestCase(
        query="What notice must a Data Fiduciary give to a Data Principal before seeking consent under DPDP Rules?",
        target_doc_id="dpdp_rules_2025",
        required_concepts=["Notice", "Data Fiduciary|Fiduciary", "Data Principal|Principal", "consent"],
        description="DPDP Rules notice and itemised personal data processing requirements"
    ),
    RetrievalTestCase(
        query="When is RAD model best suited and why is it not suitable for high performance systems?",
        target_doc_id="sdlc_models",
        required_concepts=["RAD|Rapid Application Development", "60-90|rapid", "modular|components"],
        description="SDLC RAD model characteristics, timeline, and limitations"
    ),
    RetrievalTestCase(
        query="What are the verification and validation phases in the V-Shaped model?",
        target_doc_id="sdlc_models",
        required_concepts=["V-Shaped|V-Model", "Verification", "Validation", "Acceptance Testing|testing"],
        description="SDLC V-Model verification vs validation phase mapping"
    ),
]


class RetrievalEvaluator:
    """Evaluates whether retrieved passages actually answer specific queries."""

    @staticmethod
    def evaluate_passage_answerability(
        passage_text: str,
        required_concepts: List[str]
    ) -> float:
        """Evaluates whether the retrieved passage contains the necessary answer concepts."""
        if not passage_text or not required_concepts:
            return 0.0

        lower_passage = passage_text.lower()
        matched = 0
        for concept_group in required_concepts:
            options = [opt.strip().lower() for opt in concept_group.split("|")]
            found = False
            for opt in options:
                pattern = re.compile(rf"\b{re.escape(opt)}\b")
                if pattern.search(lower_passage) or opt in lower_passage:
                    found = True
                    break
            if found:
                matched += 1

        return matched / len(required_concepts)

    def evaluate_pipeline(self, pipeline: Any, benchmark: Optional[List[RetrievalTestCase]] = None) -> Dict[str, Any]:
        """Runs the benchmark against the RAG pipeline and returns metrics."""
        cases = benchmark or REGULATORY_RAG_EVAL_BENCHMARK
        results = []
        hits_at_1 = 0
        hits_at_k = 0
        reciprocal_ranks = []
        total_answerability_top1 = 0.0
        total_answerability_best = 0.0

        for case in cases:
            retrieved = pipeline.retrieve(case.query, top_k=5)
            doc_hit_rank = None
            best_answerability = 0.0
            top1_answerability = 0.0

            for rank, (chunk, _) in enumerate(retrieved, start=1):
                ans_score = self.evaluate_passage_answerability(chunk["content"], case.required_concepts)
                if rank == 1:
                    top1_answerability = ans_score
                if ans_score > best_answerability:
                    best_answerability = ans_score

                # If from target document and at least 50% answerability
                if chunk["doc_id"] == case.target_doc_id and ans_score >= 0.5:
                    if doc_hit_rank is None:
                        doc_hit_rank = rank

            if doc_hit_rank == 1:
                hits_at_1 += 1
            if doc_hit_rank is not None:
                hits_at_k += 1
                reciprocal_ranks.append(1.0 / doc_hit_rank)
            else:
                reciprocal_ranks.append(0.0)

            total_answerability_top1 += top1_answerability
            total_answerability_best += best_answerability

            results.append({
                "query": case.query,
                "target_doc": case.target_doc_id,
                "first_hit_rank": doc_hit_rank,
                "top1_answerability": round(top1_answerability, 3),
                "best_answerability": round(best_answerability, 3),
                "passed": (doc_hit_rank is not None and best_answerability >= 0.5)
            })

        count = len(cases)
        mrr = sum(reciprocal_ranks) / count if count > 0 else 0.0
        hit_rate_at_1 = hits_at_1 / count if count > 0 else 0.0
        hit_rate_at_k = hits_at_k / count if count > 0 else 0.0
        avg_top1_answerability = total_answerability_top1 / count if count > 0 else 0.0
        avg_best_answerability = total_answerability_best / count if count > 0 else 0.0

        return {
            "test_cases_count": count,
            "hit_rate_at_1": round(hit_rate_at_1, 3),
            "hit_rate_at_k": round(hit_rate_at_k, 3),
            "mrr": round(mrr, 3),
            "avg_top1_answerability": round(avg_top1_answerability, 3),
            "avg_best_answerability": round(avg_best_answerability, 3),
            "case_results": results
        }
