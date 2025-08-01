import os
import imaplib
import email
import re
import openai
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration
openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_PASSWORD")
SHEET_ID = os.getenv("SHEET_ID")

def get_sheet():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            json.loads(os.getenv('SERVICE_ACCOUNT_JSON')),
            ['https://www.googleapis.com/auth/spreadsheets']
        )
        return gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
    except Exception as e:
        print(f"Google Sheets error: {str(e)}")
        return None

def get_emails():
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(EMAIL, PASSWORD)
        mail.select('inbox')
        
        status, messages = mail.search(None, '(UNSEEN)')
        if status != 'OK':
            return []
        
        emails = []
        for eid in messages[0].split():
            status, data = mail.fetch(eid, '(RFC822)')
            msg = email.message_from_bytes(data[0][1])
            sender = re.search(r'From:\s+"?(.+?)"?\s+<(.+?)>', msg.as_string())
            
            emails.append({
                'name': sender.group(1) if sender else 'Unknown',
                'email': sender.group(2) if sender else 'unknown@email.com'
            })
            mail.store(eid, '+FLAGS', '\\Seen')
        
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

def parse_pdf_from_text(text):
    try:
        prompt = """Extract from receipt:
        {
            "item": "most expensive item",
            "cost": "total amount",
            "date": "YYYY-MM-DD",
            "source": "store/vendor",
            "receipt_number": "number if available"
        }""" + text[:2000]
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        
        json_str = response.choices[0].message.content
        return json.loads(json_str.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        print(f"Parsing error: {str(e)}")
        return None

def append_to_sheet(data):
    try:
        sheet = get_sheet()
        if not sheet:
            return False
            
        if not sheet.row_values(1):
            sheet.append_row(["Sender Name", "Sender Email", "Item", "Cost", "Date", "Source", "Receipt Number"])
        
        sheet.append_row(data)
        return True
    except Exception as e:
        print(f"Sheets append error: {str(e)}")
        return False