from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    BALANCE_ENQUIRY = "BALANCE_ENQUIRY"
    CARD_TRANSACTIONS = "CARD_TRANSACTIONS"
    STATEMENT_REQUEST = "STATEMENT_REQUEST"
    POLICY_INQUIRY = "POLICY_INQUIRY"
    GENERAL_INQUIRY = "GENERAL_INQUIRY"
    UNKNOWN = "UNKNOWN"


class SentimentType(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE_URGENT = "NEGATIVE_URGENT"


class EntityValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EmailInput(BaseModel):
    email_id: str = Field(default_factory=lambda: f"EML-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}")
    sender: str
    subject: str
    body: str
    received_at: datetime = Field(default_factory=datetime.now)
    attachment_paths: List[str] = Field(default_factory=list)
    channel: str = "api"
    sender_verified: Optional[bool] = None
    message_id: Optional[str] = None


class ExtractedEntities(BaseModel):
    account_number: Optional[str] = None
    credit_card_number: Optional[str] = None
    account_numbers: List[str] = Field(default_factory=list)
    card_numbers: List[str] = Field(default_factory=list)
    statement_period: Optional[str] = None
    transaction_count: Optional[int] = 5
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    customer_name: Optional[str] = None
    confidence_scores: Dict[str, float] = Field(default_factory=dict)
    sources: Dict[str, str] = Field(default_factory=dict)


class EntityValidationDetail(BaseModel):
    entity_type: str
    raw_value: Optional[str] = None
    masked_value: Optional[str] = None
    status: EntityValidationStatus
    message: str
    customer_name: Optional[str] = None
    additional_info: Dict[str, Any] = Field(default_factory=dict)


class ValidationSummary(BaseModel):
    overall_valid: bool = True
    has_partial_failure: bool = False
    validations: List[EntityValidationDetail] = Field(default_factory=list)


class ValidateAccountRequest(BaseModel):
    account_number: str

class ValidateAccountResponse(BaseModel):
    status: str
    customer_name: Optional[str] = None
    customer_id: Optional[str] = None
    account_type: Optional[str] = None
    message: Optional[str] = None


class ValidateCardRequest(BaseModel):
    card_number: str

class ValidateCardResponse(BaseModel):
    status: str
    customer_name: Optional[str] = None
    customer_id: Optional[str] = None
    card_type: Optional[str] = None
    message: Optional[str] = None


class GetAccountBalanceRequest(BaseModel):
    account_number: str

class GetAccountBalanceResponse(BaseModel):
    account_number: str
    customer_name: str
    account_type: str
    available_balance: float
    currency: str = "INR"
    status: str = "ACTIVE"


class TransactionItem(BaseModel):
    transaction_id: str
    date: str
    merchant: str
    amount: float
    currency: str = "INR"
    type: str


class GetCardTransactionsRequest(BaseModel):
    card_number: str
    limit: int = 5

class GetCardTransactionsResponse(BaseModel):
    card_number: str
    customer_name: str
    card_type: str
    count: int
    transactions: List[TransactionItem]


class GetStatementRequest(BaseModel):
    account_number: str
    period: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None

class GetStatementResponse(BaseModel):
    account_number: str
    customer_name: str
    period: str
    statement_id: str
    download_url: str
    generated_at: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class CustomerLookupRequest(BaseModel):
    email: str


class CustomerLookupResponse(BaseModel):
    status: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    primary_account: Optional[str] = None


class ApiCallResult(BaseModel):
    api_name: str
    endpoint: str
    status: str
    request_payload: Dict[str, Any]
    response_payload: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    attempts: int = 1
    transport: str = "inprocess"


class AgentState(BaseModel):
    email: EmailInput
    cleaned_body: str = ""
    detected_language: str = "en"
    translated_body: str = ""
    llm_analysis: Dict[str, Any] = Field(default_factory=dict)
    attachment_extracted_text: str = ""
    full_context: str = ""
    
    detected_intents: List[IntentType] = Field(default_factory=list)
    intent_confidences: Dict[str, float] = Field(default_factory=dict)
    sentiment: SentimentType = SentimentType.NEUTRAL
    sentiment_reason: str = ""
    urgency_flag: bool = False
    
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    customer_profile: Dict[str, Any] = Field(default_factory=dict)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    
    selected_apis: List[str] = Field(default_factory=list)
    api_plan: List[Dict[str, Any]] = Field(default_factory=list)
    api_results: Dict[str, Any] = Field(default_factory=dict)
    api_call_logs: List[ApiCallResult] = Field(default_factory=list)
    fulfilments: List[Dict[str, Any]] = Field(default_factory=list)
    
    has_partial_failure: bool = False
    retrieved_policies: List[str] = Field(default_factory=list)
    generated_response: str = ""
    final_email_subject: str = ""
    masked_response: str = ""

    requires_human_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)
    
    execution_trace: List[str] = Field(default_factory=list)
    agent_timings: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    start_time: datetime = Field(default_factory=datetime.now)
    total_execution_ms: float = 0.0


class AuditRecord(BaseModel):
    timestamp: str
    email_id: str
    sender_masked: str
    subject: str
    detected_intents: List[str]
    intent_confidences: Dict[str, float] = Field(default_factory=dict)
    sentiment: str
    sentiment_reason: str = ""
    urgency_flag: bool
    entities_masked: Dict[str, Any]
    validations: List[Dict[str, Any]] = Field(default_factory=list)
    validation_status: str
    api_plan: List[Dict[str, Any]] = Field(default_factory=list)
    apis_called: List[str]
    api_calls: List[Dict[str, Any]] = Field(default_factory=list)
    has_partial_failure: bool
    requires_human_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)
    response_subject: str = ""
    response_masked: str = ""
    response_preview: str
    execution_trace: List[str] = Field(default_factory=list)
    agent_timings: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    language: str = "en"
    translated: bool = False
    sender_verified: Optional[bool] = None
    llm_provider: str = ""
    api_transport: str = ""
    total_execution_ms: float
    status: str
