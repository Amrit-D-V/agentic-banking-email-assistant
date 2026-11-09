# Assumptions and Limitations

## Assumptions (from brief §14, and decisions made)

1. **Core banking is mocked.** `apis/mock_banking_service.py` holds fixture customers, accounts, cards and transactions. Contracts follow brief §11 and are extended with `customer_id`.
2. **Who may receive account data.** Only emails from an address registered with the bank (`LookupCustomerByEmailAPI`) get account or card data, and the quoted account or card must belong to that customer. The live Gmail worker also reads Gmail's `Authentication-Results` header: a DMARC/DKIM/SPF failure is treated as unregistered, even if the address is registered. Policy questions are answered for anyone. `REQUIRE_REGISTERED_SENDER=false` switches to open mode for demos.
3. **Statements go to the registered email.** That is why a statement request with no account number (Scenario 3, verbatim) uses the sender's registered primary account, while a balance request without an account number asks for it.
4. **No statement period given** means the last full calendar month before the email was received. The reply says so explicitly.
5. **Transaction count defaults to 5** when not stated, and is capped at 50.
6. **Up to 5 accounts and 5 cards per email** (`MAX_ENTITIES_PER_EMAIL`). Each one is validated and fetched independently, so one invalid card doesn't affect the others.
7. **Replies are templated from verified data.** Figures, transactions and links always come from bank APIs. An optional LLM-written opening line exists (`LLM_PERSONALISED_OPENING`), but it is **off by default** after testing: even with guardrails, LLaMA 1B and 3B produced lines such as "your balance will be updated shortly" and "we are investigating the outage", which are false statements a bank can't send. Lines with numbers, links, amounts or promise words are rejected automatically.
8. **Non-English emails** (Hindi and other Indian scripts, and Romanised Hindi) are translated to English by LLaMA before analysis. A translation is only used if it keeps every number from the original and isn't a refusal; otherwise the email is analysed as-is and flagged for human review. Replies are in English.
9. **Email server integration** is real: Gmail IMAP/SMTP with an app password.

## Limitations and how production would address them

| Area | Current | Production |
|---|---|---|
| LLM | LLaMA 3.2 **3B** locally (1–3 s per email on a laptop, median 2.9 s on the evaluation set). It translated the Hindi test email correctly where 1B refused | LLaMA 3.1 8B / 70B on vLLM or TGI with replicas; set with `OLLAMA_MODEL` |
| Throughput | In-process queue with `WORKER_CONCURRENCY` (4) consumer threads; one local Ollama instance (parallel requests enabled in docker-compose) | Kafka/SQS feeding horizontally scaled worker deployments, plus vLLM/TGI with replicas |
| Async I/O | Synchronous agents with thread pools | Async LangGraph nodes and async HTTP/MCP clients (roadmap) |
| Tracing | Per-agent timings per email + Prometheus `/metrics` | OpenTelemetry distributed tracing, Grafana dashboards |
| Storage | SQLAlchemy store: SQLite by default, **PostgreSQL** via `DATABASE_URL` (docker-compose runs one) | Managed PostgreSQL; WORM retention for audit records |
| Policy RAG | TF-IDF + FAISS over 4 markdown documents | Embedding model + vector DB with document versioning |
| OCR | Tesseract (English) | More languages via `OCR_LANGUAGES`, or a document-AI service for handwriting and tables |
| Translation | LLaMA translation with a number-preserving guardrail; replies in English | Dedicated translation model; reply in the customer's language |
| Dashboard login | HTTP Basic auth with one admin user (`ADMIN_USER` / `ADMIN_PASSWORD`); reviewer recorded on approvals | SSO / RBAC with per-user roles |
| Runtime settings | Saved in the database and restored on restart | Central config service with change history |
| Voice channel (optional in brief) | Not built: it needs a speech-to-text model (e.g. Whisper), outside a laptop demo | Speech-to-text in front of the same pipeline; the agents are channel-independent |
| LlamaIndex (suggested in brief) | Not used: LangGraph handles orchestration, and the policy corpus is small enough for FAISS directly | LlamaIndex for document ingestion if the policy corpus grows |
| Attachments | 10 MB upload limit, filename sanitising, allowed folders | Malware scanning, object storage, retention policy |
| Email formats | Plain text and HTML bodies; common attachment types | S/MIME, `.msg`, archives |

## Known edge cases
- A 10-digit number after "account" is always treated as an account, even if the customer mistyped a phone number there.
- "My card statement" is treated as a card-transactions request, not an account statement (rule veto). Account statements need "bank/account/e-statement" wording.
- The small model sometimes misses unusual phrasing. Rule cues catch the explicit wording, and LLM-only intents are capped at 0.7 confidence and sent for human review.
