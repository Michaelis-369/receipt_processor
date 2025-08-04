import os
import imaplib
import email
import re
import openai
import gspread
import json
from email.header import decode_header
from email.utils import parseaddr
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv
import streamlit as st

# --- Initialization ---
load_dotenv()

# Configuration
openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_PASSWORD")
SHEET_ID = os.getenv("SHEET_ID")

def get_sheet():
    """Initialize Google Sheets connection with proper error handling."""
    try:
        service_json = os.getenv('SERVICE_ACCOUNT_JSON')
        sheet_id = os.getenv('SHEET_ID')

        if not service_json:
            st.error("Missing SERVICE_ACCOUNT_JSON in environment variables")
            return None
        if not sheet_id:
            st.error("Missing GOOGLE_SHEET_ID in environment variables")
            return None

        service_account_info = json.loads(service_json)

        # Ensure required fields exist
        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        if not all(field in service_account_info for field in required_fields):
            st.error("Service account JSON missing required fields")
            return None

        # Fix private key formatting
        service_account_info['private_key'] = service_account_info['private_key'].replace('\\n', '\n')

        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            service_account_info,
            ['https://www.googleapis.com/auth/spreadsheets']
        )

        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(sheet_id)
        return spreadsheet.sheet1

    except Exception as e:
        st.error(f"Google Sheets connection failed: {str(e)}")
        return None

def get_unread_emails():
    """Fetch unread emails without marking them as read"""
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(EMAIL, PASSWORD)
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
            
            # Decode subject
            subject, encoding = decode_header(msg["Subject"])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding if encoding else 'utf-8')
            
            # Get sender info
            from_ = parseaddr(msg.get("From"))
            sender_name, sender_email = from_
            
            emails.append({
                'id': eid,
                'subject': subject,
                'from': f"{sender_name} <{sender_email}>",
                'name': sender_name,
                'email': sender_email,
                'date': msg.get("Date")
            })
        
        return emails
    
    except Exception as e:
        st.error(f"Email fetch error: {str(e)}")
        return []
    finally:
        try:
            mail.close()
        except:
            pass

def mark_email_as_read(email_id):
    """Mark specific email as read"""
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(EMAIL, PASSWORD)
        mail.select('inbox')
        mail.store(email_id, '+FLAGS', '\\Seen')
        mail.close()
        return True
    except Exception as e:
        st.error(f"Error marking email as read: {str(e)}")
        return False

def parse_pdf_from_text(text):
    """Parse receipt text using OpenAI with better error handling"""
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
        json_str = json_str.replace("```json", "").replace("```", "").strip()
        result = json.loads(json_str)
        
        return {
            "item": result.get("item", "Unknown"),
            "cost": result.get("cost", "0"),
            "date": result.get("date", datetime.now().strftime("%Y-%m-%d")),
            "source": result.get("source", "Unknown"),
            "receipt_number": result.get("receipt_number", "Unknown")
        }
        
    except Exception as e:
        st.error(f"Parsing error: {str(e)}")
        return None

def append_to_sheet(data):
    """Append data to Google Sheet with duplicate checking"""
    try:
        sheet = get_sheet()
        if not sheet:
            return False

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
        
        st.warning("⚠️ Entry with the same receipt number already exists.")
        return False

    except Exception as e:
        st.error(f"Sheet append error: {str(e)}")
        return False
