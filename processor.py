import re
import json
import requests
import imaplib
import email
import gspread
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime
from dateutil import parser
from oauth2client.service_account import ServiceAccountCredentials

class ReceiptProcessor:
    def __init__(self, anthropic_api_key, email_address, email_password, sheet_id, google_creds):
        self.anthropic_headers = {
            "x-api-key": anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        self.anthropic_url = "https://api.anthropic.com/v1/messages"
        self.email_address = email_address
        self.email_password = email_password
        self.sheet_id = sheet_id
        self.google_creds = google_creds
        self._init_google_sheets()

    def _init_google_sheets(self):
        try:
            self.creds = ServiceAccountCredentials.from_json_keyfile_dict(
                self.google_creds,
                ['https://www.googleapis.com/auth/spreadsheets']
            )
            self.gc = gspread.authorize(self.creds)
        except Exception as e:
            raise Exception(f"Google Sheets initialization failed: {str(e)}")

    def clean_text(self, text):
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'http[s]?://\S+', '', text)
        return text[:5000]

    def parse_receipt_text(self, text):
        if not text.strip():
            return None

        cleaned_text = self.clean_text(text)
        
        prompt = """Extract these details from the receipt text:
        - item: The main product purchased (2-3 words max)
        - cost: The grand total paid (numbers only)
        - date: The order date (YYYY-MM-DD format)
        - source: The store/vendor name
        - receipt_number: The order/transaction ID

        Return ONLY a JSON object with these exact keys. Example:
        {
            "item": "product name",
            "cost": "100.00",
            "date": "2025-06-21",
            "source": "store name",
            "receipt_number": "123-4567890"
        }

        Receipt text: """ + cleaned_text

        data = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}]
        }

        try:
            response = requests.post(
                self.anthropic_url,
                headers=self.anthropic_headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            
            json_str = response.json()["content"][0]["text"]
            json_str = json_str.replace("```json", "").replace("```", "").strip()
            result = json.loads(json_str)
            
            return {
                "item": str(result.get("item", "unknown")).strip()[:50],
                "cost": re.sub(r'[^\d.]', '', str(result.get("cost", "0"))),
                "date": self._parse_date(result.get("date")),
                "source": str(result.get("source", "unknown")).strip()[:50],
                "receipt_number": str(result.get("receipt_number", "")).strip()[:50] or 
                                 f"auto_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            }
        except Exception as e:
            print(f"API Error: {str(e)}")
            return None

    def _parse_date(self, date_str):
        try:
            return parser.parse(date_str).strftime("%Y-%m-%d")
        except:
            return datetime.now().strftime("%Y-%m-%d")

    def get_unread_emails(self):
        try:
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(self.email_address, self.email_password)
            mail.select('inbox')
            
            status, messages = mail.search(None, '(UNSEEN)')
            if status != 'OK' or not messages[0]:
                return []
            
            emails = []
            for eid in messages[0].split():
                status, data = mail.fetch(eid, '(RFC822 BODY.PEEK[HEADER])')
                if status != 'OK':
                    continue
                    
                msg = email.message_from_bytes(data[0][1])
                
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding if encoding else 'utf-8')
                
                from_ = parseaddr(msg.get("From"))
                sender_name, sender_email = from_
                
                emails.append({
                    'id': eid.decode(),
                    'subject': subject[:100],
                    'from': f"{sender_name} <{sender_email}>",
                    'name': sender_name[:50],
                    'email': sender_email[:100],
                    'date': msg.get("Date", "")[:50]
                })
            
            return emails
        except Exception as e:
            print(f"Email error: {str(e)}")
            return []
        finally:
            try:
                mail.close()
                mail.logout()
            except:
                pass

    def append_to_sheet(self, data):
        try:
            spreadsheet = self.gc.open_by_key(self.sheet_id)
            sheet = spreadsheet.sheet1
            
            expected_header = [
                "Sender Name", "Sender Email", "Item", 
                "Cost", "Date", "Source", "Receipt Number"
            ]
            
            current_header = sheet.row_values(1)
            if current_header != expected_header:
                if any(current_header):
                    sheet.delete_rows(1)
                sheet.insert_row(expected_header, 1)

            existing_data = sheet.get_all_values()
            existing_receipts = {row[6] for row in existing_data[1:] if len(row) > 6}

            if data[6] not in existing_receipts:
                sheet.append_row(data)
                return True
            
            print("Duplicate receipt - not added to sheet")
            return False
        except Exception as e:
            print(f"Sheets error: {str(e)}")
            return False
