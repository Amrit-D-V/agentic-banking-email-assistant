from datetime import datetime
from typing import Any, Dict, List, Optional

from utils import store

PENDING = "PENDING_APPROVAL"
AUTO_RELEASED = "AUTO_RELEASED"
APPROVED = "APPROVED"
REJECTED = "REJECTED"


def add(entry: Dict[str, Any]) -> None:
    store.add_review(entry)


def list_items(status: Optional[str] = None) -> List[Dict[str, Any]]:
    return store.list_reviews(status)


def decide(email_id: str, approve: bool, reviewer: str = "ops-dashboard", note: str = "") -> Optional[Dict[str, Any]]:
    return store.decide_review(email_id, PENDING, {
        "status": APPROVED if approve else REJECTED,
        "decided_by": reviewer,
        "decided_at": datetime.now().isoformat(),
        "note": note,
    })
