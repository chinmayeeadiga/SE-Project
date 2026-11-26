import hashlib
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from src.rag.document_loader import LoadedDocument


@dataclass
class DocumentChunk:
    chunk_id: str
    doc_id: str
    doc_name: str
    source_type: str
    section_title: str
    clause_id: Optional[str]
    content: str
    char_length: int
    sha256: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class LogicalChunker:
    """Section-aware logical chunker that preserves headings, clauses, and lists."""

    # Heading detection patterns across regulatory and SDLC documents
    HEADING_PATTERNS = [
        # e.g., "Waterfall Model:", "RAD (Rapid Application Development) Model:"
        re.compile(r"^([A-Z][A-Za-z0-9\s\(\)\/\-]+\s+Model:)\s*$", re.MULTILINE),
        # e.g., "Chapter I - Preliminary", "CHAPTER II OBLIGATIONS OF DATA FIDUCIARY"
        re.compile(r"^((?:Chapter|CHAPTER)\s+[IVXLCDM0-9]+(?:\s*[\–\:\-]\s*[^\n]+)?)\s*$", re.MULTILINE),
        # e.g., "Section 10.", "SECTIONS", "3. Notice given by Data Fiduciary"
        re.compile(r"^(\d+\.\s+[A-Z][^\n]{3,60})\s*$", re.MULTILINE),
        # e.g., "A. Short Title and Commencement", "C. Application Security Life Cycle"
        re.compile(r"^([A-Z]\.\s+[A-Z][^\n]{3,60})\s*$", re.MULTILINE),
        # e.g., "V1 Architecture, Design and Threat Modeling", "V2 Authentication"
        re.compile(r"^(V\d+\s+[A-Z][^\n]{3,60})\s*$", re.MULTILINE),
        # e.g., "GOVERN (GV)", "IDENTIFY (ID)"
        re.compile(r"^([A-Z]{2,}\s*\([A-Z0-9\.\-]+\))\s*$", re.MULTILINE),
        # e.g., CERT-In directions "(i) All service providers...", "(ii) ...", "(vi) ..."
        re.compile(r"^(\([ivx0-9]+\)\s+[A-Z][^\n]{10,80})\s*$", re.MULTILINE),
    ]

    def __init__(
        self,
        max_chunk_char_len: int = 1800,
        overlap_char_len: int = 250,
        min_chunk_char_len: int = 120
    ):
        self.max_chunk_char_len = max_chunk_char_len
        self.overlap_char_len = overlap_char_len
        self.min_chunk_char_len = min_chunk_char_len

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def identify_sections(self, text: str) -> List[Dict[str, Any]]:
        """Identifies structural sections and their positions in the document."""
        heading_matches = []

        for pattern in self.HEADING_PATTERNS:
            for match in pattern.finditer(text):
                heading_matches.append((match.start(), match.end(), match.group(1).strip()))

        # Sort matches by character position
        heading_matches.sort(key=lambda x: x[0])

        # Deduplicate overlapping matches
        filtered_matches = []
        last_end = -1
        for start, end, title in heading_matches:
            if start >= last_end:
                filtered_matches.append((start, end, title))
                last_end = end

        if not filtered_matches:
            return [{"title": "General", "content": text, "start": 0}]

        sections = []
        # Handle preamble before first heading
        if filtered_matches[0][0] > 0:
            preamble = text[:filtered_matches[0][0]].strip()
            if preamble:
                sections.append({"title": "Introduction/Preamble", "content": preamble, "start": 0})

        for i, (start, end, title) in enumerate(filtered_matches):
            next_start = filtered_matches[i + 1][0] if i + 1 < len(filtered_matches) else len(text)
            section_content = text[end:next_start].strip()
            sections.append({
                "title": title,
                "content": section_content,
                "start": start
            })

        return sections

    def _split_oversized_section(self, title: str, content: str) -> List[str]:
        """Splits an oversized section at paragraph or clause boundaries with controlled overlap."""
        # Split on paragraph boundaries (double newline)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]

        if not paragraphs:
            return [f"[{title}]\n{content}"]

        chunks_text = []
        current_chunk_paragraphs = []
        current_length = 0

        for para in paragraphs:
            para_len = len(para)

            # If a single paragraph is itself gigantic, split on clause boundaries
            if para_len > self.max_chunk_char_len:
                if current_chunk_paragraphs:
                    combined = f"[{title}]\n" + "\n\n".join(current_chunk_paragraphs)
                    chunks_text.append(combined)
                    current_chunk_paragraphs = []
                    current_length = 0

                # Split on sentence/clause boundaries
                clauses = re.split(r"(?<=[.;])\s+", para)
                clause_buf = []
                clause_len = 0
                for clause in clauses:
                    if clause_len + len(clause) > self.max_chunk_char_len and clause_buf:
                        chunks_text.append(f"[{title}]\n" + " ".join(clause_buf))
                        # Retain last clause for overlap
                        clause_buf = clause_buf[-1:]
                        clause_len = sum(len(c) for c in clause_buf)
                    clause_buf.append(clause)
                    clause_len += len(clause)
                if clause_buf:
                    chunks_text.append(f"[{title}]\n" + " ".join(clause_buf))
                continue

            if current_length + para_len > self.max_chunk_char_len and current_chunk_paragraphs:
                combined = f"[{title}]\n" + "\n\n".join(current_chunk_paragraphs)
                chunks_text.append(combined)
                # Overlap: keep the last paragraph if small enough
                if len(current_chunk_paragraphs[-1]) <= self.overlap_char_len:
                    current_chunk_paragraphs = [current_chunk_paragraphs[-1]]
                    current_length = len(current_chunk_paragraphs[0])
                else:
                    current_chunk_paragraphs = []
                    current_length = 0

            current_chunk_paragraphs.append(para)
            current_length += para_len

        if current_chunk_paragraphs:
            combined = f"[{title}]\n" + "\n\n".join(current_chunk_paragraphs)
            chunks_text.append(combined)

        return chunks_text

    def chunk_document(self, doc: LoadedDocument) -> List[DocumentChunk]:
        """Segments a loaded document into logical, section-aware chunks."""
        sections = self.identify_sections(doc.cleaned_text)
        chunks: List[DocumentChunk] = []

        chunk_counter = 1

        for sec in sections:
            title = sec["title"]
            content = sec["content"]

            full_section_text = f"[{title}]\n{content}".strip() if content else f"[{title}]"

            if len(full_section_text) <= self.max_chunk_char_len:
                # Keep whole section together
                if len(full_section_text) >= self.min_chunk_char_len or doc.source_type == "sdlc_reference":
                    chunk_id = f"{doc.doc_id}_{chunk_counter:04d}"
                    clause_match = re.search(r"\b(?:Section|Rule|Clause|Direction|\()(\w+)", title)
                    clause_id = clause_match.group(1) if clause_match else None

                    chunks.append(DocumentChunk(
                        chunk_id=chunk_id,
                        doc_id=doc.doc_id,
                        doc_name=doc.filename,
                        source_type=doc.source_type,
                        section_title=title,
                        clause_id=clause_id,
                        content=full_section_text,
                        char_length=len(full_section_text),
                        sha256=self.compute_hash(full_section_text),
                        metadata={
                            "doc_id": doc.doc_id,
                            "doc_name": doc.filename,
                            "source_type": doc.source_type,
                            "section_title": title,
                            "clause_id": clause_id
                        }
                    ))
                    chunk_counter += 1
            else:
                # Section is oversized, split logically at paragraph boundaries
                sub_chunks = self._split_oversized_section(title, content)
                for sub in sub_chunks:
                    if len(sub.strip()) < self.min_chunk_char_len and doc.source_type != "sdlc_reference":
                        continue
                    chunk_id = f"{doc.doc_id}_{chunk_counter:04d}"
                    clause_match = re.search(r"\b(?:Section|Rule|Clause|Direction|\()(\w+)", title)
                    clause_id = clause_match.group(1) if clause_match else None

                    chunks.append(DocumentChunk(
                        chunk_id=chunk_id,
                        doc_id=doc.doc_id,
                        doc_name=doc.filename,
                        source_type=doc.source_type,
                        section_title=title,
                        clause_id=clause_id,
                        content=sub,
                        char_length=len(sub),
                        sha256=self.compute_hash(sub),
                        metadata={
                            "doc_id": doc.doc_id,
                            "doc_name": doc.filename,
                            "source_type": doc.source_type,
                            "section_title": title,
                            "clause_id": clause_id
                        }
                    ))
                    chunk_counter += 1

        return chunks
