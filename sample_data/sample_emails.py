from typing import Dict, List

from config.settings import settings
from models.schemas import EmailInput

REGISTERED_SENDER = settings.DEMO_CUSTOMER_EMAIL or "john.doe@example.com"
UNKNOWN_SENDER = "new.customer@example.com"
OTHER_CUSTOMER = "priya.sharma@example.com"


def _mail(key: str, subject: str, body: str, sender: str = REGISTERED_SENDER, **kw) -> EmailInput:
    return EmailInput(email_id=f"EML-{key.upper()}", sender=sender, subject=subject, body=body, channel="demo", **kw)


SAMPLE_EMAILS: Dict[str, EmailInput] = {
    "scenario_1_balance": _mail(
        "S1", "Enquiry: Savings Account Balance",
        "Please provide my savings account balance for account number 1234567890."),
    "scenario_2_card_transactions": _mail(
        "S2", "Credit Card Transactions Request",
        "Please share my last 5 credit card transactions for card 4567XXXX8901."),
    "scenario_3_statement": _mail(
        "S3", "Statement Request",
        "Kindly send my bank statement for April 2026."),
    "scenario_4_multi_intent": _mail(
        "S4", "Account balance and credit card transactions",
        "Please share my account balance for account 1234567890 and also send last 3 transactions of my credit card 987654321."),
    "scenario_5_partial_failure": _mail(
        "S5", "Account balance and card transactions check",
        "Please provide balance for account 1234567890 and card transactions for card 999999999."),

    "scenario_6_urgent_escalation": _mail(
        "S6", "URGENT: Immediate balance check needed - Portal is down!",
        "This is extremely frustrating. Your mobile app is down and I have an urgent payment due. Provide my savings "
        "balance for account 1234567890 right now or I will escalate to the banking ombudsman!"),
    "scenario_7_missing_details": _mail(
        "S7", "Please tell me my balance",
        "Hi, I want to know how much balance is left in my savings account. Please reply quickly."),
    "scenario_8_policy_query": _mail(
        "S8", "Query regarding Minimum Average Balance and penalty charges",
        "What is the minimum balance required for my savings account in metro branches and what are the penalty "
        "charges if balance falls below it?"),
    "scenario_9_unsupported": _mail(
        "S9", "Home loan",
        "I would like to apply for a home loan of 40 lakhs. What documents do I need to submit?"),

    "scenario_10_api_timeout": _mail(
        "S10", "Balance enquiry",
        "Please share the balance of account 1111111111."),
    "scenario_11_api_outage": _mail(
        "S11", "Balance and card usage",
        "Please share the balance of account 2222222222 and the last 2 transactions for card 4567XXXX8901."),

    "scenario_12_ownership_mismatch": _mail(
        "S12", "Balance please",
        "Please send the balance for account 1234567890.", sender=OTHER_CUSTOMER),

    "scenario_13_image_attachment": _mail(
        "S13", "Request form attached",
        "Please process the attached service request form.",
        attachment_paths=["sample_data/attachments/service_request_form.png"]),
    "scenario_14_scanned_pdf": _mail(
        "S14", "Scanned request",
        "Hello, please see the attached scanned letter.",
        attachment_paths=["sample_data/attachments/scanned_statement_request.pdf"]),
    "scenario_15_multiple_accounts": _mail(
        "S15", "Balances for both my accounts",
        "Please share the balance of account 1234567890 and account 1234509876, and the last 2 transactions "
        "for card 4567XXXX8901 and card 999999999."),
    "scenario_16_hindi": _mail(
        "S16", "खाते का बैलेंस",
        "कृपया मेरे खाता संख्या 1234567890 का बैलेंस बताइए।"),
    "scenario_17_unregistered_sender": _mail(
        "S17", "Balance please",
        "Please send me the balance for account 1234567890.", sender=UNKNOWN_SENDER),
}

SCENARIO_TITLES: Dict[str, str] = {
    "scenario_1_balance": "1. Account Balance Enquiry",
    "scenario_2_card_transactions": "2. Credit Card Usage Enquiry",
    "scenario_3_statement": "3. Statement Request",
    "scenario_4_multi_intent": "4. Multiple Requests in One Email",
    "scenario_5_partial_failure": "5. Partial Validation Failure",
    "scenario_6_urgent_escalation": "6. Angry / Urgent Customer",
    "scenario_7_missing_details": "7. Missing Details",
    "scenario_8_policy_query": "8. Policy Question (RAG)",
    "scenario_9_unsupported": "9. Unsupported Request",
    "scenario_10_api_timeout": "10. Core API Timeout",
    "scenario_11_api_outage": "11. Core API Outage (partial)",
    "scenario_12_ownership_mismatch": "12. Account Not Linked to Sender",
    "scenario_13_image_attachment": "13. Image Attachment (OCR)",
    "scenario_14_scanned_pdf": "14. Scanned PDF Attachment (OCR)",
    "scenario_15_multiple_accounts": "15. Several Accounts and Cards",
    "scenario_16_hindi": "16. Hindi Email (translated)",
    "scenario_17_unregistered_sender": "17. Unregistered Sender",
}


def get_all_scenarios() -> List[EmailInput]:
    return list(SAMPLE_EMAILS.values())


def fresh_copy(key: str) -> EmailInput:
    base = SAMPLE_EMAILS[key]
    return EmailInput(sender=base.sender, subject=base.subject, body=base.body,
                      attachment_paths=list(base.attachment_paths), channel=base.channel)
