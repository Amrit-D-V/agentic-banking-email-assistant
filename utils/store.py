import json
import threading
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    inspect,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from config.settings import settings

metadata = MetaData()

audit_records = Table(
    "audit_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email_id", String(64), index=True, nullable=False),
    Column("timestamp", String(32), index=True, nullable=False),
    Column("payload", Text, nullable=False),
)

review_items = Table(
    "review_items", metadata,
    Column("email_id", String(64), primary_key=True),
    Column("status", String(32), index=True, nullable=False),
    Column("queued_at", String(32), nullable=False),
    Column("payload", Text, nullable=False),
)

runtime_config = Table(
    "runtime_config", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
)

processed_messages = Table(
    "processed_messages", metadata,
    Column("message_id", String(255), primary_key=True),
    Column("email_id", String(64), nullable=False),
    Column("processed_at", String(32), nullable=False),
)

failed_emails = Table(
    "failed_emails", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("message_id", String(255), index=True),
    Column("failed_at", String(32), nullable=False),
    Column("status", String(16), index=True, nullable=False),
    Column("error", Text, nullable=False),
    Column("payload", Text, nullable=False),
)

_engines: Dict[str, Engine] = {}
_lock = threading.Lock()


def engine() -> Engine:
    url = settings.DATABASE_URL
    with _lock:
        if url not in _engines:
            kwargs: Dict[str, Any] = {"future": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
                settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
            eng = create_engine(url, **kwargs)
            _migrate(eng)
            _engines[url] = eng
        return _engines[url]


def _migrate(eng: Engine) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(settings.BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(settings.BASE_DIR / "migrations"))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "audit_records" in tables and "alembic_version" not in tables:
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")


def add_audit(record: Dict[str, Any]) -> None:
    with engine().begin() as conn:
        conn.execute(insert(audit_records).values(
            email_id=record["email_id"], timestamp=record["timestamp"], payload=json.dumps(record)))


def list_audit(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    q = select(audit_records.c.payload).order_by(audit_records.c.id.desc())
    if limit:
        q = q.limit(limit)
    with engine().connect() as conn:
        rows = [json.loads(r.payload) for r in conn.execute(q)]
    return list(reversed(rows))


def find_audit(email_id: str) -> Dict[str, Any]:
    q = select(audit_records.c.payload).where(audit_records.c.email_id == email_id).order_by(audit_records.c.id.desc()).limit(1)
    with engine().connect() as conn:
        row = conn.execute(q).first()
    return json.loads(row.payload) if row else {}


def iter_audit_jsonl() -> Iterator[str]:
    with engine().connect() as conn:
        for row in conn.execute(select(audit_records.c.payload).order_by(audit_records.c.id)):
            yield row.payload + "\n"


def add_review(item: Dict[str, Any]) -> None:
    with engine().begin() as conn:
        conn.execute(delete(review_items).where(review_items.c.email_id == item["email_id"]))
        conn.execute(insert(review_items).values(
            email_id=item["email_id"], status=item["status"], queued_at=item["queued_at"], payload=json.dumps(item)))


def list_reviews(status: Optional[str] = None) -> List[Dict[str, Any]]:
    q = select(review_items.c.payload).order_by(review_items.c.queued_at)
    if status:
        q = q.where(review_items.c.status == status)
    with engine().connect() as conn:
        return [json.loads(r.payload) for r in conn.execute(q)]


def decide_review(email_id: str, expected_status: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with engine().begin() as conn:
        row = conn.execute(select(review_items.c.payload, review_items.c.status)
                           .where(review_items.c.email_id == email_id)).first()
        if not row or row.status != expected_status:
            return None
        item = {**json.loads(row.payload), **changes}
        result = conn.execute(update(review_items)
                              .where(review_items.c.email_id == email_id, review_items.c.status == expected_status)
                              .values(status=item["status"], payload=json.dumps(item)))
        return item if result.rowcount == 1 else None


def save_config(values: Dict[str, Any]) -> None:
    with engine().begin() as conn:
        for key, value in values.items():
            conn.execute(delete(runtime_config).where(runtime_config.c.key == key))
            conn.execute(insert(runtime_config).values(key=key, value=json.dumps(value)))


def load_config() -> Dict[str, Any]:
    with engine().connect() as conn:
        return {r.key: json.loads(r.value) for r in conn.execute(select(runtime_config))}


def is_processed(message_id: Optional[str]) -> bool:
    if not message_id:
        return False
    with engine().connect() as conn:
        return conn.execute(select(processed_messages.c.message_id)
                            .where(processed_messages.c.message_id == message_id)).first() is not None


def mark_processed(message_id: Optional[str], email_id: str) -> None:
    if not message_id:
        return
    with engine().begin() as conn:
        conn.execute(delete(processed_messages).where(processed_messages.c.message_id == message_id))
        conn.execute(insert(processed_messages).values(
            message_id=message_id, email_id=email_id, processed_at=datetime.now().isoformat()))


def add_failed(message_id: Optional[str], error: str, payload: Dict[str, Any]) -> None:
    with engine().begin() as conn:
        conn.execute(insert(failed_emails).values(
            message_id=message_id, failed_at=datetime.now().isoformat(timespec="seconds"),
            status="FAILED", error=error[:2000], payload=json.dumps(payload, default=str)))


def list_failed(status: Optional[str] = "FAILED") -> List[Dict[str, Any]]:
    q = select(failed_emails).order_by(failed_emails.c.id.desc())
    if status:
        q = q.where(failed_emails.c.status == status)
    with engine().connect() as conn:
        return [{**dict(r._mapping), "payload": json.loads(r.payload)} for r in conn.execute(q)]


def set_failed_status(item_id: int, status: str, error: Optional[str] = None) -> None:
    values: Dict[str, Any] = {"status": status}
    if error:
        values["error"] = error[:2000]
    with engine().begin() as conn:
        conn.execute(update(failed_emails).where(failed_emails.c.id == item_id).values(**values))


def clear_activity() -> None:
    with engine().begin() as conn:
        conn.execute(delete(audit_records))
        conn.execute(delete(review_items))
        conn.execute(delete(failed_emails))


def healthcheck() -> str:
    with engine().connect() as conn:
        count = conn.execute(select(func.count()).select_from(audit_records)).scalar_one()
    backend = settings.DATABASE_URL.split(":", 1)[0]
    return f"{backend} · {count} audit records · checked {datetime.now():%H:%M:%S}"
