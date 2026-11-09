import argparse
import email
import imaplib
import logging
import queue
import re
import smtplib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import settings
from models.schemas import EmailInput
from utils import store
from utils.text_cleaner import clean_email_text

log = logging.getLogger("EmailWorker")

AUTOMATED_SENDER_KEYWORDS = [
    "no-reply", "noreply", "notification", "newsletter", "mailer-daemon",
    "welcome@", "updates@", "news@", "marketing@", "promo@", "alerts@",
]


def decode_mime(val: str | bytes | None) -> str:
    if not val:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="ignore")
    return "".join(
        chunk.decode(enc or "utf-8", errors="ignore") if isinstance(chunk, bytes) else str(chunk)
        for chunk, enc in decode_header(val)
    )


def sender_verdict(msg: email.message.Message) -> Optional[bool]:
    results = " ".join(msg.get_all("Authentication-Results") or []).lower()
    if not results:
        return None
    if "dmarc=fail" in results:
        return False
    if "dkim=pass" in results or "spf=pass" in results:
        return True
    if "dkim=fail" in results or "spf=fail" in results or "spf=softfail" in results:
        return False
    return None


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:120] or "attachment"


class EmailWorker:
    def __init__(
        self,
        user: str = settings.EMAIL_USER,
        pwd: str = settings.EMAIL_PASS,
        imap_host: str = settings.IMAP_HOST,
        smtp_host: str = settings.SMTP_HOST,
        smtp_port: int = settings.SMTP_PORT,
        attach_dir: Path = settings.ATTACHMENTS_DIR,
    ):
        self.user = user
        self.pwd = pwd
        self.imap_host = imap_host
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.attach_dir = Path(attach_dir)
        self.attach_dir.mkdir(parents=True, exist_ok=True)
        self.seen_message_ids: set[str] = set()
        self.stop_event = threading.Event()
        self.inbox_queue: "queue.Queue[tuple[str, EmailInput]]" = queue.Queue()
        self._queued: set[str] = set()
        self._status_lock = threading.Lock()
        self.status: Dict[str, Any] = {
            "running": False, "mailbox": user, "started_at": None, "last_poll": None,
            "polls": 0, "processed": 0, "replied": 0, "held_for_review": 0, "skipped_automated": 0,
            "skipped_duplicates": 0, "failed": 0, "queue_depth": 0,
            "last_error": None,
        }

    @property
    def configured(self) -> bool:
        return bool(self.user and self.pwd)

    def connect_imap(self) -> imaplib.IMAP4_SSL:
        srv = imaplib.IMAP4_SSL(self.imap_host, 993, timeout=15)
        srv.login(self.user, self.pwd)
        srv.select("INBOX")
        return srv

    def parse_msg(self, raw: bytes) -> EmailInput:
        msg = email.message_from_bytes(raw)
        raw_sender = decode_mime(msg.get("From"))
        _, clean_sender = parseaddr(raw_sender)
        subj = decode_mime(msg.get("Subject"))
        body, html_body, paths = "", "", []

        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            fname = part.get_filename()

            if fname:
                fpath = self.attach_dir / f"{int(time.time() * 1000)}_{safe_filename(decode_mime(fname))}"
                fpath.write_bytes(part.get_payload(decode=True) or b"")
                paths.append(str(fpath))
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            if ctype == "text/plain" and "attachment" not in disp and not body:
                body = payload.decode(charset, errors="ignore")
            elif ctype == "text/html" and "attachment" not in disp and not html_body:
                html_body = payload.decode(charset, errors="ignore")

        return EmailInput(
            sender=clean_sender or raw_sender,
            subject=subj,
            body=body or clean_email_text(html_body) or subj,
            attachment_paths=paths,
            channel="email",
            sender_verified=sender_verdict(msg),
            message_id=(msg.get("Message-ID") or "").strip() or None,
        )

    def send_reply(self, to_addr: str, subj: str, body: str) -> None:
        msg = MIMEMultipart()
        msg["From"] = f"Customer Support <{self.user}>"
        msg["To"] = to_addr
        msg["Subject"] = subj
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as srv:
            srv.starttls()
            srv.login(self.user, self.pwd)
            srv.send_message(msg)

    def is_automated_email(self, msg: email.message.Message, sender: str) -> bool:
        if msg.get("List-Unsubscribe") or msg.get("Precedence", "").lower() in ["bulk", "junk", "list"]:
            return True
        return any(kw in sender.lower() for kw in AUTOMATED_SENDER_KEYWORDS)

    def fetch_unseen(self, batch_size: Optional[int] = None) -> list[tuple[str, EmailInput]]:
        batch_size = batch_size or settings.WORKER_BATCH_SIZE
        srv = self.connect_imap()
        try:
            _, data = srv.search(None, "UNSEEN")
            unhandled = [mid for mid in data[0].split() if mid.decode() not in self.seen_message_ids]
            emails = []
            for mid in unhandled[-batch_size:]:
                try:
                    _, msg_data = srv.fetch(mid, "(BODY.PEEK[])")
                    raw = next(part[1] for part in msg_data if isinstance(part, tuple))
                    mail = self.parse_msg(raw)
                    if self.is_automated_email(email.message_from_bytes(raw), mail.sender):
                        self.seen_message_ids.add(mid.decode())
                        self.status["skipped_automated"] += 1
                        continue
                    emails.append((mid.decode(), mail))
                except Exception as e:
                    log.warning("IMAP fetch error for message %s: %s", mid, e)
            return emails
        finally:
            srv.close()
            srv.logout()

    def mark_seen(self, mid: str) -> None:
        try:
            srv = self.connect_imap()
            srv.store(mid, "+FLAGS", "\\Seen")
            srv.close()
            srv.logout()
        except Exception as e:
            log.warning("IMAP flag error: %s", e)
        self.seen_message_ids.add(mid)

    def _handle(self, mid: str, mail: EmailInput) -> None:
        from workflows.orchestrator import orchestrator

        try:
            if store.is_processed(mail.message_id):
                with self._status_lock:
                    self.status["skipped_duplicates"] += 1
                self.mark_seen(mid)
                return
            state = orchestrator.process_email(mail)
            held = settings.HITL_ENABLED and state.requires_human_review
            if held:
                log.info("Held reply to %s for review: %s", mail.email_id, state.review_reasons)
            else:
                self.send_reply(mail.sender, state.final_email_subject, state.masked_response)
            store.mark_processed(mail.message_id, mail.email_id)
            self.mark_seen(mid)
            with self._status_lock:
                self.status["processed"] += 1
                self.status["held_for_review" if held else "replied"] += 1
        except Exception as e:
            store.add_failed(mail.message_id, f"{type(e).__name__}: {e}", mail.model_dump(mode="json"))
            self.mark_seen(mid)
            with self._status_lock:
                self.status["failed"] += 1
                self.status["last_error"] = f"{mail.email_id}: {e}"
            log.exception("Failed to process %s; moved to failed list", mail.email_id)
        finally:
            self._queued.discard(mid)

    def poll_once(self) -> int:
        self.status["last_poll"] = datetime.now().isoformat(timespec="seconds")
        self.status["polls"] += 1
        new = [(mid, mail) for mid, mail in self.fetch_unseen() if mid not in self._queued]
        for mid, mail in new:
            self._queued.add(mid)
            self.inbox_queue.put((mid, mail))
        self.status["queue_depth"] = self.inbox_queue.qsize()
        return len(new)

    def _consume(self) -> None:
        while not self.stop_event.is_set():
            try:
                mid, mail = self.inbox_queue.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._handle(mid, mail)
            finally:
                self.inbox_queue.task_done()
                self.status["queue_depth"] = self.inbox_queue.qsize()

    def process_pending(self) -> int:
        count = self.poll_once()
        pending = []
        while not self.inbox_queue.empty():
            pending.append(self.inbox_queue.get_nowait())
            self.inbox_queue.task_done()
        if pending:
            with ThreadPoolExecutor(max_workers=max(1, min(settings.WORKER_CONCURRENCY, len(pending)))) as pool:
                list(pool.map(lambda item: self._handle(*item), pending))
        self.status["queue_depth"] = 0
        return count

    def watch(self, interval: int = 8) -> None:
        self.stop_event.clear()
        self.status.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"), last_error=None)
        consumers = [threading.Thread(target=self._consume, name=f"email-consumer-{i}", daemon=True)
                     for i in range(max(1, settings.WORKER_CONCURRENCY))]
        try:
            srv = self.connect_imap()
            _, data = srv.search(None, "UNSEEN")
            self.seen_message_ids = {mid.decode() for mid in data[0].split()}
            srv.close()
            srv.logout()
            log.info("Watching %s (ignoring %d older unread messages)", self.user, len(self.seen_message_ids))
            for t in consumers:
                t.start()
            while not self.stop_event.is_set():
                try:
                    self.poll_once()
                except Exception as err:
                    self.status["last_error"] = str(err)
                    log.warning("Worker poll error: %s", err)
                self.stop_event.wait(interval)
        except Exception as err:
            self.status["last_error"] = str(err)
            log.error("Email worker stopped: %s", err)
        finally:
            self.stop_event.set()
            self.status["running"] = False

    def start_background(self, interval: int = 8) -> Optional[str]:
        if not self.configured:
            return "EMAIL_USER / EMAIL_PASS are not set in .env"
        if self.status["running"]:
            return None
        threading.Thread(target=self.watch, args=(interval,), name="email-worker", daemon=True).start()
        return None

    def stop(self) -> None:
        self.stop_event.set()


email_worker = EmailWorker()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--poll", action="store_true")
    p.add_argument("--interval", type=int, default=8)
    args = p.parse_args()
    if args.poll:
        email_worker.watch(args.interval)
    else:
        print(f"Single pass complete: {email_worker.process_pending()} processed")
