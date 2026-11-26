import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any


@dataclass
class LoadedDocument:
    doc_id: str
    filename: str
    filepath: str
    source_type: str  # "regulatory" or "sdlc_reference"
    raw_text: str
    cleaned_text: str
    sha256: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class DocumentLoader:
    """Loads and cleans regulatory and SDLC documents while preserving headings, clauses, and lists."""

    # Patterns for front matter, repetitive headers/footers, and page numbers
    PAGE_NUMBER_PATTERN = re.compile(r"^\s*(?:Page\s+\d+\s+of\s+\d+|\d+\s*\|\s*Page|\.{3,}\s*\d+)\s*$", re.MULTILINE | re.IGNORECASE)
    REPEATED_HEADER_PATTERN = re.compile(r"^\s*(?:THE GAZETTE OF INDIA\s*:?\s*EXTRAORDINARY|REGD\.\s*No\.\s*[A-Z0-9\.\-]+)\s*$", re.MULTILINE | re.IGNORECASE)
    TOC_DOT_LINE_PATTERN = re.compile(r"^[A-Za-z0-9\s,\-\–\(\)]+\.{4,}\s*\d+\s*$", re.MULTILINE)

    def __init__(self, rag_docs_dir: Path, sdlc_docs_dir: Path):
        self.rag_docs_dir = Path(rag_docs_dir)
        self.sdlc_docs_dir = Path(sdlc_docs_dir)

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def clean_text(self, text: str, source_type: str) -> str:
        """Cleans text without removing substantive content or structural clauses."""
        lines = text.splitlines()
        cleaned_lines = []

        for line in lines:
            stripped = line.strip()

            # Skip standalone page numbers or gazette registration stamps
            if self.PAGE_NUMBER_PATTERN.match(stripped):
                continue
            if self.REPEATED_HEADER_PATTERN.match(stripped):
                continue

            # In regulatory documents, TOC lines with dot leaders like "... 21" can be kept if short, or cleaned
            # We preserve substantive headings
            cleaned_lines.append(line)

        cleaned_content = "\n".join(cleaned_lines)
        # Normalize excessive blank lines (3+ into 2)
        cleaned_content = re.sub(r"\n{3,}", "\n\n", cleaned_content)
        return cleaned_content.strip()

    def load_document(self, filepath: Path, source_type: str) -> Optional[LoadedDocument]:
        if not filepath.exists() or not filepath.is_file():
            return None

        # Read text with utf-8 fallback
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1") as f:
                raw_text = f.read()

        cleaned_text = self.clean_text(raw_text, source_type)
        sha256 = self.compute_hash(raw_text)

        doc_id = filepath.stem
        metadata = {
            "doc_id": doc_id,
            "filename": filepath.name,
            "filepath": str(filepath.resolve()),
            "source_type": source_type,
            "raw_length": len(raw_text),
            "cleaned_length": len(cleaned_text),
            "sha256": sha256
        }

        return LoadedDocument(
            doc_id=doc_id,
            filename=filepath.name,
            filepath=str(filepath.resolve()),
            source_type=source_type,
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            sha256=sha256,
            metadata=metadata
        )

    def load_all_documents(self) -> List[LoadedDocument]:
        """Loads all regulatory documents and SDLC reference documents."""
        documents: List[LoadedDocument] = []

        if self.rag_docs_dir.exists():
            for p in sorted(self.rag_docs_dir.glob("*.txt")):
                doc = self.load_document(p, source_type="regulatory")
                if doc:
                    documents.append(doc)

        if self.sdlc_docs_dir.exists():
            for p in sorted(self.sdlc_docs_dir.glob("*.txt")):
                doc = self.load_document(p, source_type="sdlc_reference")
                if doc:
                    documents.append(doc)

        return documents
