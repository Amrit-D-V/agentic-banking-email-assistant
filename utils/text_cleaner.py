import re
from typing import Tuple


def clean_email_text(raw_text: str) -> str:
    if not raw_text:
        return ""

    cleaned = re.sub(r"<[^>]+>", " ", raw_text)

    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")

    disclaimer_markers = [
        "--- Original Message ---",
        "Disclaimer:",
        "This e-mail is confidential",
        "Sent from my iPhone",
        "Sent from my Android",
        "Sent from Outlook",
        "Confidentiality Notice:",
    ]
    for marker in disclaimer_markers:
        idx = cleaned.find(marker)
        if idx != -1:
            cleaned = cleaned[:idx]

    lines = [line.strip() for line in cleaned.split("\n")]
    filtered_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                filtered_lines.append("")
                prev_empty = True
        else:
            filtered_lines.append(line)
            prev_empty = False

    cleaned_text = "\n".join(filtered_lines).strip()
    return cleaned_text


SCRIPTS = [
    ("hi", r"[\u0900-\u097F]"),
    ("bn", r"[\u0980-\u09FF]"),
    ("pa", r"[\u0A00-\u0A7F]"),
    ("gu", r"[\u0A80-\u0AFF]"),
    ("ta", r"[\u0B80-\u0BFF]"),
    ("te", r"[\u0C00-\u0C7F]"),
    ("kn", r"[\u0C80-\u0CFF]"),
    ("ml", r"[\u0D00-\u0D7F]"),
]
HINGLISH_MARKERS = {"mera", "meri", "mere", "mujhe", "khata", "khate", "bataiye", "batao", "kripya", "chahiye",
                    "kya", "hai", "hain", "nahi", "aur", "kar", "dijiye", "bhejiye", "bhej", "pichle", "mahine"}


def detect_language(text: str) -> Tuple[str, float]:
    if not text:
        return ("en", 1.0)
    letters = len(re.findall(r"[^\W\d_]", text)) or 1
    for code, pattern in SCRIPTS:
        hits = len(re.findall(pattern, text))
        if hits > 5 and hits / letters > 0.2:
            return (code, round(min(0.99, 0.6 + hits / letters / 2), 2))
    words = set(re.findall(r"[a-z]+", text.lower()))
    if len(words & HINGLISH_MARKERS) >= 3:
        return ("hi", 0.7)
    return ("en", 0.98)
