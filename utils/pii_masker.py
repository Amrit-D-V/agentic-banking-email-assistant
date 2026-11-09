import re
from typing import Optional


def mask_account_number(account_number: Optional[str]) -> str:
    if not account_number:
        return "N/A"
    
    clean_num = re.sub(r"\D", "", account_number)
    if len(clean_num) <= 4:
        return f"XXXX{clean_num}"
    
    return f"XXXX{clean_num[-4:]}"


def mask_card_number(card_number: Optional[str]) -> str:
    if not card_number:
        return "N/A"
    
    cleaned = card_number.replace(" ", "").replace("-", "")
    
    if "X" in cleaned or "x" in cleaned:
        digits_only = re.sub(r"\D", "", cleaned)
        last_4 = digits_only[-4:] if len(digits_only) >= 4 else "XXXX"
        return f"XXXX-XXXX-XXXX-{last_4}"

    digits = re.sub(r"\D", "", cleaned)
    if len(digits) >= 12:
        return f"{digits[:4]}-XXXX-XXXX-{digits[-4:]}"
    elif len(digits) >= 4:
        return f"XXXX-XXXX-XXXX-{digits[-4:]}"
    else:
        return "XXXX-XXXX-XXXX-XXXX"


def mask_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return "N/A"
    
    user_part, domain = email.split("@", 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + "***"
    else:
        masked_user = user_part[0] + "***" + user_part[-1]
    return f"{masked_user}@{domain}"


def mask_text_pii(text: str) -> str:
    if not text:
        return ""
    
    card_pattern = r"\b(?:\d{4}[ -]?){3}\d{4}\b"
    text = re.sub(card_pattern, lambda m: mask_card_number(m.group(0)), text)
    
    acct_pattern = r"\b\d{9,18}\b"
    text = re.sub(acct_pattern, lambda m: mask_account_number(m.group(0)), text)
    
    return text


_SENSITIVE_KEYS = {"account_number": mask_account_number, "card_number": mask_card_number, "email": mask_email}


def mask_payload(payload):
    if not isinstance(payload, dict):
        return payload
    return {k: (_SENSITIVE_KEYS[k](v) if k in _SENSITIVE_KEYS and v else v) for k, v in payload.items()}
