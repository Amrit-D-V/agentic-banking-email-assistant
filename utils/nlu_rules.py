import calendar
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple


_NUMBER_TOKEN = re.compile(r"(?<![\w-])([0-9Xx*](?:[0-9Xx* -]{5,22})[0-9])(?![\w-])")

_KEYWORDS = {
    "card": re.compile(r"\b(credit\s+card|debit\s+card|card)\b", re.I),
    "account": re.compile(r"\b(account|a/c|acct|acc(?:\.|\s+no))\b", re.I),
    "ignore": re.compile(r"\b(phone|mobile|contact|call|whatsapp|pin\s*code|pincode|otp|ref(?:erence)?|ticket|cif)\b", re.I),
}

_WORD_NUMBERS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def _classify_number(text: str, start: int, token: str) -> Optional[str]:
    window = text[max(0, start - 60):start]
    best, best_pos = None, -1
    for label, rx in _KEYWORDS.items():
        for m in rx.finditer(window):
            if m.end() > best_pos:
                best, best_pos = label, m.end()
    if best == "ignore":
        return None
    if best:
        return best
    compact = re.sub(r"[ -]", "", token)
    if re.search(r"[Xx*]", compact) or len(compact) in (15, 16):
        return "card"
    if compact.isdigit() and 9 <= len(compact) <= 18:
        return "account"
    return None


def find_identifiers(text: str) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {"account": [], "card": []}
    for m in _NUMBER_TOKEN.finditer(text or ""):
        token = m.group(1).strip()
        compact = re.sub(r"[ -]", "", token)
        digits = re.sub(r"\D", "", compact)
        if len(digits) < 4 or len(compact) < 9 or len(compact) > 19:
            continue
        label = _classify_number(text, m.start(1), token)
        if label == "account" and not compact.isdigit():
            continue
        if label and compact not in found[label]:
            found[label].append(compact)
    return found


def extract_transaction_count(text: str) -> Optional[int]:
    m = re.search(r"\b(?:last|latest|recent|past|previous)\s+(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")\b"
                  r"(?:\s+\w+){0,3}?\s+(?:transactions?|txns?|purchases|spends?)", text or "", re.I)
    if not m:
        return None
    raw = m.group(1).lower()
    n = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
    return max(1, min(n, 50))


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _parse_date(s: str) -> Optional[date]:
    s = s.strip().rstrip(",.")
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s).replace(",", ""), fmt).date()
        except ValueError:
            continue
    return None


def extract_statement_period(text: str, today: Optional[date] = None) -> Optional[Dict[str, str]]:
    text = text or ""
    today = today or date.today()
    low = text.lower()

    date_pat = r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:" + _MONTH_RE + r")\.?,?\s+\d{4})"
    m = re.search(date_pat + r"\s*(?:to|till|until|and|-|–)\s*" + date_pat, text, re.I)
    if m:
        d1, d2 = _parse_date(m.group(1)), _parse_date(m.group(2))
        if d1 and d2 and d1 <= d2:
            return {"label": f"{d1:%d %b %Y} to {d2:%d %b %Y}", "date_from": d1.isoformat(), "date_to": d2.isoformat()}

    m = re.search(r"\b(" + _MONTH_RE + r")\.?\s*(?:to|till|until|-|–)\s*(" + _MONTH_RE + r")\.?,?\s+(\d{4})\b", low)
    if m:
        y = int(m.group(3))
        m1, m2 = MONTHS[m.group(1)], MONTHS[m.group(2)]
        if m1 <= m2:
            d1, _ = _month_bounds(y, m1)
            _, d2 = _month_bounds(y, m2)
            return {"label": f"{calendar.month_name[m1]} to {calendar.month_name[m2]} {y}",
                    "date_from": d1.isoformat(), "date_to": d2.isoformat()}

    m = re.search(r"\bq([1-4])\s*[-/ ]?\s*(\d{4})\b", low)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        d1, _ = _month_bounds(y, 3 * q - 2)
        _, d2 = _month_bounds(y, 3 * q)
        return {"label": f"Q{q} {y}", "date_from": d1.isoformat(), "date_to": d2.isoformat()}

    m = re.search(r"\bfy\s*(\d{4})\s*[-/]\s*(\d{2,4})\b", low)
    if m:
        y = int(m.group(1))
        return {"label": f"FY {y}-{str(y + 1)[-2:]}", "date_from": f"{y}-04-01", "date_to": f"{y + 1}-03-31"}

    m = re.search(r"\b(" + _MONTH_RE + r")\.?[\s,-]+(\d{4})\b", low)
    if m:
        mon, y = MONTHS[m.group(1)], int(m.group(2))
    else:
        m = re.search(r"(?<![\d/])(0?[1-9]|1[0-2])[/-](\d{4})\b", low)
        mon, y = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    if mon:
        d1, d2 = _month_bounds(y, mon)
        return {"label": f"{calendar.month_name[mon]} {y}", "date_from": d1.isoformat(), "date_to": d2.isoformat()}

    first_this_month = today.replace(day=1)
    if re.search(r"\b(last|previous|past)\s+month\b", low):
        d2 = first_this_month - timedelta(days=1)
        return {"label": f"{calendar.month_name[d2.month]} {d2.year}",
                "date_from": d2.replace(day=1).isoformat(), "date_to": d2.isoformat()}
    m = re.search(r"\b(?:last|previous|past)\s+(\d{1,2}|" + "|".join(_WORD_NUMBERS) + r")\s+months?\b", low)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _WORD_NUMBERS[m.group(1)]
        d2 = first_this_month - timedelta(days=1)
        y, mo = d2.year, d2.month - n + 1
        while mo <= 0:
            mo += 12
            y -= 1
        return {"label": f"Last {n} months", "date_from": date(y, mo, 1).isoformat(), "date_to": d2.isoformat()}
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days\b", low)
    if m:
        d1 = today - timedelta(days=int(m.group(1)))
        return {"label": f"Last {m.group(1)} days", "date_from": d1.isoformat(), "date_to": today.isoformat()}
    return None


_NOT_NAMES = {"hi", "hello", "dear", "sir", "madam", "team", "customer", "bank", "support", "please", "kindly",
              "thanks", "regards", "i", "my", "the", "account", "card", "statement", "balance"}


def is_plausible_name(value) -> bool:
    words = str(value or "").strip().split()
    return (1 <= len(words) <= 4 and len(str(value)) <= 40
            and all(re.fullmatch(r"[A-Z][a-zA-Z.'-]*", w) for w in words)
            and not any(w.lower().strip(".") in _NOT_NAMES for w in words))


def extract_customer_name(text: str) -> Optional[str]:
    m = re.search(r"\b(?:my name is|this is|i am|i'm)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})", text or "")
    if m and m.group(1).split()[0].lower() not in {"writing", "a", "an", "the", "very", "extremely", "not"}:
        return m.group(1)
    m = re.search(r"\b(?:regards|thanks|thank you|sincerely|best|cheers)[,!.]?\s*\n+\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*$",
                  (text or "").strip(), re.I)
    return m.group(1) if m else None


STRONG_INTENT_CUES = {
    "BALANCE_ENQUIRY": [
        r"(?<!minimum )(?<!average )(?<!min )(?<!monthly )\b(account|savings|available|current|my|the)\s+balance\b",
        r"\bbalance\s+(?:for|of|in|on)\s+(?:my\s+)?(?:account|a/c|savings)",
        r"\bhow much (?:money|balance|funds?)\b",
        r"\b(?:check|know|share|provide|send|tell)\b.{0,25}\bbalance\b",
        r"\bfunds? available\b",
        r"\bbalance\s+(check|enquiry|inquiry|request)\b",
    ],
    "CARD_TRANSACTIONS": [
        r"\bcard\b.{0,40}\b(transactions?|txns?|usage|spends?|spending|purchases)\b",
        r"\b(transactions?|txns?|usage|spends?|spending|purchases)\b.{0,40}\bcard\b",
        r"\bcredit\s+card\s+statement\b",
        r"\bcard\b.{0,40}\bstatement\b",
    ],
    "STATEMENT_REQUEST": [
        r"(?<!card )\b(bank|account|e-?)\s*statements?\b",
        r"\b(send|share|provide|need|want|email|mail|download|get)\b.{0,30}(?<!card )\bstatements?\b",
        r"\bpassbook\b",
    ],
    "POLICY_INQUIRY": [
        r"\b(minimum|average)\s+(monthly\s+)?balance\b",
        r"\b(charges?|fees?|penalt(y|ies)|interest rates?|policy|policies|rules|limit)\b",
        r"\b(dispute|chargeback|zero liability|report(?:ing)? fraud)\b",
        r"\bstatement password\b",
    ],
}

WEAK_INTENT_CUES = {
    "BALANCE_ENQUIRY": r"\b(balance|funds?|money)\b",
    "CARD_TRANSACTIONS": r"\b(card|transactions?|spends?|purchases)\b",
    "STATEMENT_REQUEST": r"\b(statements?|passbook)\b",
    "POLICY_INQUIRY": r"\b(charges?|fees?|penalt\w+|interest|policy|policies|rules?|limits?|minimum|dispute|fraud)\b",
}


def rule_analysis(text: str) -> Tuple[List[str], List[str]]:
    low = (text or "").lower()
    found = [intent for intent, pats in STRONG_INTENT_CUES.items() if any(re.search(p, low) for p in pats)]
    vetoed: List[str] = []
    if "CARD_TRANSACTIONS" in found and not re.search(r"(?<!card )\b(bank|account|e-?)\s*statements?\b", low):
        vetoed.append("STATEMENT_REQUEST")
    if "POLICY_INQUIRY" in found and re.search(r"\b(minimum|average)\s+(monthly\s+)?balance\b", low) \
            and not re.search(r"\b(my|available|current)\s+(account\s+)?balance\b(?!\s+(required|requirement))", low) \
            and not re.search(r"\bbalance\s+(for|of|in)\s+(my\s+)?(account|a/c)\s+\d", low):
        vetoed.append("BALANCE_ENQUIRY")
    return [i for i in found if i not in vetoed], vetoed


def rule_intents(text: str) -> List[str]:
    return rule_analysis(text)[0]


def intent_is_grounded(intent: str, text: str) -> bool:
    cue = WEAK_INTENT_CUES.get(intent)
    return bool(cue and re.search(cue, (text or "").lower()))


NEGATIVE_URGENT_CUES = [
    r"\burgent(ly)?\b", r"\bimmediately\b", r"\basap\b", r"\bright now\b", r"\bat the earliest\b",
    r"\bfrustrat\w*", r"\bangry\b", r"\bfurious\b", r"\bunacceptable\b", r"\bworst\b", r"\bterrible\b",
    r"\bdisappoint\w*", r"\bridiculous\b", r"\bpathetic\b", r"\bescalat\w*", r"\bombudsman\b",
    r"\bcomplain\w*", r"\bfraud\w*", r"\bunauthori[sz]ed\b", r"\bnot happy\b", r"\bstill (?:not|no)\b",
    r"\bno response\b", r"\blegal action\b", r"!{2,}",
]
POSITIVE_CUES = [r"\bthank(s| you)\b", r"\bappreciate\w*", r"\bgreat (service|help|job)\b", r"\bexcellent\b",
                 r"\bhappy with\b", r"\bgrateful\b", r"\bkudos\b"]


def rule_sentiment(text: str) -> Tuple[str, List[str]]:
    low = (text or "").lower()
    neg = [m.group(0) for p in NEGATIVE_URGENT_CUES if (m := re.search(p, low))]
    if neg:
        return "NEGATIVE_URGENT", neg
    pos = [m.group(0) for p in POSITIVE_CUES if (m := re.search(p, low))]
    if pos:
        return "POSITIVE", pos
    return "NEUTRAL", []
