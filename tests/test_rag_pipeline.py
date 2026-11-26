import pytest
from pathlib import Path
from src.config import settings
from src.rag.document_loader import DocumentLoader
from src.rag.chunker import LogicalChunker
from src.rag.bm25 import BM25Retriever
from src.rag.pipeline import RAGPipeline


def test_document_loader_loads_all_docs():
    loader = DocumentLoader(settings.RAG_DOCS_DIR, settings.SDLC_DOCS_DIR)
    docs = loader.load_all_documents()
    assert len(docs) == 8, f"Expected 8 documents, loaded {len(docs)}"

    doc_ids = {d.doc_id for d in docs}
    expected_ids = {
        "cert_in_directions_2022",
        "dpdp_act_2023",
        "dpdp_rules_2025",
        "nist_csf_2_0",
        "owasp_asvs_5_0_0",
        "rbi_digital_payment_security_directions_2026",
        "rbi_kyc_directions_2025",
        "sdlc_models"
    }
    assert expected_ids.issubset(doc_ids), f"Missing docs: {expected_ids - doc_ids}"


def test_logical_chunker_preserves_headings_and_structure():
    loader = DocumentLoader(settings.RAG_DOCS_DIR, settings.SDLC_DOCS_DIR)
    sdlc_doc = loader.load_document(settings.SDLC_DOCS_DIR / "sdlc_models.txt", "sdlc_reference")
    assert sdlc_doc is not None

    chunker = LogicalChunker()
    chunks = chunker.chunk_document(sdlc_doc)
    # sdlc_models has 6 models
    assert len(chunks) == 6
    chunk_titles = [c.section_title for c in chunks]
    assert any("Waterfall" in t for t in chunk_titles)
    assert any("V-Shaped" in t for t in chunk_titles)
    assert any("Prototype" in t for t in chunk_titles)
    assert any("Spiral" in t for t in chunk_titles)
    assert any("RAD" in t for t in chunk_titles)
    assert any("Incremental" in t for t in chunk_titles)

    # Every chunk must have non-empty content and valid sha256
    for c in chunks:
        assert c.char_length > 100
        assert len(c.sha256) == 64
        assert c.source_type == "sdlc_reference"


def test_bm25_retrieval_and_persistence(tmp_path):
    loader = DocumentLoader(settings.RAG_DOCS_DIR, settings.SDLC_DOCS_DIR)
    docs = loader.load_all_documents()
    chunker = LogicalChunker()
    chunks = []
    for d in docs:
        chunks.extend(chunker.chunk_document(d))

    retriever = BM25Retriever()
    retriever.add_chunks(chunks)

    # Test keyword search
    hits = retriever.search("6 hours cyber security incident report", top_k=3)
    assert len(hits) > 0
    top_chunk, score = hits[0]
    assert score > 0.0
    assert "cert_in" in top_chunk["doc_id"] or "incident" in top_chunk["content"].lower()

    # Test persistence
    idx_path = tmp_path / "bm25.json"
    retriever.save(idx_path)
    assert idx_path.exists()

    loaded_retriever = BM25Retriever()
    loaded_retriever.load(idx_path)
    assert loaded_retriever.doc_count == retriever.doc_count

    loaded_hits = loaded_retriever.search("6 hours cyber security incident report", top_k=3)
    assert len(loaded_hits) == len(hits)
    assert loaded_hits[0][0]["chunk_id"] == hits[0][0]["chunk_id"]


def test_reciprocal_rank_fusion():
    dense_results = [
        ({"chunk_id": "doc1", "title": "A"}, 0.9),
        ({"chunk_id": "doc2", "title": "B"}, 0.8),
        ({"chunk_id": "doc3", "title": "C"}, 0.7),
    ]
    bm25_results = [
        ({"chunk_id": "doc2", "title": "B"}, 15.0),
        ({"chunk_id": "doc1", "title": "A"}, 12.0),
        ({"chunk_id": "doc4", "title": "D"}, 9.0),
    ]

    fused = RAGPipeline.reciprocal_rank_fusion(dense_results, bm25_results, k=60)
    assert len(fused) == 4
    # doc1 and doc2 appeared in both, so they must be at the top
    top_ids = [c["chunk_id"] for c, _ in fused[:2]]
    assert "doc1" in top_ids and "doc2" in top_ids


def test_real_regulatory_retrieval(shared_rag_pipeline):
    # Query 1: CERT-In 6-hour incident reporting
    cert_hits = shared_rag_pipeline.retrieve("mandatory 6 hours reporting of cyber security incidents", top_k=3)
    assert len(cert_hits) > 0
    assert any("cert_in" in c[0]["doc_id"] for c in cert_hits)

    # Query 2: RBI KYC Officially Valid Document
    kyc_hits = shared_rag_pipeline.retrieve("Officially Valid Document OVD customer identification", top_k=3)
    assert len(kyc_hits) > 0
    assert any("rbi_kyc" in c[0]["doc_id"] for c in kyc_hits)

    # Query 3: RBI Digital Payment Security 2FA
    payment_hits = shared_rag_pipeline.retrieve("Two factor authentication and mobile application security", top_k=3)
    assert len(payment_hits) > 0
    assert any("digital_payment" in c[0]["doc_id"] for c in payment_hits)
