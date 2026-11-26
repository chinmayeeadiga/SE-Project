import argparse
import sys
from pathlib import Path

# Configure utf-8 stdout/stderr for Windows console compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from src.config import settings
from src.rag.pipeline import RAGPipeline
from src.rag.evaluation import RetrievalEvaluator
from src.orchestrator import Orchestrator

console = Console(force_terminal=True, legacy_windows=False)


def handle_ingest(args):
    """Command to ingest documents into the RAG knowledge base."""
    console.print(Panel.fit("[bold green]Starting Document Ingestion into Knowledge Base...[/bold green]"))
    pipeline = RAGPipeline()
    result = pipeline.ingest_documents(force=args.force)
    
    table = Table(title="Knowledge Base Ingestion Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    for k, v in result.items():
        table.add_row(str(k), str(v))
    
    console.print(table)
    console.print("[bold green][OK] Ingestion Completed Successfully![/bold green]")


def handle_analyze(args):
    """Command to analyze a stakeholder input document."""
    file_path = Path(args.file)
    if not file_path.exists():
        console.print(f"[bold red]Error: Input file '{file_path}' does not exist.[/bold red]")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    title = args.title or file_path.stem.replace("_", " ").title()
    console.print(Panel.fit(f"[bold cyan]Analyzing Requirements for: {title}[/bold cyan]"))

    orchestrator = Orchestrator(output_dir=Path(args.output) if args.output else None)
    report = orchestrator.run(stakeholder_input=content, project_title=title, save_outputs=True)

    console.print("\n[bold green][OK] Analysis & SDLC Detection Completed![/bold green]\n")
    
    # Summary display
    summary_table = Table(title="Execution Summary")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Result", style="green")
    
    summary_table.add_row("Total Requirements", str(len(report.requirements_analysis.requirements)))
    summary_table.add_row("Ambiguities Detected", str(len(report.requirements_analysis.ambiguities)))
    summary_table.add_row("Conflicts Detected", str(len(report.requirements_analysis.conflicts)))
    summary_table.add_row("Missing Info Gaps", str(len(report.requirements_analysis.missing_information)))
    if report.compliance_report:
        summary_table.add_row("Compliance Checks", str(len(report.compliance_report.checks)))
        summary_table.add_row("Compliance Needs Review", str(report.compliance_report.needs_review_count))
    summary_table.add_row("Recommended SDLC Model", f"[bold]{report.sdlc_recommendation.recommended_model.value}[/bold]")
    summary_table.add_row("Model Confidence", f"{int(report.sdlc_recommendation.confidence * 100)}%")
    
    console.print(summary_table)

    # SDLC Scores
    sdlc_table = Table(title="SDLC Model Scores (0 - 100)")
    sdlc_table.add_column("SDLC Model", style="bold")
    sdlc_table.add_column("Score", style="yellow")
    sdlc_table.add_column("Status", style="magenta")

    for model, score in sorted(report.sdlc_recommendation.model_scores.items(), key=lambda x: x[1], reverse=True):
        status = "[RECOMMENDED]" if model == report.sdlc_recommendation.recommended_model.value else "Evaluated"
        sdlc_table.add_row(model, f"{score:.1f}", status)

    console.print(sdlc_table)
    console.print(f"\n[bold]Output reports saved to:[/bold] `{orchestrator.output_dir.resolve()}`")


def handle_evaluate(args):
    """Command to evaluate passage-level answerability on actual documents."""
    console.print(Panel.fit("[bold blue]Evaluating Passage-Level Retrieval Answerability...[/bold blue]"))
    pipeline = RAGPipeline()
    evaluator = RetrievalEvaluator()
    eval_result = evaluator.evaluate_pipeline(pipeline)

    table = Table(title="Passage-Level Retrieval Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Benchmark Test Cases", str(eval_result["test_cases_count"]))
    table.add_row("Hit Rate @ 1", f"{eval_result['hit_rate_at_1'] * 100:.1f}%")
    table.add_row("Hit Rate @ K", f"{eval_result['hit_rate_at_k'] * 100:.1f}%")
    table.add_row("Mean Reciprocal Rank (MRR)", f"{eval_result['mrr']:.3f}")
    table.add_row("Avg Top-1 Passage Answerability", f"{eval_result['avg_top1_answerability'] * 100:.1f}%")
    table.add_row("Avg Best Passage Answerability", f"{eval_result['avg_best_answerability'] * 100:.1f}%")

    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Digital Banking Requirements Engineering & SDLC Detection Assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ingest
    ingest_parser = subparsers.add_parser("ingest", help="Ingest documents into knowledge base")
    ingest_parser.add_argument("--force", action="store_true", help="Force re-indexing all documents")

    # analyze
    analyze_parser = subparsers.add_parser("analyze", help="Analyze stakeholder input document")
    analyze_parser.add_argument("--file", "-f", required=True, help="Path to stakeholder input file (txt/md)")
    analyze_parser.add_argument("--title", "-t", default=None, help="Project title")
    analyze_parser.add_argument("--output", "-o", default=None, help="Output directory for reports")

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate passage-level retrieval answerability")

    args = parser.parse_args()

    if args.command == "ingest":
        handle_ingest(args)
    elif args.command == "analyze":
        handle_analyze(args)
    elif args.command == "evaluate":
        handle_evaluate(args)


if __name__ == "__main__":
    main()
