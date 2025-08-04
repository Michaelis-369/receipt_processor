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
if 'selected_email' not in st.session_state:
    st.session_state.selected_email = None

st.title("📄 Smart Receipt Processor")

def manual_entry_form():
    """Manual entry form that preserves all user inputs"""
    with st.form("manual_entry"):
        st.subheader("Manual Entry")
        sender_name = st.text_input("Sender Name", value="")
        sender_email = st.text_input("Sender Email", value="")
        
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
                'name': sender_name or "ManualEntry",
                'email': sender_email or "no_email@example.com",
                'item': item,
                'cost': cost,
                'date': date.strftime("%Y-%m-%d"),
                'source': source,
                'receipt_number': receipt_number or f"Manual_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            }
    return None

def generate_safe_filename(parsed_data):
    """Generate consistent filename for both AI and manual entries"""
    receipt_num = re.sub(r'[^\w.-]', '_', str(parsed_data.get('receipt_number', 'Unknown')))
    item = re.sub(r'[^\w.-]', '_', str(parsed_data.get('item', 'Unknown'))[:50])
    sender = re.sub(r'[^\w.-]', '_', str(parsed_data.get('name', 'ManualEntry'))[:20])
    return f"{receipt_num}_{item}_{sender}.pdf"

# Email selection section
st.subheader("1. Select Email Source")
if st.button("Check for Unread Emails"):
    with st.spinner("Fetching unread emails..."):
        unread_emails = processor.get_unread_emails()
        
        if unread_emails:
            st.session_state.unread_emails = unread_emails
        else:
            st.info("No unread emails found")

if 'unread_emails' in st.session_state:
    email_options = {i: f"{email['subject']} (From: {email['from']})" 
                    for i, email in enumerate(st.session_state.unread_emails)}
    
    selected_index = st.selectbox(
        "Select email to associate with receipt",
        options=list(email_options.keys()),
        format_func=lambda x: email_options[x],
        index=None
    )
    
    if selected_index is not None:
        st.session_state.selected_email = st.session_state.unread_emails[selected_index]
        st.success(f"Selected email: {st.session_state.selected_email['subject']}")

# PDF upload section
st.subheader("2. Upload Receipt PDF")
uploaded_file = st.file_uploader("Drag & drop receipt PDF", type="pdf")

if uploaded_file:
    file_bytes = uploaded_file.read()
    file_hash = hashlib.md5(file_bytes).hexdigest()
    
    if file_hash not in st.session_state.processed_files:
        with st.spinner("Processing..."):
            try:
                pdf_file = BytesIO(file_bytes)
                text = "\n".join([page.extract_text() for page in PyPDF2.PdfReader(pdf_file).pages])
                
                # Use selected email info if available
                sender_info = None
                if st.session_state.selected_email:
                    sender_info = {
                        'name': st.session_state.selected_email['name'],
                        'email': st.session_state.selected_email['email']
                    }
                
                parsed_data = processor.parse_pdf_from_text(text)
                
                if parsed_data is None:
                    st.warning("⚠️ Could not auto-extract receipt data")
                    manual_data = manual_entry_form()
                    if manual_data:
                        parsed_data = manual_data
                        # Use email sender if available
                        if sender_info:
                            parsed_data['email'] = sender_info['email']
                            parsed_data['name'] = sender_info['name']
                
                if parsed_data:
                    safe_name = generate_safe_filename(parsed_data)
                    receipt_path = os.path.join("receipts", safe_name)
                    
                    os.makedirs("receipts", exist_ok=True)
                    with open(receipt_path, "wb") as f:
                        f.write(file_bytes)
                    
                    success = processor.append_to_sheet([
                        parsed_data['name'],
                        parsed_data['email'],
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
                        
                        # Mark email as read after successful processing
                        if st.session_state.selected_email:
                            processor.mark_email_as_read(st.session_state.selected_email['id'])
                        
                        st.success("✅ Processing complete!")
                        st.json(parsed_data)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    if 'current_receipt' in st.session_state:
        with open(st.session_state.current_receipt, "rb") as f:
            st.download_button(
                "Download Processed Receipt",
                data=f,
                file_name=st.session_state.current_name,
                mime="application/pdf"
            )
