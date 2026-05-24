#!/bin/bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scripts/download_models.py
echo "Setup complete. Run: python -m src.app"
