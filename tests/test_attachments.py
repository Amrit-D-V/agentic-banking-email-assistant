from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest

from email_worker import EmailWorker, safe_filename
from sample_data.sample_emails import fresh_copy
from utils.document_reader import OCR_AVAILABLE, extract_text_from_attachment
from workflows.orchestrator import orchestrator

needs_ocr = pytest.mark.skipif(not OCR_AVAILABLE, reason="tesseract-ocr not installed")


@needs_ocr
def test_image_ocr():
    text = extract_text_from_attachment("sample_data/attachments/service_request_form.png")
    assert "1234567890" in text and "4567XXXX8901" in text


@needs_ocr
def test_scanned_pdf_falls_back_to_ocr():
    text = extract_text_from_attachment("sample_data/attachments/scanned_statement_request.pdf")
    assert "[OCR]" in text and "March 2026" in text


@needs_ocr
def test_image_attachment_end_to_end():
    state = orchestrator.process_email(fresh_copy("scenario_13_image_attachment"))
    assert state.entities.account_number == "1234567890"
    assert state.entities.credit_card_number == "4567XXXX8901"
    assert state.entities.transaction_count == 4
    assert set(state.selected_apis) == {"GetAccountBalanceAPI", "GetCardTransactionsAPI"}


@needs_ocr
def test_scanned_pdf_end_to_end():
    state = orchestrator.process_email(fresh_copy("scenario_14_scanned_pdf"))
    assert state.entities.statement_period == "March 2026"
    assert "GetStatementAPI" in state.selected_apis


def test_image_detected_by_content_not_extension(tmp_path):
    src = Path("sample_data/attachments/service_request_form.png")
    renamed = tmp_path / "scan.bin"
    renamed.write_bytes(src.read_bytes())
    text = extract_text_from_attachment(str(renamed))
    assert "Unsupported" not in text


def test_missing_and_unsupported_attachments(tmp_path):
    assert "not found" in extract_text_from_attachment(str(tmp_path / "nope.pdf"))
    junk = tmp_path / "data.xyz"
    junk.write_bytes(b"\x00\x01garbage")
    assert "Unsupported" in extract_text_from_attachment(str(junk))


def test_safe_filename_blocks_path_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..\\..\\win.ini") == "win.ini"
    assert "/" not in safe_filename("a/b/c d.pdf")


def test_email_worker_downloads_attachments_safely(tmp_path):
    msg = MIMEMultipart()
    msg["From"] = "John Doe <john.doe@example.com>"
    msg["Subject"] = "Form attached"
    msg.attach(MIMEText("Please see attached.", "plain"))
    part = MIMEApplication(Path("sample_data/attachment_sample.txt").read_bytes(), Name="x.txt")
    part["Content-Disposition"] = 'attachment; filename="../../evil.txt"'
    msg.attach(part)

    worker = EmailWorker(user="", pwd="", attach_dir=tmp_path)
    mail = worker.parse_msg(msg.as_bytes())
    assert mail.sender == "john.doe@example.com"
    assert mail.channel == "email"
    assert len(mail.attachment_paths) == 1
    saved = Path(mail.attachment_paths[0])
    assert saved.parent == tmp_path and saved.name.endswith("evil.txt")
