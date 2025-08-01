import os
import re
import hashlib
from io import BytesIO
import streamlit as st
import PyPDF2
import processor
from datetime import datetime

# Initialize session state
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = set()
if 'manual_data' not in st.session_state:
    st.session_state.manual_data = None

st.title("📄 Smart Receipt Processor")

def manual_entry_form(default_sender=None):
    with st.form("manual_entry"):
        st.subheader("Manual Entry")
        sender_name = st.text_input("Sender Name", value=default_sender['name'] if default_sender else "")
        sender_email = st.text_input("Sender Email", value=default_sender['email'] if default_sender else "")
        
        col1, col2 = st.columns(2)
        with col1:
            item = st.text_input("Item", "Unknown")
            cost = st.text_input("Cost", "0")
        with col2:
            date = st.date_input("Date", datetime.now())
            source = st.text_input("Source", "Unknown")
        
        receipt_number = st.text_input("Receipt Number", "Unknown")
        
        if st.form_submit_button("Submit"):
            return {
                'name': sender_name,
                'email': sender_email,
                'item': item,
                'cost': cost,
                'date': date.strftime("%Y-%m-%d"),
                'source': source,
                'receipt_number': receipt_number
            }
    return None

uploaded_file = st.file_uploader("Drag & drop receipt PDF", type="pdf")

if uploaded_file:
    file_bytes = uploaded_file.read()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    if file_hash not in st.session_state.processed_files:
        with st.spinner("Processing..."):
            try:
                pdf_file = BytesIO(file_bytes)
                text = "\n".join([page.extract_text() for page in PyPDF2.PdfReader(pdf_file).pages])
                
                senders = processor.get_emails()
                sender = senders[0] if senders else {'name': 'Manual_Entry', 'email': 'no_email@example.com'}
                
                parsed_data = processor.parse_pdf_from_text(text)
                
                if parsed_data is None:
                    st.warning("⚠️ Auto-extraction failed")
                    st.session_state.manual_data = manual_entry_form(sender)
                    if st.session_state.manual_data:
                        parsed_data = st.session_state.manual_data
                
                if parsed_data:
                    safe_name = f"{parsed_data['receipt_number']}_{parsed_data['item'][:50]}_{sender['name'][:20]}.pdf"
                    safe_name = re.sub(r'[^\w.-]', '_', safe_name)
                    receipt_path = os.path.join("receipts", safe_name)
                    
                    os.makedirs("receipts", exist_ok=True)
                    with open(receipt_path, "wb") as f:
                        f.write(file_bytes)
                    
                    success = processor.append_to_sheet([
                        parsed_data.get('name', sender['name']),
                        parsed_data.get('email', sender['email']),
                        parsed_data['item'],
                        parsed_data['cost'],
                        parsed_data['date'],
                        parsed_data['source'],
                        parsed_data['receipt_number']
                    ])
                    
                    if success:
                        st.session_state.processed_files.add(file_hash)
                        st.session_state.current_receipt = receipt_path
                        st.session_state.current_name = safe_name
                        st.success("✅ Processing complete!")
                        st.json(parsed_data)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    if 'current_receipt' in st.session_state:
        with open(st.session_state.current_receipt, "rb") as f:
            st.download_button(
                "Download Receipt",
                data=f,
                file_name=st.session_state.current_name,
                mime="application/pdf"
            )