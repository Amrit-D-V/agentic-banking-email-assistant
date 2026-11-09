import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import settings
from models.schemas import (
    CustomerLookupResponse,
    GetAccountBalanceResponse,
    GetCardTransactionsResponse,
    GetStatementResponse,
    TransactionItem,
    ValidateAccountResponse,
    ValidateCardResponse,
)

SIMULATED_TIMEOUT_ACCOUNT = "1111111111"
SIMULATED_OUTAGE_ACCOUNT = "2222222222"


class CoreBankingError(Exception):

    transient = False
    error_type = "API_ERROR"


class RecordNotFoundError(CoreBankingError):
    error_type = "NOT_FOUND"


class ServiceUnavailableError(CoreBankingError):
    transient = True
    error_type = "UNAVAILABLE"


def _digits_and_mask(value: str) -> str:
    return value.replace(" ", "").replace("-", "").upper().replace("*", "X")


def card_matches(candidate: str, key: str) -> bool:
    a, b = _digits_and_mask(candidate), _digits_and_mask(key)
    if len(a) != len(b):
        return False
    return all(x == y or "X" in (x, y) for x, y in zip(a, b))


class MockBankingService:
    def __init__(self):
        self.customers: Dict[str, Dict[str, Any]] = {
            "CUST-1002": {"name": "John Doe", "email": "john.doe@example.com", "primary_account": "1234567890"},
            "CUST-2004": {"name": "Priya Sharma", "email": "priya.sharma@example.com", "primary_account": "9876543210"},
            "CUST-3008": {"name": "Rajesh Kumar", "email": "rajesh.kumar@example.com", "primary_account": "5555666677"},
            "CUST-1489": {"name": "Amrit Vishwakarma", "email": None, "primary_account": "5010041489"},
        }

        self.accounts: Dict[str, Dict[str, Any]] = {
            "1234567890": {"customer_id": "CUST-1002", "account_type": "Savings", "available_balance": 125000.0},
            "9876543210": {"customer_id": "CUST-2004", "account_type": "Salary Account", "available_balance": 78450.50},
            "5555666677": {"customer_id": "CUST-3008", "account_type": "Current Account", "available_balance": 450000.0},
            "5010041489": {"customer_id": "CUST-1489", "account_type": "Savings Account", "available_balance": 95420.00},
            "1234509876": {"customer_id": "CUST-1002", "account_type": "Current Account", "available_balance": 48250.75},
            SIMULATED_TIMEOUT_ACCOUNT: {"customer_id": "CUST-1002", "account_type": "Savings", "available_balance": 1000.0},
            SIMULATED_OUTAGE_ACCOUNT: {"customer_id": "CUST-1002", "account_type": "Savings", "available_balance": 1000.0},
        }
        for acct in self.accounts.values():
            acct.update(currency="INR", status="ACTIVE")

        self.cards: Dict[str, Dict[str, Any]] = {
            "4567XXXX8901": {"customer_id": "CUST-1002", "card_type": "HDFC Millennia Credit Card", "credit_limit": 200000.0},
            "987654321": {"customer_id": "CUST-1002", "card_type": "HDFC Regalia Gold Credit Card", "credit_limit": 500000.0},
            "5240123412349012": {"customer_id": "CUST-2004", "card_type": "HDFC MoneyBack+ Credit Card", "credit_limit": 100000.0},
        }

        self.card_transactions: Dict[str, List[TransactionItem]] = {
            "4567XXXX8901": [
                TransactionItem(transaction_id="TXN-901-01", date="2026-04-28", merchant="Amazon India", amount=3499.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-901-02", date="2026-04-26", merchant="Swiggy Bangalore", amount=640.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-901-03", date="2026-04-24", merchant="Shell Fuel Station", amount=2500.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-901-04", date="2026-04-20", merchant="Uber India", amount=480.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-901-05", date="2026-04-18", merchant="Netflix Subscription", amount=649.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-901-06", date="2026-04-10", merchant="Cashback Refund", amount=150.0, type="CREDIT"),
            ],
            "987654321": [
                TransactionItem(transaction_id="TXN-321-01", date="2026-05-01", merchant="MakeMyTrip Flights", amount=18500.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-321-02", date="2026-04-29", merchant="Taj Hotels", amount=12400.0, type="DEBIT"),
                TransactionItem(transaction_id="TXN-321-03", date="2026-04-27", merchant="Croma Electronics", amount=8999.0, type="DEBIT"),
            ],
            "5240123412349012": [
                TransactionItem(transaction_id="TXN-012-01", date="2026-05-03", merchant="BigBasket", amount=2210.0, type="DEBIT"),
            ],
        }

        self.card_aliases: Dict[str, str] = {"4567123456788901": "4567XXXX8901"}


    def _find_card_key(self, card_number: str) -> Optional[str]:
        keys = list(self.cards) + list(self.card_aliases)
        key = next((k for k in keys if card_matches(card_number, k)), None)
        return self.card_aliases.get(key, key)

    def _customer_for_email(self, email: str) -> Optional[str]:
        email = (email or "").strip().lower()
        if not email:
            return None
        if settings.DEMO_CUSTOMER_EMAIL and email == settings.DEMO_CUSTOMER_EMAIL.lower():
            return "CUST-1002"
        return next((cid for cid, c in self.customers.items() if c["email"] and c["email"] == email), None)

    def _inject_faults(self, account_number: str = "") -> None:
        if account_number == SIMULATED_TIMEOUT_ACCOUNT:
            time.sleep(settings.MOCK_SLOW_RESPONSE_SECONDS)
        if account_number == SIMULATED_OUTAGE_ACCOUNT:
            raise ServiceUnavailableError("Core banking system temporarily unavailable (503).")
        if settings.MOCK_FAILURE_RATE and random.random() < settings.MOCK_FAILURE_RATE:
            raise ServiceUnavailableError("Simulated transient outage (chaos testing).")

    def account_owner(self, account_number: str) -> Optional[str]:
        acct = self.accounts.get(account_number.strip())
        return acct["customer_id"] if acct else None

    def card_owner(self, card_number: str) -> Optional[str]:
        key = self._find_card_key(card_number)
        return self.cards[key]["customer_id"] if key else None

    def lookup_customer_by_email(self, email: str) -> CustomerLookupResponse:
        cid = self._customer_for_email(email)
        if not cid:
            return CustomerLookupResponse(status="NOT_FOUND")
        c = self.customers[cid]
        return CustomerLookupResponse(
            status="FOUND", customer_id=cid, customer_name=c["name"], primary_account=c["primary_account"]
        )

    def validate_account(self, account_number: str) -> ValidateAccountResponse:
        acct = self.accounts.get(account_number.strip())
        if not acct:
            return ValidateAccountResponse(status="INVALID", message="Account number could not be found in banking records.")
        return ValidateAccountResponse(
            status="VALID",
            customer_name=self.customers[acct["customer_id"]]["name"],
            customer_id=acct["customer_id"],
            account_type=acct["account_type"],
            message="Account is active and verified in CBS.",
        )

    def validate_card(self, card_number: str) -> ValidateCardResponse:
        key = self._find_card_key(card_number)
        if not key:
            return ValidateCardResponse(status="INVALID", message="Credit card number is invalid or not registered.")
        card = self.cards[key]
        return ValidateCardResponse(
            status="VALID",
            customer_name=self.customers[card["customer_id"]]["name"],
            customer_id=card["customer_id"],
            card_type=card["card_type"],
            message="Credit card verified and active in CMS.",
        )

    def get_account_balance(self, account_number: str) -> GetAccountBalanceResponse:
        num = account_number.strip()
        self._inject_faults(num)
        acct = self.accounts.get(num)
        if not acct:
            raise RecordNotFoundError(f"Account {num[-4:]} not found.")
        return GetAccountBalanceResponse(
            account_number=num,
            customer_name=self.customers[acct["customer_id"]]["name"],
            account_type=acct["account_type"],
            available_balance=acct["available_balance"],
            currency=acct["currency"],
            status=acct["status"],
        )

    def get_card_transactions(self, card_number: str, limit: int = 5) -> GetCardTransactionsResponse:
        self._inject_faults()
        key = self._find_card_key(card_number)
        if not key:
            raise RecordNotFoundError("Credit card not found.")
        card = self.cards[key]
        txns = self.card_transactions.get(key, [])[: max(1, limit)]
        return GetCardTransactionsResponse(
            card_number=card_number,
            customer_name=self.customers[card["customer_id"]]["name"],
            card_type=card["card_type"],
            count=len(txns),
            transactions=txns,
        )

    def get_statement(
        self, account_number: str, period: str, date_from: Optional[str] = None, date_to: Optional[str] = None
    ) -> GetStatementResponse:
        num = account_number.strip()
        self._inject_faults(num)
        acct = self.accounts.get(num)
        if not acct:
            raise RecordNotFoundError(f"Account {num[-4:]} not found.")
        slug = (date_from and date_to and f"{date_from}_{date_to}") or period.lower().replace(" ", "_")
        stmt_id = f"STMT-{num[-4:]}-{slug}"
        return GetStatementResponse(
            account_number=num,
            customer_name=self.customers[acct["customer_id"]]["name"],
            period=period,
            statement_id=stmt_id,
            download_url=f"https://netbanking.hdfc.internal/statements/download/{stmt_id}.pdf",
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            date_from=date_from,
            date_to=date_to,
        )


mock_banking_service = MockBankingService()
