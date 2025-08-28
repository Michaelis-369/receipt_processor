import re
import json
import requests
import imaplib
import email
import gspread
import base64
from email.header import decode_header
from email.utils import parseaddr
from datetime import datetime
from dateutil import parser
from oauth2client.service_account import ServiceAccountCredentials

class ReceiptProcessor:
    def __init__(self, anthropic_api_key, email_address, email_password, sheet_id, google_creds, openai_api_key=None):
        self.anthropic_headers = {
            "x-api-key": anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        self.anthropic_url = "https://api.anthropic.com/v1/messages"
        self.openai_api_key = openai_api_key
        self.openai_url = "https://api.openai.com/v1/chat/completions"
        self.email_address = email_address
        self.email_password = email_password
        self.sheet_id = sheet_id
        self.google_creds = google_creds
        self._init_google_sheets()

    def _init_google_sheets(self):
        """Initialize Google Sheets connection"""
        try:
            self.creds = ServiceAccountCredentials.from_json_keyfile_dict(
                self.google_creds,
                ['https://www.googleapis.com/auth/spreadsheets']
            )
            self.gc = gspread.authorize(self.creds)
        except Exception as e:
            raise Exception(f"Google Sheets initialization failed: {str(e)}")

    def clean_text(self, text):
        """Clean extracted text"""
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'http[s]?://\S+', '', text)
        return text[:5000]  # Limit to first 5000 chars

    def parse_receipt_text(self, text):
        """Parse receipt text using Anthropic API"""
        if not text.strip():
            return None

        cleaned_text = self.clean_text(text)
        
        prompt = """Extract these details from the receipt text:
        - item: The generic name of the product purchased (2 words max, hyphen separated if multiple)
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

    def parse_receipt_image(self, image_bytes, file_type="jpeg"):
        """Parse receipt image using OpenAI GPT-4o-mini Vision API"""
        if not self.openai_api_key:
            print("OpenAI API key not configured")
            return None
            
        try:
            # Encode image to base64
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            
            prompt = """Analyze this receipt image and extract these details:
            - item: The generic name of the product purchased (2 words max, hyphen separated if multiple)
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
            }"""

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_api_key}"
            }

            data = {
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{file_type};base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 500,
                "response_format": { "type": "json_object" }
            }

            response = requests.post(
                self.openai_url,
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()["choices"][0]["message"]["content"]
            result_data = json.loads(result)
            
            return {
                "item": str(result_data.get("item", "unknown")).strip()[:50],
                "cost": re.sub(r'[^\d.]', '', str(result_data.get("cost", "0"))),
                "date": self._parse_date(result_data.get("date")),
                "source": str(result_data.get("source", "unknown")).strip()[:50],
                "receipt_number": str(result_data.get("receipt_number", "")).strip()[:50] or 
                                 f"auto_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            }
            
        except Exception as e:
            print(f"OpenAI Vision API Error: {str(e)}")
            return None

    def _parse_date(self, date_str):
        """Parse and format date string"""
        try:
            return parser.parse(date_str).strftime("%Y-%m-%d")
        except:
            return datetime.now().strftime("%Y-%m-%d")

    def get_unread_emails(self):
        """Fetch unread emails from Gmail"""
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

    def check_duplicate_receipt(self, receipt_number):
        """Check if receipt already exists in the sheet"""
        try:
            spreadsheet = self.gc.open_by_key(self.sheet_id)
            sheet = spreadsheet.sheet1
            
            # Get all receipt numbers from column 11 (index 10) instead of 13
            existing_numbers = sheet.col_values(11)[1:]  # Skip header row
            
            # Check if the receipt number already exists
            return receipt_number in existing_numbers
        except Exception as e:
            print(f"Duplicate check error: {str(e)}")
            return False
    
    def append_to_sheet(self, data):
        """Append receipt data to Google Sheet with proper number formatting"""
        try:
            spreadsheet = self.gc.open_by_key(self.sheet_id)
            sheet = spreadsheet.sheet1
            
            # Updated header with new column order (removed name and email)
            expected_header = [
                "Date", "Vendor/Source", "Paid Inv/Pcard", 
                "Operational", "Carpenter", "Equipment", 
                "McCabe", "Other", "Notes",
                "Item", "Receipt Number"  # Removed "Sender Name" and "Sender Email"
            ]
            
            current_header = sheet.row_values(1)
            if current_header != expected_header:
                if any(current_header):
                    sheet.delete_rows(1)
                sheet.insert_row(expected_header, 1)

            # Check for duplicates (now in column 11 instead of 13)
            if self.check_duplicate_receipt(data[10]):  # Changed index from 12 to 10
                return {
                    "status": "duplicate",
                    "message": "This receipt has already been processed"
                }

            # Method 1: Find last row with date pattern
            all_dates = sheet.col_values(1)
            last_data_row = 1
            
            for i, date_value in enumerate(all_dates[1:], start=2):
                if date_value and re.match(r'^\d{4}-\d{2}-\d{2}$', str(date_value)):
                    last_data_row = i
            
            # Method 2: Alternative - check multiple columns to be sure
            all_receipt_numbers = sheet.col_values(11)  # Column K instead of M
            for i, receipt_num in enumerate(all_receipt_numbers[1:], start=2):
                if receipt_num and receipt_num != "#N/A" and not receipt_num.startswith("="):
                    last_data_row = max(last_data_row, i)
            
            # Method 3: As fallback, use the row count but skip obvious formula rows
            if last_data_row == 1 and sheet.row_count > 2:
                # Check if row 2 has data or is a formula row
                row2_data = sheet.row_values(2)
                if any(row2_data) and not any(str(cell).startswith("=") for cell in row2_data if cell):
                    last_data_row = 2
            
            # Prepare data with proper types
            row_data = []
            for i, item in enumerate(data):
                if 3 <= i <= 7 and item != '':  # Note: indices changed due to removed columns
                    try:
                        row_data.append(float(item))
                    except (ValueError, TypeError):
                        row_data.append(item)
                else:
                    row_data.append(item)
            
            # Insert the new row right after the last data row
            sheet.insert_row(row_data, index=last_data_row + 1, value_input_option='USER_ENTERED')
            
            return {
                "status": "success",
                "message": "Receipt successfully added to sheet"
            }
        except Exception as e:
            print(f"Sheets error: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to process receipt: {str(e)}"
            }
