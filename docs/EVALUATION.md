# Evaluation

`python main.py evaluate` runs the 60 labelled emails in `sample_data/eval_emails.json` through the full
pipeline (with a temporary database) and reports accuracy. The set covers the brief's scenarios plus varied
wording, typos, shorthand, Hinglish, Hindi, HTML bodies, signatures, phone and ticket numbers, several
accounts per email, angry tone and unsupported requests.

The rule set was **not** tuned on these emails, so the numbers are an honest estimate.

## Results (measured on a laptop)

| | Rules only | LLaMA 3.2 3B + rules (default) | Single combined LLM call |
|---|---|---|---|
| Intent accuracy | 85.0% | **93.3%** | 88.3% |
| Account numbers | 100% | 100% | 100% |
| Card numbers | 100% | 100% | 100% |
| Transaction count | 100% | 100% | 100% |
| Statement period | 100% | 100% | 100% |
| Sentiment | 98.3% | 93.3% | 81.7% |
| Median time per email | 8 ms | 2.9 s | 3.4 s |

Intent detection with LLaMA (precision / recall / F1):

| Intent | Precision | Recall | F1 |
|---|---|---|---|
| BALANCE_ENQUIRY | 1.00 | 0.92 | 0.96 |
| CARD_TRANSACTIONS | 1.00 | 1.00 | 1.00 |
| STATEMENT_REQUEST | 0.93 | 0.93 | 0.93 |
| POLICY_INQUIRY | 1.00 | 0.86 | 0.92 |
| GENERAL_INQUIRY | 0.71 | 1.00 | 0.83 |

## What the numbers say

- **Identifiers are deterministic and exact.** Account and card numbers, counts and periods come from the rule layer, grounded in the email text, so they're 100% in every mode.
- **The LLM is what handles messy language.** Typos ("balence", "acount"), shorthand ("bal of acc") and Hinglish/Hindi move intent accuracy from 85% to 93%.
- **Sentiment trades precision for safety.** An email is marked urgent if either the lexicon or the LLM says so. LLaMA over-flags a few polite emails ("please reply quickly"), which costs some accuracy, but no angry customer is missed.
- **Combining the three LLM calls into one was tested and rejected.** It was less accurate and slower: the separate calls run in parallel LangGraph branches, while one long answer is generated sequentially. It remains available as `NLU_SINGLE_CALL=true`.
- **Remaining misses:** shorthand that neither rules nor the 3B model understand ("pls send bal of acc"), a three-intent email where the statement request was missed, and "e-statement password" classified as a statement request rather than a policy question. Low-confidence results go to human review.

`tests/test_quality_scalability.py` fails if rule-engine accuracy drops below these baselines.
