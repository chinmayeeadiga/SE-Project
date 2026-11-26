import pytest
from src.rag.evaluation import RetrievalEvaluator, REGULATORY_RAG_EVAL_BENCHMARK


def test_passage_answerability_evaluation(shared_rag_pipeline):
    evaluator = RetrievalEvaluator()
    results = evaluator.evaluate_pipeline(shared_rag_pipeline, REGULATORY_RAG_EVAL_BENCHMARK)

    assert results["test_cases_count"] >= 5
    # Hit Rate @ K must be at least 80%
    assert results["hit_rate_at_k"] >= 0.80, f"Hit rate @ K too low: {results['hit_rate_at_k']}"
    # MRR must be high
    assert results["mrr"] >= 0.50, f"MRR too low: {results['mrr']}"
    # Average best passage answerability score must be >= 0.60
    assert results["avg_best_answerability"] >= 0.60, f"Answerability score too low: {results['avg_best_answerability']}"

    # Verify each benchmark case result
    for case_res in results["case_results"]:
        assert case_res["first_hit_rank"] is not None, f"Query failed to retrieve target: {case_res['query']}"
