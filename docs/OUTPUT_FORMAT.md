# Final Report Format

Every analysis produces a Markdown and JSON report containing the following major sections.

## Agent 1: Requirement Analyser

- Executive summary
- Functional requirements
- Non-functional requirements
- Business/security/regulatory/constraint requirements when present
- Explicit vs inferred origin
- Ambiguities and clarifications
- Conflicting requirements
- Missing information and compliance gaps

## Agent 2: Compliance Agent

For every extracted requirement, the agent records:

- requirement ID
- requirement text
- compliance status
- banking standard/regulation
- section
- retrieved evidence
- notes

It also records domain-derived compliance checks separately.

## Agent 3: SDLC Determiner

- Recommended SDLC model
- Confidence
- Scores for all six models
- Eight factor assessments
- Supporting evidence
- Comparison with alternative models
- Retrieved SDLC reference passages

## Traceability

The final report maps each requirement to an applicable banking standard and an SDLC verification phase.
