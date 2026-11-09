# Low-Level Design

## 1. Module map

```
agents/
  _context.py            shared helpers: attachment context, grounding source text
  email_agent.py         EmailUnderstandingAgent
  intent_agent.py        IntentClassificationAgent    (LLM + rules ensemble)
  sentiment_agent.py     SentimentAnalysisAgent       (escalation-biased ensemble)
  entity_agent.py        EntityExtractionAgent        (rules authoritative, LLM grounded)
  validation_agent.py    ValidationAgent              (parallel validate + ownership)
  api_selection_agent.py APISelectionAgent            (decision engine, parallel fetch, RAG)
  response_agent.py      ResponseGenerationAgent      (per-intent sections, HITL flags)
  audit_agent.py         AuditLoggingAgent            (database audit record + review queue)
  intent_registry.py     IntentHandler registry       (extensibility point)
apis/
  mock_banking_service.py  CBS/CMS data, strict card matching, fault injection
  api_client.py            BankingApiClient: ApiSpec table, transports, timeout/retry
  banking_api_server.py    FastAPI app: core APIs, pipeline APIs, pages
  mcp_banking_server.py    MCP tools
  mcp_client.py            persistent stdio MCP session on a background event loop
  operations.py            /api/v1/ops router (metrics, health, control, HITL)
  auth.py                  HTTP Basic login dependency (optional)
  prometheus.py            /metrics in Prometheus text format
  dashboard_ui.py          dashboard page
models/
  schemas.py             Pydantic models: EmailInput, ExtractedEntities, AgentState, API contracts, AuditRecord
  llm_client.py          Ollama client, JSON mode, fallback, health, stats
prompts/templates.py     intent, sentiment, entity prompts
utils/
  nlu_rules.py           identifiers, dates, counts, names, intent cues + vetoes, sentiment lexicon
  document_reader.py     PDF text / OCR, image OCR, content sniffing
  text_cleaner.py        email cleaning, language detection
  pii_masker.py          account/card/email masking, payload masking
  policy_rag.py          TF-IDF + FAISS index over knowledge_base/policies
  metrics.py             metrics from audit trail, outcome model, PII leak scan
  review_queue.py        human review queue (on the store)
  store.py               SQLAlchemy store: audit records, review items, settings, processed messages, failed emails
  evaluation.py          labelled-email evaluation (accuracy, per-intent P/R/F1)
  logging_config.py      rotating log with PII filter
workflows/orchestrator.py  LangGraph graph
email_worker.py            IMAP/SMTP channel
config/settings.py         pydantic-settings (env / .env)
```

## 2. State (`AgentState`)

| Field group | Fields | Written by |
|---|---|---|
| Input | `email` (sender, subject, body, attachment_paths, channel, received_at) | channel |
| Understanding | `cleaned_body`, `attachment_extracted_text`, `full_context` | Email agent |
| Intent | `detected_intents`, `intent_confidences` | Intent agent |
| Sentiment | `sentiment`, `urgency_flag`, `sentiment_reason` | Sentiment agent |
| Entities | `entities` (account, card, period, date_from/to, count, name, confidence, sources) | Entity agent |
| Validation | `validation_summary`, `customer_profile`, `has_partial_failure` | Validation agent |
| Orchestration | `api_plan`, `selected_apis`, `api_results`, `api_call_logs`, `retrieved_policies`, `errors` | Validation + API Selection |
| Output | `generated_response`, `masked_response`, `final_email_subject`, `requires_human_review`, `review_reasons` | Response agent |
| Trace | `execution_trace`, `start_time`, `total_execution_ms` | all / Audit |

The parallel branches write disjoint fields of the same object, and the graph uses a last-write
reducer on the single `state` channel.

## 3. Key algorithms

### 3.1 Identifier labelling (`find_identifiers`)
```
for each token matching [0-9Xx*][0-9Xx* -]{5,22}[0-9]:
    compact = remove spaces/hyphens; skip if < 9 or > 19 chars or < 4 digits
    window  = 60 chars before token
    label   = keyword whose match ends closest to the token among
              card | account (a/c, acct) | ignore (phone, mobile, otp, ref, ticket, cif)
    if label == ignore: skip
    if no keyword: masked or 15/16 chars -> card; 9-18 digits -> account
    accounts must be all digits
return ordered lists {account: [...], card: [...]}
```

### 3.2 Intent ensemble
```
rules, vetoed = rule_analysis(text)          # strong cues + veto list
llm = LLM intents (enum-valid, not GENERAL)
for intent in rules ∪ llm:
    both            -> 0.97
    rules only      -> 0.80 (LLM ran) / 0.85 (no LLM)
    vetoed          -> drop
    llm + weak cue  -> min(llm_conf, 0.70)
    else            -> drop (ungrounded)
empty -> GENERAL_INQUIRY
```

### 3.3 Per-intent partial failure
```
served[i] = any(validation[entity] == VALID for entity in handler[i].entity_options)
overall_valid = all(served);  partial = any(served) and not all(served)
# after fetch, Response agent recomputes using API outcomes (an outage also makes it partial)
```

### 3.4 Resilient invoke
```
for attempt in 1..(1+MAX_RETRIES):
    try: data = transport(spec, payload, timeout); return SUCCESS
    except Timeout:            err = TIMEOUT (transient)
    except ApiError e:         err = e (transient if 5xx/UNAVAILABLE)
    if not transient: break
    sleep(BACKOFF * 2^(attempt-1))
return {"error", "error_type"}, ApiCallResult(status=TIMEOUT|FAILED, attempts)
```
In-process calls run on a bounded thread pool so they are timed out like remote calls.
MCP calls use `run_coroutine_threadsafe(...).result(timeout)` on the client's event loop.

### 3.5 Outcome model (dashboard)

| Outcome | Rule |
|---|---|
| ROUTED | only `GENERAL_INQUIRY` |
| PARTIAL | `has_partial_failure` |
| FAILED | any data API not SUCCESS, or a validation UNAVAILABLE |
| RESOLVED | validation VALID or not applicable (policy answers) |
| NEEDS_INFO | otherwise (missing, invalid or not-owned details) |

Automation rate = (RESOLVED + PARTIAL) / total.

## 4. Concurrency
- Gmail worker: one poller thread enqueues new emails; `WORKER_CONCURRENCY` consumer threads process them. Each Gmail `Message-ID` is recorded after the reply (idempotency); crashes go to `failed_emails`.
- LangGraph superstep: intent, sentiment and entity nodes run concurrently in its executor.
- Validation stage: `ThreadPoolExecutor` with one worker per call.
- Fetch stage: `ThreadPoolExecutor` with one worker per selected API.
- MCP: one session shared across threads; the protocol multiplexes requests by id.
- Audit records, review items and settings go through SQLAlchemy transactions; review decisions use a conditional update, so an item can only be decided once.

## 5. Configuration (`config/settings.py`, env or `.env`)

| Key | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `mock` = rule engine only |
| `OLLAMA_MODEL` | `llama3.2:3b` | any Ollama model |
| `DATABASE_URL` | SQLite in `logs/` | e.g. `postgresql+psycopg://user:pass@host/db` |
| `REQUIRE_REGISTERED_SENDER` | true | account data only for registered (and SPF/DKIM-verified) senders |
| `MAX_ENTITIES_PER_EMAIL` | 5 | accounts / cards handled per email |
| `TRANSLATE_NON_ENGLISH` | true | translate before analysis |
| `LLM_PERSONALISED_OPENING` | false | LLM opening line (guarded; off after testing) |
| `ADMIN_USER` / `ADMIN_PASSWORD` | admin / – | optional login for dashboard and control APIs |
| `WORKER_CONCURRENCY` / `WORKER_BATCH_SIZE` | 4 / 20 | Gmail worker: queue consumers / emails per poll |
| `API_CACHE_SECONDS` | 60 | cache for validation and customer lookups |
| `CIRCUIT_FAILURE_THRESHOLD` / `CIRCUIT_RESET_SECONDS` | 5 / 30 | circuit breaker |
| `NLU_SINGLE_CALL` | false | one combined LLM call instead of three (tested: slower and less accurate) |
| `BANKING_API_TRANSPORT` | `inprocess` | `http` or `mcp` |
| `API_TIMEOUT_SECONDS` / `API_MAX_RETRIES` | 2 / 2 | resilience |
| `MOCK_FAILURE_RATE` | 0.0 | chaos testing |
| `HITL_ENABLED` | false | hold flagged replies |
| `HITL_CONFIDENCE_THRESHOLD` | 0.8 | review below this |
| `ENFORCE_SENDER_OWNERSHIP` | true | sender must own quoted account/card |
| `DEMO_CUSTOMER_EMAIL` | `john.doe@example.com` | email treated as John Doe (set to your Gmail for live demos) |
| `RESPONSE_SLA_MS` | 10000 | SLA line on dashboard |
| `EMAIL_USER` / `EMAIL_PASS` | – | Gmail + app password |

## 6. Testing (`tests/`, 123 tests, about 10 s)

| File | Covers |
|---|---|
| `test_scenarios.py` | Scenarios 1–5 verbatim, order independence, urgent, missing, policy, unsupported, timeout, outage, ownership, name privacy, default period, audit masking; `--llm` parity tests against live LLaMA |
| `test_nlu_rules.py` | identifier labelling, counts, date ranges, intent cues and vetoes, sentiment, names |
| `test_resilience.py` | timeout/retry, transient vs permanent, chaos, REST transport, real MCP subprocess |
| `test_attachments.py` | image OCR, scanned PDF OCR, content sniffing, path traversal, email attachment download |
| `test_api_server.py` | REST, upload, path restriction, HTTP error mapping, ops config, metrics, drill-down, HITL flow, health, reset |
| `test_new_features.py` | several accounts/cards, registered-sender rule, SPF/DKIM verdicts, translation and its guardrail, LLM opening guardrail, unique ids, settings persistence, export, login, concurrent worker |
| `test_quality_scalability.py` | circuit breaker, cache, agent timings, idempotency, failed list + retry, queue consumers, Prometheus, migrations, accuracy regression |
| `test_mock_banking_service.py`, `test_mcp_server.py`, `test_pii_masker.py`, `test_policy_rag.py` | units |
