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
import streamlit as st

# --- Initialization ---
load_dotenv()

# Configuration
openai.api_key = os.getenv("OPENAI_API_KEY")
EMAIL = os.getenv("EMAIL_ADDRESS")
PASSWORD = os.getenv("EMAIL_PASSWORD")
SHEET_ID = os.getenv("SHEET_ID")

import os
import json
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

    except json.JSONDecodeError:
        st.error("Invalid SERVICE_ACCOUNT_JSON format")
        return None
    except gspread.exceptions.APIError as e:
        st.error(f"Google API Error: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Google Sheets connection failed: {str(e)}")
        return None


def get_emails():
    """Fetch unread emails from inbox with improved error handling"""
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
            if status != 'OK':
                continue
                
            msg = email.message_from_bytes(data[0][1])
            sender = re.search(r'From:\s+"?(.+?)"?\s+<(.+?)>', msg.as_string())
            
            emails.append({
                'name': sender.group(1) if sender else 'Unknown',
                'email': sender.group(2) if sender else 'unknown@email.com'
            })
            mail.store(eid, '+FLAGS', '\\Seen')
        
        return emails
    
    except imaplib.IMAP4.error as e:
        st.error(f"IMAP Error: {str(e)}")
        return []
    except Exception as e:
        st.error(f"Email processing error: {str(e)}")
        return []
    finally:
        try:
            mail.close()
            mail.logout()
        except:
            pass

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
        
    except json.JSONDecodeError:
        st.error("Failed to parse OpenAI response")
        return None
    except openai.error.OpenAIError as e:
        st.error(f"OpenAI Error: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Parsing error: {str(e)}")
        return None

import streamlit as st
import gspread

def append_to_sheet(data):
    """
    Append a row of data to a Google Sheet with header check, 
    duplicate check (based on Receipt Number), and proper error handling.
    """
    try:
        sheet = get_sheet()
        if not sheet:
            st.error("❌ Failed to access the Google Sheet.")
            return False

        # Define expected header
        expected_header = [
            "Sender Name", "Sender Email", "Item", 
            "Cost", "Date", "Source", "Receipt Number"
        ]

        # Check and set header if needed
        current_header = sheet.row_values(1)
        if current_header != expected_header:
            if any(current_header):  # Header exists but is wrong
                sheet.delete_rows(1)
            sheet.insert_row(expected_header, 1)

        # Fetch existing data
        existing_data = sheet.get_all_values()

        # Extract existing receipt numbers (assuming Receipt Number is in column 7)
        existing_receipts = {row[6] for row in existing_data[1:] if len(row) > 6}

        if data[6] not in existing_receipts:
            sheet.append_row(data)
            st.success("✅ Successfully saved to Google Sheets.")
            return True
        else:
            st.warning("⚠️ Entry with the same receipt number already exists.")
            return False

    except gspread.exceptions.APIError as e:
        st.error(f"Google Sheets API Error: {str(e)}")
        return False

    except Exception as e:
        st.error(f"Unexpected error: {str(e)}")
        return False
