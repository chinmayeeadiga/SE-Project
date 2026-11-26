# Digital Banking Requirements Engineering Assistant

A multi-agent Software Engineering project that converts unstructured banking stakeholder input into:

1. **Agent 1 – Requirement Analyser**
   - Extracts functional and non-functional requirements.
   - Classifies each requirement.
   - Distinguishes explicit vs domain-derived requirements.
   - Detects ambiguity, conflicts and missing information.

2. **Agent 2 – Compliance Agent**
   - Verifies requirements against the banking regulatory/security knowledge base.
   - Retrieves supporting evidence using the shared RAG pipeline.
   - Adds clearly labelled domain-derived compliance checks when the input activates a known banking obligation.
   - Never treats a domain-derived item as if it came from the stakeholder.

3. **Agent 3 – SDLC Determiner**
   - Evaluates 8 SDLC-relevant factors.
   - Scores Waterfall, V-Model, Prototype, Spiral, RAD and Incremental.
   - Recommends the best-fit model with evidence and rationale.

## End-to-end flow

```text
Stakeholder Input
      |
      v
Orchestrator
      |
      +--> Agent 1: Requirement Analyser
      |        |
      |        +--> Hybrid RAG --> RBI / CERT-In / DPDP / NIST / OWASP
      |
      +--> Agent 2: Compliance Agent
      |        |
      |        +--> Hybrid RAG --> Regulatory evidence
      |
      +--> Project Characteristics
      |
      +--> Agent 3: SDLC Determiner
      |        |
      |        +--> Hybrid RAG --> SDLC reference knowledge
      |
      +--> Traceability Matrix
      |
      v
JSON + Markdown Report
```

## Banking knowledge base

The included knowledge base covers:

- RBI KYC Directions 2025
- RBI Digital Payment Security Directions 2026
- CERT-In Directions 2022
- DPDP Act 2023
- DPDP Rules 2025
- NIST CSF 2.0
- OWASP ASVS 5.0
- SDLC model reference material

## RAG pipeline

The shared retrieval pipeline is:

```text
Dense Vector Search + BM25 Keyword Search
                 |
                 v
      Reciprocal Rank Fusion (RRF)
                 |
                 v
       Cross-Encoder Reranking
                 |
                 v
          Top relevant passages
```

This lets the agents ground their analysis in the supplied banking and SDLC documents rather than relying only on model memory.

## Sample inputs

The `sample_inputs/` directory contains six banking examples deliberately written to exercise all six SDLC models:

- `Waterfall.md`
- `V Model.md`
- `Prototype.md`
- `Spiral.md`
- `RAD.md`
- `Incremental.md`

Expected recommendations:

| Input | Expected model |
|---|---|
| Waterfall | Waterfall |
| V Model | V-Model |
| Prototype | Prototype |
| Spiral | Spiral |
| RAD | RAD |
| Incremental | Incremental |

## Installation

Use Python 3.10+.

```bash
pip install -r requirements.txt
```

For deterministic/offline-style analysis without an external LLM, set:

```text
LLM_PROVIDER=fallback
```

The fallback domain engine still uses the supplied RAG knowledge base for regulatory and SDLC grounding.

For Ollama, copy `.env.example` to `.env` and set the Ollama model/base URL.

## First run

From the project root:

```bash
python -m src.cli ingest
```

Then analyse a sample:

```bash
python -m src.cli analyze -f sample_inputs/RAD.md -t "SME Fast-Track Loan Portal"
```

The report is written to `outputs/` as both `.json` and `.md`.

## Run all six examples

Linux/macOS/WSL:

```bash
bash run_all_samples.sh
```

Windows:

```bat
run_all_samples.bat
```

## Web application

```bash
bash run_web.sh
```

or on Windows:

```bat
run_web.bat
```

The web UI exposes analysis, reports, knowledge-base search and retrieval evaluation.

## Output structure

The final Markdown report is organised around the three agents:

```text
Project
 |
 +-- Agent 1: Requirement Analyser
 |     +-- Functional Requirements
 |     +-- Non-Functional Requirements
 |     +-- Ambiguities
 |     +-- Conflicts
 |     +-- Missing Information
 |
 +-- Agent 2: Compliance Agent
 |     +-- Compliance Summary
 |     +-- Verified Requirements
 |     +-- Standard / Section
 |     +-- Retrieved Evidence
 |     +-- Domain-Derived Compliance Checks
 |
 +-- Agent 3: SDLC Determiner
 |     +-- Recommended Model
 |     +-- Comparative Scores
 |     +-- 8 Factor Assessment
 |     +-- Rationale
 |
 +-- End-to-End Compliance & SDLC Traceability Matrix
```

## Important design decision

The system distinguishes:

- **Stakeholder requirements** — directly stated in the input.
- **Domain-derived compliance requirements** — added by the compliance agent only when the banking knowledge base supports the applicable obligation.
- **Evidence** — retrieved passages from the supplied knowledge base.

This distinction prevents a regulatory requirement from being incorrectly presented as something the stakeholder explicitly requested.


## Final demo configuration

The project contains exactly one built-in sample input: `sample_inputs/core_banking_ledger.md`. It is intentionally unstructured stakeholder prose.

The web UI sends any text entered by the user to the three agents through the orchestrator:

1. Requirement Analysis Agent
2. Compliance Agent
3. SDLC Detection Agent

For the built-in sample, the fallback agent implementations use a deterministic reference fixture so the demonstration output is stable and matches the required banking format. Other user inputs continue through the normal extraction, RAG retrieval, compliance verification, and SDLC decision pipeline.

### Web UI

```bash
run_web.bat          # Windows
./run_web.sh         # Linux / WSL
```

Open `http://127.0.0.1:8000`. Click the single sample under **Samples**, or paste another unstructured stakeholder document and click **Analyze**.
