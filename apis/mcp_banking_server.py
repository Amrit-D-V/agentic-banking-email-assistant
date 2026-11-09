import json
from typing import Callable, Optional

from mcp.server.mcpserver import MCPServer

from apis.mock_banking_service import CoreBankingError, mock_banking_service
from config.settings import settings

mcp_server = MCPServer(settings.MCP_SERVER_NAME)


def _run(fn: Callable) -> str:
    try:
        return fn().model_dump_json()
    except CoreBankingError as e:
        return json.dumps({"error": str(e), "error_type": e.error_type, "transient": e.transient})


@mcp_server.tool(description="Find the customer registered with a sender email address (status, customer id, name, primary account).")
def lookup_customer_by_email(email: str) -> str:
    return _run(lambda: mock_banking_service.lookup_customer_by_email(email))


@mcp_server.tool(description="Validate that a bank account exists and is active in core banking.")
def validate_account(account_number: str) -> str:
    return _run(lambda: mock_banking_service.validate_account(account_number))


@mcp_server.tool(description="Validate that a credit card (masked or full number) exists and is active.")
def validate_card(card_number: str) -> str:
    return _run(lambda: mock_banking_service.validate_card(card_number))


@mcp_server.tool(description="Get the available balance, currency and account type for a verified account.")
def get_account_balance(account_number: str) -> str:
    return _run(lambda: mock_banking_service.get_account_balance(account_number))


@mcp_server.tool(description="Get the most recent credit card transactions (default 5) for a verified card.")
def get_card_transactions(card_number: str, limit: int = 5) -> str:
    return _run(lambda: mock_banking_service.get_card_transactions(card_number, limit=limit))


@mcp_server.tool(description="Get a statement reference and secure download link for an account and period (optional ISO date range).")
def get_account_statement(
    account_number: str, period: str, date_from: Optional[str] = None, date_to: Optional[str] = None
) -> str:
    return _run(lambda: mock_banking_service.get_statement(account_number, period, date_from, date_to))


@mcp_server.tool(description="Search bank policies (minimum balance, charges, fraud rules, statement security) and return matching excerpts.")
def lookup_banking_policy(query: str) -> str:
    from utils.policy_rag import policy_rag

    return json.dumps({"query": query, "results": policy_rag.search(query, top_k=2)})


def run_mcp_stdio():
    mcp_server.run()


if __name__ == "__main__":
    run_mcp_stdio()
