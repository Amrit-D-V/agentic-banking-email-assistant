#!/usr/bin/env bash
set -e

command -v python3 >/dev/null || { echo "Python 3.10+ is required."; exit 1; }
echo "Python: $(python3 --version)"

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

command -v tesseract >/dev/null || echo "Note: install tesseract-ocr for image/scanned-PDF attachments (sudo apt install tesseract-ocr)."
command -v ollama >/dev/null && ollama pull llama3.2:3b || echo "Note: install Ollama (https://ollama.com) for LLaMA; without it the rule engine is used."
[ -f .env ] || cp .env.example .env

cat <<'MSG'

Setup complete.
  source .venv/bin/activate
  python main.py              # Operations Center at http://127.0.0.1:8000/dashboard
  python main.py demo-all     # run every scenario in the terminal
  pytest                      # test suite (add --llm to include live LLaMA tests)
MSG
