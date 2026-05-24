@echo off
echo Setting up EcomQA...
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python scripts/download_models.py
echo Setup complete! Run: python -m src.app
