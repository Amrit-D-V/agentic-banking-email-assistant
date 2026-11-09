import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse

from apis.auth import require_admin
from apis.dashboard_ui import DASHBOARD_PAGE
from apis.mock_banking_service import CoreBankingError, ServiceUnavailableError, mock_banking_service
from apis.operations import apply_saved_config, router as ops_router
from apis.prometheus import router as prometheus_router
from config.settings import settings
from email_worker import safe_filename
from models.schemas import (
    AgentState,
    CustomerLookupRequest,
    CustomerLookupResponse,
    EmailInput,
    GetAccountBalanceRequest,
    GetAccountBalanceResponse,
    GetCardTransactionsRequest,
    GetCardTransactionsResponse,
    GetStatementRequest,
    GetStatementResponse,
    ValidateAccountRequest,
    ValidateAccountResponse,
    ValidateCardRequest,
    ValidateCardResponse,
)
from utils.logging_config import setup_logging
from workflows.orchestrator import orchestrator

setup_logging()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    apply_saved_config()
    yield


app = FastAPI(
    title="Core Banking & Agentic Email Automation API",
    description="Mock CBS/CMS APIs, the multi-agent email pipeline, and the operations control plane for Task-1002.",
    version="2.0.0",
    lifespan=lifespan,
)
app.include_router(ops_router, dependencies=[Depends(require_admin)])
app.include_router(prometheus_router)

ALLOWED_ATTACHMENT_ROOTS = [settings.ATTACHMENTS_DIR.resolve(), (settings.BASE_DIR / "sample_data").resolve()]
UPLOAD_DIR = settings.ATTACHMENTS_DIR / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _check_attachment_paths(paths: List[str]) -> None:
    for p in paths:
        resolved = (settings.BASE_DIR / p).resolve()
        if not any(resolved.is_relative_to(root) for root in ALLOWED_ATTACHMENT_ROOTS):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Attachment path not allowed: {Path(p).name}")


def _cbs(fn):
    try:
        return fn()
    except ServiceUnavailableError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e))
    except CoreBankingError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse, tags=["Web UI"])
def get_dashboard(_user: str = Depends(require_admin)):
    return HTMLResponse(content=DASHBOARD_PAGE)


@app.post(
    "/api/v1/process-email",
    response_model=AgentState,
    tags=["Agentic Automation"],
    summary="Process customer email through the 8-agent LangGraph pipeline",
)
def process_customer_email(email_input: EmailInput, _user: str = Depends(require_admin)):
    _check_attachment_paths(email_input.attachment_paths)
    return orchestrator.process_email(email_input)


@app.post(
    "/api/v1/process-email-upload",
    response_model=AgentState,
    tags=["Agentic Automation"],
    summary="Process an email with uploaded attachments (PDF / images / text)",
)
async def process_email_upload(
    sender: str = Form(...),
    subject: str = Form(""),
    body: str = Form(""),
    files: Optional[List[UploadFile]] = File(None),
    _user: str = Depends(require_admin),
):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files or []:
        data = await f.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{f.filename} exceeds 10 MB")
        if not data:
            continue
        dest = UPLOAD_DIR / f"{int(time.time() * 1000)}_{safe_filename(f.filename or 'upload')}"
        dest.write_bytes(data)
        paths.append(str(dest))
    mail = EmailInput(sender=sender, subject=subject, body=body or subject, attachment_paths=paths, channel="ui")
    return orchestrator.process_email(mail)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "HEALTHY", "service": "Agentic Email Automation"}


@app.post(
    "/api/v1/customer-lookup",
    response_model=CustomerLookupResponse,
    tags=["Validation"],
    summary="Find customer by registered email",
)
def customer_lookup(request: CustomerLookupRequest):
    return mock_banking_service.lookup_customer_by_email(request.email)


@app.post(
    "/api/v1/validate-account",
    response_model=ValidateAccountResponse,
    tags=["Validation"],
    summary="Validate Account Number",
)
def validate_account(request: ValidateAccountRequest):
    return mock_banking_service.validate_account(request.account_number)


@app.post(
    "/api/v1/validate-card",
    response_model=ValidateCardResponse,
    tags=["Validation"],
    summary="Validate Credit Card Number",
)
def validate_card(request: ValidateCardRequest):
    return mock_banking_service.validate_card(request.card_number)


@app.post(
    "/api/v1/account-balance",
    response_model=GetAccountBalanceResponse,
    tags=["Accounts"],
    summary="Get Account Balance",
)
def get_account_balance(request: GetAccountBalanceRequest):
    return _cbs(lambda: mock_banking_service.get_account_balance(request.account_number))


@app.post(
    "/api/v1/card-transactions",
    response_model=GetCardTransactionsResponse,
    tags=["Cards"],
    summary="Get Card Transactions",
)
def get_card_transactions(request: GetCardTransactionsRequest):
    return _cbs(lambda: mock_banking_service.get_card_transactions(request.card_number, limit=request.limit))


@app.post(
    "/api/v1/statement",
    response_model=GetStatementResponse,
    tags=["Statements"],
    summary="Get Account Statement",
)
def get_statement(request: GetStatementRequest):
    return _cbs(lambda: mock_banking_service.get_statement(
        request.account_number, request.period, request.date_from, request.date_to))
