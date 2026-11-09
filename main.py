import argparse
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.settings import settings
from models.schemas import EmailInput
from sample_data.sample_emails import SAMPLE_EMAILS, SCENARIO_TITLES, fresh_copy
from utils.logging_config import setup_logging
from workflows.orchestrator import orchestrator

console = Console()


def display_scenario_result(scenario_name: str, state):
    console.print()
    console.rule(f"[bold cyan]Execution Report: {scenario_name}[/bold cyan]")

    intake_table = Table(title="1. Intake & NLP Analysis", show_header=True, header_style="bold magenta")
    intake_table.add_column("Parameter", style="cyan", width=22)
    intake_table.add_column("Value", style="white")

    intake_table.add_row("Email ID", state.email.email_id)
    intake_table.add_row("Subject", state.email.subject)
    intake_table.add_row("Raw Content", state.email.body)
    intake_table.add_row(
        "Detected Intents",
        ", ".join([f"[green]{i.value}[/green]" for i in state.detected_intents]),
    )
    sentiment_color = "red" if state.urgency_flag else "green"
    intake_table.add_row(
        "Sentiment & Tone",
        f"[{sentiment_color}]{state.sentiment.value}[/{sentiment_color}] (Urgent={state.urgency_flag})",
    )
    intake_table.add_row("Sentiment Reason", state.sentiment_reason)
    console.print(intake_table)

    validation_table = Table(title="2. Entity Extraction & Core Validation", show_header=True, header_style="bold blue")
    validation_table.add_column("Entity Type", style="cyan", width=22)
    validation_table.add_column("Raw Value", style="white", width=20)
    validation_table.add_column("Masked (PII Safe)", style="yellow", width=22)
    validation_table.add_column("Validation Status", width=18)
    validation_table.add_column("Details", style="white")

    for val in state.validation_summary.validations:
        status_val = val.status.value if hasattr(val.status, "value") else str(val.status)
        status_style = "green" if status_val == "VALID" else "red"
        validation_table.add_row(
            val.entity_type,
            str(val.raw_value or "None"),
            str(val.masked_value or "None"),
            f"[{status_style}]{status_val}[/{status_style}]",
            val.message,
        )
    console.print(validation_table)

    api_table = Table(title="3. API Decision Engine & Core Banking Orchestration", show_header=True, header_style="bold green")
    api_table.add_column("API Invoked", style="cyan", width=24)
    api_table.add_column("Transport", width=10)
    api_table.add_column("Status", width=10)
    api_table.add_column("Tries", width=5)
    api_table.add_column("Latency", width=11)
    api_table.add_column("Result Summary", style="white")

    for log in state.api_call_logs:
        status_badge = f"[green]{log.status}[/green]" if log.status == "SUCCESS" else f"[red]{log.status}[/red]"
        summary = str(log.response_payload or log.error_message)[:60]
        api_table.add_row(log.api_name, log.transport, status_badge, str(log.attempts), f"{log.execution_time_ms} ms", summary)
    console.print(api_table)
    for stage in state.api_plan:
        console.print(f"[dim]Decision plan · {stage['stage']} ({stage['mode']}): {', '.join(stage['apis']) or '-'}"
                      + (f" | skipped: {[x['intent'] for x in stage.get('skipped', [])]}" if stage.get("skipped") else "") + "[/dim]")
    if state.requires_human_review:
        console.print(f"[bold yellow]Flagged for human review:[/bold yellow] {', '.join(state.review_reasons)}")

    partial_banner = ""
    if state.has_partial_failure:
        partial_banner = "[bold yellow]PARTIAL FULFILMENT: valid requests answered, failures explained[/bold yellow]\n\n"

    response_content = f"{partial_banner}[bold]Subject:[/bold] {state.final_email_subject}\n\n{state.masked_response}"
    console.print(Panel(response_content, title="[bold green]Final Automated Response Email[/bold green]", border_style="green"))

    console.print(
        f"[dim]Total Pipeline Execution Time: [bold cyan]{state.total_execution_ms} ms[/bold cyan] | "
        f"Audit record saved to: [bold]{settings.DATABASE_URL.split(':', 1)[0]}[/bold][/dim]\n"
    )


def run_scenario(scenario_key: str):
    if scenario_key not in SAMPLE_EMAILS:
        console.print(f"[bold red]Unknown scenario key:[/bold red] {scenario_key}")
        console.print(f"Available keys: {list(SAMPLE_EMAILS.keys())}")
        return

    state = orchestrator.process_email(fresh_copy(scenario_key))
    display_scenario_result(SCENARIO_TITLES.get(scenario_key, scenario_key), state)


def demo_all_scenarios():
    console.print(Panel(
        "[bold cyan]Intelligent Email Processing System[/bold cyan]\n"
        f"[white]End-to-end demonstration of {len(SAMPLE_EMAILS)} scenarios[/white]\n"
        f"[dim]LLM: {settings.LLM_PROVIDER} ({settings.OLLAMA_MODEL}) · Core banking transport: {settings.BANKING_API_TRANSPORT}[/dim]",
        border_style="cyan",
    ))
    for key in SAMPLE_EMAILS:
        display_scenario_result(SCENARIO_TITLES.get(key, key), orchestrator.process_email(fresh_copy(key)))


def run_evaluation():
    from utils.evaluation import evaluate

    console.print(f"[bold cyan]Evaluating on labelled emails[/bold cyan] · LLM: {settings.LLM_PROVIDER} ({settings.OLLAMA_MODEL})")
    report = evaluate()

    table = Table(title=f"Accuracy on {report['cases']} emails ({report['fully_correct']} fully correct)", header_style="bold magenta")
    table.add_column("Field")
    table.add_column("Correct", justify="right")
    table.add_column("Accuracy", justify="right")
    for field, a in report["accuracy"].items():
        table.add_row(field, f"{a['correct']}/{a['total']}", f"{a['pct']}%")
    console.print(table)

    intents = Table(title="Intent detection", header_style="bold blue")
    for col in ("Intent", "Precision", "Recall", "F1", "Support"):
        intents.add_column(col, justify="left" if col == "Intent" else "right")
    for name, m in report["per_intent"].items():
        intents.add_row(name, f"{m['precision']:.2f}", f"{m['recall']:.2f}", f"{m['f1']:.2f}", str(m["support"]))
    console.print(intents)
    console.print(f"Latency per email: median {report['latency_ms']['median']} ms, max {report['latency_ms']['max']} ms")

    for f in report["failures"]:
        console.print(f"[yellow]{f['id']}[/yellow] failed {f['failed']}: {f['body']}")
        console.print(f"   expected {f['expected_intents']} got {f['got_intents']} · {f['got']}", style="dim")


def interactive_mode():
    console.print("[bold green]Interactive Mode Active.[/bold green] Type an email to process (or 'exit' to quit):")
    while True:
        try:
            subject = input("\nEnter Subject: ")
            if subject.strip().lower() in ["exit", "quit", "q"]:
                break
            body = input("Enter Email Body: ")
            if not body.strip():
                console.print("[yellow]Empty body, skipping.[/yellow]")
                continue

            email = EmailInput(
                sender=settings.DEMO_CUSTOMER_EMAIL,
                subject=subject,
                body=body,
            )
            state = orchestrator.process_email(email)
            display_scenario_result("Custom Interactive Inquiry", state)
        except (KeyboardInterrupt, EOFError):
            break


def main():
    parser = argparse.ArgumentParser(description="HDFC Intelligent Banking Email Automation System")
    parser.add_argument(
        "action",
        nargs="?",
        default="ui",
        choices=["ui", "demo-all", "scenario", "interactive", "evaluate", "serve-api", "serve-mcp", "email-worker"],
        help="Action to perform",
    )
    parser.add_argument("--key", default="scenario_1_balance", help="Scenario key for 'scenario' action")
    parser.add_argument("--poll", action="store_true", help="Poll continuously for new emails in email-worker mode")
    parser.add_argument("--llm", choices=["ollama", "mock"], help="Override LLM_PROVIDER (mock = rule engine only)")
    parser.add_argument("--transport", choices=["inprocess", "http", "mcp"], help="Override BANKING_API_TRANSPORT")

    args = parser.parse_args()
    if args.llm:
        settings.LLM_PROVIDER = args.llm
    if args.transport:
        settings.BANKING_API_TRANSPORT = args.transport
    if args.action not in ("serve-mcp",):
        setup_logging()

    if args.action == "ui" or args.action == "serve-api":
        import uvicorn
        console.print(Panel(
            f"[bold cyan]Intelligent Email Processing System[/bold cyan]\n"
            f"[bold green]Dashboard:[/bold green] [bold underline]http://127.0.0.1:8000/dashboard[/bold underline]\n"
            f"[dim]REST API Docs (Swagger): [bold underline]http://127.0.0.1:8000/docs[/bold underline][/dim]",
            border_style="green",
        ))
        uvicorn.run("apis.banking_api_server:app", host="127.0.0.1", port=8000, reload=False)
    elif args.action == "demo-all":
        demo_all_scenarios()
    elif args.action == "scenario":
        run_scenario(args.key)
    elif args.action == "interactive":
        interactive_mode()
    elif args.action == "evaluate":
        run_evaluation()
    elif args.action == "serve-mcp":
        from apis.mcp_banking_server import run_mcp_stdio
        console.print("[bold green]Starting MCP Server over stdio...[/bold green]")
        run_mcp_stdio()
    elif args.action == "email-worker":
        from email_worker import email_worker

        if not email_worker.configured:
            console.print("[bold red]Set EMAIL_USER and EMAIL_PASS (Gmail app password) in .env first.[/bold red]")
            sys.exit(1)
        console.print(Panel(
            f"[bold cyan]Live Email Automation Worker[/bold cyan]\n"
            f"Mailbox: [bold]{email_worker.user}[/bold] · HITL: {'on' if settings.HITL_ENABLED else 'off'}\n"
            f"[dim]Polling Mode: {'Continuous (every 8s)' if args.poll else 'Single-pass'}[/dim]",
            border_style="green",
        ))
        if args.poll:
            email_worker.watch()
        else:
            console.print(f"[bold green]Processed {email_worker.process_pending()} pending email(s).[/bold green]")


if __name__ == "__main__":
    main()
