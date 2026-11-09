import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

from apis.mock_banking_service import CoreBankingError, mock_banking_service
from config.settings import settings
from models.schemas import ApiCallResult


class ApiError(Exception):
    def __init__(self, message: str, error_type: str = "API_ERROR", transient: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.transient = transient


@dataclass(frozen=True)
class ApiSpec:
    name: str
    endpoint: str
    mcp_tool: str
    local: Callable[..., Any]


SPECS: Dict[str, ApiSpec] = {
    s.name: s
    for s in [
        ApiSpec("LookupCustomerByEmailAPI", "/api/v1/customer-lookup", "lookup_customer_by_email",
                lambda p: mock_banking_service.lookup_customer_by_email(p["email"])),
        ApiSpec("ValidateAccountAPI", "/api/v1/validate-account", "validate_account",
                lambda p: mock_banking_service.validate_account(p["account_number"])),
        ApiSpec("ValidateCardAPI", "/api/v1/validate-card", "validate_card",
                lambda p: mock_banking_service.validate_card(p["card_number"])),
        ApiSpec("GetAccountBalanceAPI", "/api/v1/account-balance", "get_account_balance",
                lambda p: mock_banking_service.get_account_balance(p["account_number"])),
        ApiSpec("GetCardTransactionsAPI", "/api/v1/card-transactions", "get_card_transactions",
                lambda p: mock_banking_service.get_card_transactions(p["card_number"], limit=p["limit"])),
        ApiSpec("GetStatementAPI", "/api/v1/statement", "get_account_statement",
                lambda p: mock_banking_service.get_statement(p["account_number"], p["period"], p.get("date_from"), p.get("date_to"))),
    ]
}

_local_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="cbs-call")

CACHEABLE = {"LookupCustomerByEmailAPI", "ValidateAccountAPI", "ValidateCardAPI"}


class CircuitBreaker:
    def __init__(self):
        self._lock = threading.Lock()
        self._failures: Dict[str, int] = {}
        self._opened_at: Dict[str, float] = {}

    def allow(self, api_name: str) -> bool:
        with self._lock:
            opened = self._opened_at.get(api_name)
            return opened is None or time.monotonic() - opened >= settings.CIRCUIT_RESET_SECONDS

    def record(self, api_name: str, transient_failure: bool) -> None:
        with self._lock:
            if not transient_failure:
                self._failures.pop(api_name, None)
                self._opened_at.pop(api_name, None)
                return
            self._failures[api_name] = self._failures.get(api_name, 0) + 1
            if self._failures[api_name] >= settings.CIRCUIT_FAILURE_THRESHOLD:
                self._opened_at[api_name] = time.monotonic()

    def states(self) -> Dict[str, str]:
        with self._lock:
            now = time.monotonic()
            return {api: "OPEN" if now - t < settings.CIRCUIT_RESET_SECONDS else "HALF_OPEN"
                    for api, t in self._opened_at.items()}

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._opened_at.clear()


class TTLCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            hit = self._items.get(key)
            if hit and time.monotonic() - hit[0] < settings.API_CACHE_SECONDS:
                return hit[1]
            self._items.pop(key, None)
            return None

    def put(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class BankingApiClient:
    def __init__(self, base_url: Optional[str] = None, transport: Optional[str] = None):
        self.base_url = base_url or f"http://{settings.BANKING_API_HOST}:{settings.BANKING_API_PORT}"
        self._transport = transport
        self.breaker = CircuitBreaker()
        self.cache = TTLCache()

    def reset(self) -> None:
        self.breaker.reset()
        self.cache.clear()

    @property
    def transport(self) -> str:
        return self._transport or settings.BANKING_API_TRANSPORT


    def _call_inprocess(self, spec: ApiSpec, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        fut = _local_pool.submit(spec.local, payload)
        try:
            return fut.result(timeout=timeout).model_dump()
        except FutureTimeout:
            raise TimeoutError(f"{spec.name} timed out after {timeout}s")
        except CoreBankingError as e:
            raise ApiError(str(e), e.error_type, e.transient)

    def _call_http(self, spec: ApiSpec, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        try:
            r = httpx.post(f"{self.base_url}{spec.endpoint}", json=payload, timeout=timeout)
        except httpx.TimeoutException:
            raise TimeoutError(f"{spec.name} timed out after {timeout}s")
        except httpx.TransportError as e:
            raise ApiError(f"Connection error: {e}", "UNAVAILABLE", transient=True)
        if r.status_code >= 500:
            raise ApiError(r.json().get("detail", r.text), "UNAVAILABLE", transient=True)
        if r.status_code == 404:
            raise ApiError(r.json().get("detail", "Not found"), "NOT_FOUND")
        if r.status_code >= 400:
            raise ApiError(r.text, "API_ERROR")
        return r.json()

    def _call_mcp(self, spec: ApiSpec, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        from apis.mcp_client import mcp_banking_client

        data = mcp_banking_client.call_tool(spec.mcp_tool, payload, timeout=timeout)
        if "error" in data:
            raise ApiError(data["error"], data.get("error_type", "API_ERROR"), bool(data.get("transient")))
        return data


    def invoke(self, api_name: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], ApiCallResult]:
        spec = SPECS[api_name]
        transport = self.transport
        dispatch = {"inprocess": self._call_inprocess, "http": self._call_http, "mcp": self._call_mcp}[transport]
        timeout = settings.API_TIMEOUT_SECONDS
        max_attempts = 1 + max(0, settings.API_MAX_RETRIES)

        t0 = time.perf_counter()
        cache_key = f"{api_name}:{json.dumps(payload, sort_keys=True)}" if api_name in CACHEABLE and settings.API_CACHE_SECONDS > 0 else None
        if cache_key and (cached := self.cache.get(cache_key)) is not None:
            return cached, self._log(spec, payload, "cache", t0, 0, "SUCCESS", data=cached)
        if not self.breaker.allow(api_name):
            data = {"error": f"{api_name} circuit open after repeated failures", "error_type": "CIRCUIT_OPEN"}
            return data, self._log(spec, payload, transport, t0, 0, "FAILED", error=data["error"])

        error: Optional[ApiError] = None
        attempt = 0
        for attempt in range(1, max_attempts + 1):
            try:
                data = dispatch(spec, payload, timeout)
                self.breaker.record(api_name, transient_failure=False)
                if cache_key:
                    self.cache.put(cache_key, data)
                return data, self._log(spec, payload, transport, t0, attempt, "SUCCESS", data=data)
            except TimeoutError as e:
                error = ApiError(str(e), "TIMEOUT", transient=True)
            except ApiError as e:
                error = e
            except Exception as e:
                error = ApiError(str(e), "API_ERROR", transient=True)
            if not error.transient or attempt == max_attempts:
                break
            time.sleep(settings.API_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

        self.breaker.record(api_name, transient_failure=error.transient)
        status = "TIMEOUT" if error.error_type == "TIMEOUT" else "FAILED"
        data = {"error": str(error), "error_type": error.error_type}
        return data, self._log(spec, payload, transport, t0, attempt, status, error=str(error))

    @staticmethod
    def _log(spec, payload, transport, t0, attempts, status, data=None, error=None) -> ApiCallResult:
        return ApiCallResult(
            api_name=spec.name,
            endpoint=spec.endpoint,
            status=status,
            request_payload=payload,
            response_payload=data,
            error_message=error,
            execution_time_ms=round((time.perf_counter() - t0) * 1000, 2),
            attempts=attempts,
            transport=transport,
        )


    def lookup_customer_by_email(self, email: str):
        return self.invoke("LookupCustomerByEmailAPI", {"email": email})

    def validate_account(self, account_number: str):
        return self.invoke("ValidateAccountAPI", {"account_number": account_number})

    def validate_card(self, card_number: str):
        return self.invoke("ValidateCardAPI", {"card_number": card_number})

    def get_account_balance(self, account_number: str):
        return self.invoke("GetAccountBalanceAPI", {"account_number": account_number})

    def get_card_transactions(self, card_number: str, limit: int = 5):
        return self.invoke("GetCardTransactionsAPI", {"card_number": card_number, "limit": limit})

    def get_statement(self, account_number: str, period: str, date_from: Optional[str] = None, date_to: Optional[str] = None):
        return self.invoke(
            "GetStatementAPI",
            {"account_number": account_number, "period": period, "date_from": date_from, "date_to": date_to},
        )


banking_api_client = BankingApiClient()
