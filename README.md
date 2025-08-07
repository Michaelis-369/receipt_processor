# Receipt Processor App

📌 Automated receipt processing with AI and Google Sheets integration

## Features
- PDF receipt parsing
- Email sender detection
- Google Sheets export
- Manual entry fallback

## Setup
1. Clone repository
2. Create `.streamlit/secrets.toml` (see template below)
3. `pip install -r requirements.txt`
4. `streamlit run app.py`

## Secrets Template
```toml
# .streamlit/secrets.toml
ANTHROPIC_API_KEY = "your_key"
EMAIL_ADDRESS = "your_email"
EMAIL_PASSWORD = "app_password"
SHEET_ID = "your_sheet_id"

[google_creds]
type = "service_account"
project_id = "your_project_id"
# ... (add all google_creds fields)
```
