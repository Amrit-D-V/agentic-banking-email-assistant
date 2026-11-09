# API Specification

Base URL: `http://127.0.0.1:8000`. Interactive Swagger: `/docs`. All bodies are JSON unless noted.

## 1. Core banking APIs (mock CBS/CMS)

Each API is available in three equivalent forms. The agents choose one with `BANKING_API_TRANSPORT`.

| API (brief §4.6) | REST | MCP tool | Purpose |
|---|---|---|---|
| ValidateAccountAPI | `POST /api/v1/validate-account` | `validate_account` | Account exists and is active |
| ValidateCardAPI | `POST /api/v1/validate-card` | `validate_card` | Card exists and is active (masked input allowed) |
| GetAccountBalanceAPI | `POST /api/v1/account-balance` | `get_account_balance` | Available balance |
| GetCardTransactionsAPI | `POST /api/v1/card-transactions` | `get_card_transactions` | Last N transactions |
| GetStatementAPI | `POST /api/v1/statement` | `get_account_statement` | Statement reference and secure link |
| LookupCustomerByEmailAPI *(added)* | `POST /api/v1/customer-lookup` | `lookup_customer_by_email` | Registered customer for a sender email |
| Policy lookup *(added)* | – | `lookup_banking_policy` | RAG search over bank policies |

### ValidateAccountAPI
```json
// request
{"account_number": "1234567890"}
// response 200
{"status": "VALID", "customer_name": "John Doe", "customer_id": "CUST-1002",
 "account_type": "Savings", "message": "Account is active and verified in CBS."}
// unknown account -> 200
{"status": "INVALID", "customer_name": null, "customer_id": null, "account_type": null,
 "message": "Account number could not be found in banking records."}
```

### ValidateCardAPI
```json
{"card_number": "4567XXXX8901"}
{"status": "VALID", "customer_name": "John Doe", "customer_id": "CUST-1002",
 "card_type": "HDFC Millennia Credit Card", "message": "Credit card verified and active in CMS."}
```
Masked matching is strict: same length, and every unmasked digit must agree. `X` or `*` stand for unknown digits.

### GetAccountBalanceAPI
```json
{"account_number": "1234567890"}
{"account_number": "1234567890", "customer_name": "John Doe", "account_type": "Savings",
 "available_balance": 125000.0, "currency": "INR", "status": "ACTIVE"}
```

### GetCardTransactionsAPI
```json
{"card_number": "987654321", "limit": 3}
{"card_number": "987654321", "customer_name": "John Doe", "card_type": "HDFC Regalia Gold Credit Card",
 "count": 3, "transactions": [
   {"transaction_id": "TXN-321-01", "date": "2026-05-01", "merchant": "MakeMyTrip Flights",
    "amount": 18500.0, "currency": "INR", "type": "DEBIT"}]}
```

### GetStatementAPI
```json
{"account_number": "1234567890", "period": "April 2026", "date_from": "2026-04-01", "date_to": "2026-04-30"}
{"account_number": "1234567890", "customer_name": "John Doe", "period": "April 2026",
 "statement_id": "STMT-7890-2026-04-01_2026-04-30",
 "download_url": "https://netbanking.hdfc.internal/statements/download/STMT-7890-2026-04-01_2026-04-30.pdf",
 "generated_at": "2026-11-08 15:00:00 IST", "date_from": "2026-04-01", "date_to": "2026-04-30"}
```

### LookupCustomerByEmailAPI
```json
{"email": "john.doe@example.com"}
{"status": "FOUND", "customer_id": "CUST-1002", "customer_name": "John Doe", "primary_account": "1234567890"}
```

### Error contract

| Condition | REST | MCP tool payload | Client behaviour |
|---|---|---|---|
| Record not found | 404 `{"detail": ...}` | `{"error", "error_type": "NOT_FOUND", "transient": false}` | no retry |
| Core system outage | 503 | `{"error_type": "UNAVAILABLE", "transient": true}` | retry with backoff |
| Timeout | client-side | client-side | retry with backoff, then `TIMEOUT` |

### Test fixtures

| Value | Behaviour |
|---|---|
| Account `1234567890` | John Doe, INR 1,25,000 |
| Card `4567XXXX8901` (= `4567123456788901`) | John Doe, 6 transactions |
| Card `987654321` | John Doe, 3 transactions |
| Card `999999999` | not registered (Scenario 5) |
| Account `1234509876` | John Doe's second account, INR 48,250.75 (Scenario 15) |
| Account `9876543210` | Priya Sharma (`priya.sharma@example.com`) |
| Account `1111111111` | validates, data calls hang (timeout) |
| Account `2222222222` | validates, data calls return 503 |

## 2. Resilient client (`apis/api_client.py`)

`BankingApiClient.invoke(api_name, payload)` never raises. Validation and customer lookups are cached for
`API_CACHE_SECONDS` (the log shows `transport: "cache"`). A circuit breaker per API fails fast with
`error_type: "CIRCUIT_OPEN"` after repeated transient failures. It returns `(data, ApiCallResult)`:

```json
{"api_name": "GetAccountBalanceAPI", "endpoint": "/api/v1/account-balance", "status": "TIMEOUT",
 "request_payload": {"account_number": "1111111111"}, "error_message": "...timed out after 2.0s",
 "execution_time_ms": 6612.4, "attempts": 3, "transport": "inprocess"}
```

Settings:
- `API_TIMEOUT_SECONDS` (default 2)
- `API_MAX_RETRIES` (default 2)
- `API_RETRY_BACKOFF_SECONDS` (default 0.2, doubles each retry)

## 3. Pipeline APIs

### `POST /api/v1/process-email`
```json
{"sender": "john.doe@example.com", "subject": "Statement Request",
 "body": "Kindly send my bank statement for April 2026.", "attachment_paths": []}
```
Returns the full `AgentState`:
- `detected_intents`, `intent_confidences`
- `sentiment`, `urgency_flag`
- `entities` (with `sources`)
- `validation_summary`
- `api_plan`, `api_call_logs`, `api_results`
- `has_partial_failure`, `requires_human_review`, `review_reasons`
- `final_email_subject`, `masked_response`
- `execution_trace`, `total_execution_ms`

`attachment_paths` may only point inside `downloads/` or `sample_data/`. Anything else returns 400.

### `POST /api/v1/process-email-upload` (multipart)
Fields: `sender`, `subject`, `body`, plus `files` (repeatable; PDF, images or text, 10 MB each). Returns `AgentState`.

## 4. Operations & control plane (`/api/v1/ops`)

When `ADMIN_PASSWORD` is set, these endpoints, `/dashboard` and the two pipeline endpoints require HTTP Basic auth
(`ADMIN_USER` / `ADMIN_PASSWORD`). The mock core banking APIs in section 1 stay open, standing in for the bank's internal network.

| Method | Path | Purpose |
|---|---|---|
| GET | `/metrics` | KPIs, outcomes, latency percentiles, SLA, throughput, per-API stats, timeline, PII scan, recent activity |
| GET | `/health` | Live probes: CBS, MCP, Ollama, Tesseract, FAISS, audit store, email worker |
| GET | `/records/{email_id}` | Full masked audit record (decision trail) |
| GET | `/export` | Download all audit records as JSONL |
| GET / POST | `/config` | Read or change runtime settings: `LLM_PROVIDER`, `BANKING_API_TRANSPORT`, `HITL_ENABLED`, `ENFORCE_SENDER_OWNERSHIP`, `MOCK_FAILURE_RATE`, `API_TIMEOUT_SECONDS`, `API_MAX_RETRIES` (validated) |
| GET | `/scenarios` | Sample scenarios |
| POST | `/scenarios/{key}/run` | Run one scenario now |
| POST | `/run-all` | Background job: every scenario |
| POST | `/load-test` | Background job `{"count": 50, "concurrency": 8, "include_faults": false}` |
| GET | `/jobs` | Job progress and throughput |
| POST | `/probe-mcp` | Start or verify the MCP server and list its tools |
| GET / POST | `/worker`, `/worker/start`, `/worker/stop` | Live Gmail worker control |
| GET | `/reviews?status=PENDING_APPROVAL` | Review queue (no raw addresses) |
| POST | `/reviews/{id}/approve`, `/reviews/{id}/reject` | HITL decision; approve sends via SMTP for email-channel items |
| GET | `/failed` | Emails that crashed the pipeline (dead-letter list) |
| POST | `/failed/{id}/retry` | Re-run a failed email (sends the reply for Gmail emails) |
| POST | `/reset` | Clear audit records, review queue, failed list and jobs |

## 5. Prometheus metrics

`GET /metrics` (no auth) returns Prometheus text format: `email_processed_total{outcome}`, `email_latency_ms{stat}`,
`email_sla_compliance_ratio`, `core_banking_calls_total{api,status}`, `core_banking_circuit_open{api}`,
`llm_calls_total{result}`, `review_queue_pending`, `failed_emails_pending`, `email_worker_queue_depth`.

## 6. MCP server

```bash
python -m apis.mcp_banking_server      # stdio transport
```

Tools: `lookup_customer_by_email`, `validate_account`, `validate_card`, `get_account_balance`,
`get_card_transactions`, `get_account_statement`, `lookup_banking_policy`. Each returns a JSON string.

Claude Desktop / any MCP client config:
```json
{"mcpServers": {"core-banking": {"command": "python", "args": ["-m", "apis.mcp_banking_server"],
  "cwd": "/path/to/project-hdfc-interview"}}}
```
