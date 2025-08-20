import re
from io import BytesIO
import streamlit as st
import PyPDF2
from processor import ReceiptProcessor
from datetime import datetime

# Initialize session state
def init_session_state():
    session_vars = {
        'authenticated': False,
        'current_receipt': None,
        'receipt_details': None,
        'processing_stage': "upload",
        'unread_emails': None,
        'email_check_performed': False,
        'sender_info': None,
        'duplicate_receipt': False  # New session state for duplicate tracking
    }
    for key, value in session_vars.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Authentication
def check_auth():
    try:
        VALID_TOKENS = {
            "client1": "token-abc123",  # Replace with your tokens
            "client2": "token-xyz789"
        }
        
        if st.session_state.authenticated:
            return True
            
        token = st.query_params.get("token", [None])[0]
        if token and token in VALID_TOKENS.values():
            st.session_state.authenticated = True
            return True
        
        with st.form("auth"):
            st.warning("Please enter your access token")
            token_input = st.text_input("Access Token", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                if token_input in VALID_TOKENS.values():
                    st.session_state.authenticated = True
                    st.query_params["token"] = token_input
                    st.rerun()
                else:
                    st.error("Invalid access token")
        return False
    except Exception:
        st.error("Authentication service unavailable")
        return False

if not check_auth():
    st.stop()

# Initialize processor
processor = ReceiptProcessor(
    anthropic_api_key=st.secrets["ANTHROPIC_API_KEY"],
    email_address=st.secrets["EMAIL_ADDRESS"],
    email_password=st.secrets["EMAIL_PASSWORD"],
    sheet_id=st.secrets["SHEET_ID"],
    google_creds={
        "type": "service_account",
        "project_id": st.secrets["project_id"],
        "private_key_id": st.secrets["private_key_id"],
        "private_key": st.secrets["private_key"].replace('\\n', '\n'),
        "client_email": st.secrets["client_email"],
        "client_id": st.secrets["client_id"],
        "auth_uri": st.secrets["auth_uri"],
        "token_uri": st.secrets["token_uri"],
        "auth_provider_x509_cert_url": st.secrets["auth_provider_x509_cert_url"],
        "client_x509_cert_url": st.secrets["client_x509_cert_url"],
        "universe_domain": st.secrets["universe_domain"]
    }
)

def reset_processing():
    st.session_state.current_receipt = None
    st.session_state.receipt_details = None
    st.session_state.processing_stage = "upload"
    st.session_state.unread_emails = None
    st.session_state.email_check_performed = False
    st.session_state.sender_info = None
    st.session_state.duplicate_receipt = False
    st.rerun()

def sanitize_filename(text):
    return re.sub(r'[^\w_.-]', '', text.replace(' ', '_'))

st.title("📄 Professional Receipt Processor")

def get_sender_info():
    with st.form("sender_info_form"):
        st.subheader("Sender Information")
        sender_name = st.text_input("Sender Name*", max_chars=50)
        sender_email = st.text_input("Sender Email", max_chars=100)
        
        submitted = st.form_submit_button("Submit")
        if submitted:
            if not sender_name:
                st.error("Name is required")
                return None
            return {
                'name': sender_name,
                'email': sender_email or "no_email@example.com"
            }
    return None

def verify_details(extracted_data):
    with st.form("verify_details"):
        st.subheader("Verify Extracted Details")
        
        col1, col2 = st.columns(2)
        with col1:
            item = st.text_input("Item*", extracted_data.get('item', 'unknown'))
            cost = st.text_input("Cost*", extracted_data.get('cost', '0'))
        with col2:
            date_str = extracted_data.get('date', datetime.now().strftime("%Y-%m-%d"))
            try:
                date = st.date_input("Date*", datetime.strptime(date_str, "%Y-%m-%d"))
            except:
                date = st.date_input("Date*", datetime.now())
            source = st.text_input("Vendor/Source*", extracted_data.get('source', 'unknown'))
        
        receipt_number = st.text_input("Receipt Number", extracted_data.get('receipt_number', ''))
        
        # NEW: Add dropdown menus and notes
        col3, col4 = st.columns(2)
        with col3:
            payment_type = st.selectbox(
                "Paid Inv/Pcard*",
                options=["Reimbursement", "Invoice", "Store Receipt"],
                index=0
            )
        with col4:
            category = st.selectbox(
                "Category*",
                options=["Operational", "Carpenter", "Equipment", "McCabe", "Other"],
                index=0
            )
        
        notes = st.text_area("Notes", max_chars=200)
        
        submitted = st.form_submit_button("Submit Verified Details")
        if submitted:
            if not item or not cost or not source:
                st.error("Required fields marked with *")
                return None
            
            clean_cost = re.sub(r'[^\d.]', '', cost) or "0"
            formatted_cost = f"{float(clean_cost):.2f}"
            
            return {
                'item': ' '.join(item.split()[:2]).lower(),
                'cost': formatted_cost,
                'date': date.strftime("%Y-%m-%d"),
                'source': source.lower(),
                'receipt_number': receipt_number or f"receipt_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                # NEW: Add the new fields
                'payment_type': payment_type,
                'category': category,
                'notes': notes
            }
    return None

# Main processing flow
if st.session_state.processing_stage == "upload":
    st.subheader("1. Upload Receipt")
    uploaded_file = st.file_uploader("Select PDF receipt", type="pdf")
    
    if uploaded_file:
        with st.spinner("Extracting receipt data..."):
            try:
                file_bytes = uploaded_file.read()
                text = "\n".join(
                    page.extract_text() or "" 
                    for page in PyPDF2.PdfReader(BytesIO(file_bytes)).pages
                )
                
                if not text.strip():
                    st.error("The PDF appears to be empty or couldn't be read")
                    st.session_state.processing_stage = "upload"
                    st.stop()
                
                extracted_data = processor.parse_receipt_text(text)
                
                if not extracted_data:
                    st.error("Could not extract data from PDF")
                    st.session_state.processing_stage = "upload"
                    st.stop()
                
                # Check for duplicate receipt
                if processor.check_duplicate_receipt(extracted_data['receipt_number']):
                    st.session_state.duplicate_receipt = True
                    st.session_state.receipt_details = extracted_data
                    st.session_state.current_receipt = file_bytes
                    st.warning('⚠️ This receipt appears to have already been processed.\nClick the "X" to cancel or click "Process another receipt"')
                    st.json(st.session_state.receipt_details)
                else:
                    st.session_state.receipt_details = extracted_data
                    st.session_state.current_receipt = file_bytes
                    st.session_state.processing_stage = "verify"
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Error processing PDF: {str(e)}")
                st.session_state.processing_stage = "upload"
                st.stop()

elif st.session_state.duplicate_receipt:
    st.warning("⚠️ This receipt appears to have already been processed.\nClick the 'X' to cancel and process another receipt")
    st.json(st.session_state.receipt_details)
    
    if st.button("Process Another Receipt"):
        reset_processing()

elif st.session_state.processing_stage == "verify":
    st.subheader("2. Verify Extracted Data")
    
    if st.session_state.receipt_details:
        verified_data = verify_details(st.session_state.receipt_details)
        
        if verified_data:
            st.session_state.receipt_details = verified_data
            st.session_state.processing_stage = "sender"
            st.rerun()

elif st.session_state.processing_stage == "sender":
    st.subheader("3. Sender Information")
    
    if st.button("Check Emails for Sender Info"):
        with st.spinner("Checking emails..."):
            try:
                emails = processor.get_unread_emails()
                st.session_state.unread_emails = emails if emails else []
                st.session_state.email_check_performed = True
                st.rerun()
            except Exception as e:
                st.error(f"Email error: {str(e)}")
                st.session_state.email_check_performed = True
                st.rerun()
    
    if st.session_state.email_check_performed:
        if st.session_state.unread_emails:
            email_options = {
                i: f"{email['subject']} ({email['from']})" 
                for i, email in enumerate(st.session_state.unread_emails)
            }
            selected = st.selectbox(
                "Select matching email", 
                options=list(email_options.keys()),
                format_func=lambda x: email_options[x]
            )
            
            if st.button("Use Selected Email"):
                selected_email = st.session_state.unread_emails[selected]
                st.session_state.sender_info = {
                    'name': selected_email.get('name'),
                    'email': selected_email.get('email')
                }
                st.session_state.processing_stage = "submit"
                st.rerun()
        else:
            st.warning("No unread emails found - please enter sender information manually")
            manual_info = get_sender_info()
            if manual_info:
                st.session_state.sender_info = manual_info
                st.session_state.processing_stage = "submit"
                st.rerun()

elif st.session_state.processing_stage == "submit":
    st.subheader("4. Submit to Google Sheets")
    
    if st.session_state.receipt_details and st.session_state.current_receipt:
        complete_data = {
            **(st.session_state.sender_info or {'name': 'Unknown', 'email': 'no_email@example.com'}),
            **st.session_state.receipt_details
        }
        
        filename = f"{sanitize_filename(complete_data['name'])}_{sanitize_filename(complete_data['item'])}_{complete_data['receipt_number']}_{complete_data['cost']}.pdf"
        
        # Update the display to show all fields
        st.json({
            "Sender": f"{complete_data['name']} <{complete_data['email']}>",
            "Item": complete_data['item'],
            "Cost": complete_data['cost'],
            "Date": complete_data['date'],
            "Vendor/Source": complete_data['source'],
            "Receipt Number": complete_data['receipt_number'],
            "Payment Type": complete_data.get('payment_type', 'Reimbursement'),
            "Category": complete_data.get('category', 'Operational'),
            "Notes": complete_data.get('notes', '')
        })
        
        if st.button("Confirm and Submit"):
            with st.spinner("Saving to Google Sheets..."):
                try:
                    # Convert cost to number for Google Sheets formulas
                    cost_value = float(complete_data['cost'])
                    
                    # Prepare data in the new column order
                    sheet_data = [
                        complete_data['date'],  # Date
                        complete_data['source'],  # Vendor/Source
                        complete_data.get('payment_type', 'Reimbursement'),  # Paid Inv/Pcard
                        cost_value if complete_data.get('category') == 'Operational' else '',  # Operational (as number)
                        cost_value if complete_data.get('category') == 'Carpenter' else '',  # Carpenter (as number)
                        cost_value if complete_data.get('category') == 'Equipment' else '',  # Equipment (as number)
                        cost_value if complete_data.get('category') == 'McCabe' else '',  # McCabe (as number)
                        cost_value if complete_data.get('category') == 'Other' else '',  # Other (as number)
                        complete_data.get('notes', ''),  # Notes
                        complete_data['name'],  # Sender Name
                        complete_data['email'],  # Sender Email
                        complete_data['item'],  # Item
                        complete_data['receipt_number']  # Receipt Number
                    ]
                    
                    if processor.append_to_sheet(sheet_data):
                        st.session_state.processing_stage = "complete"
                        st.rerun()
                except Exception as e:
                    st.error(f"Submission failed: {str(e)}")

elif st.session_state.processing_stage == "complete":
    st.success("✅ Processing complete! Data saved to Google Sheets.")
    
    complete_data = {
        **(st.session_state.sender_info or {'name': 'Unknown'}),
        **st.session_state.receipt_details
    }
    filename = f"{sanitize_filename(complete_data['name'])}_{sanitize_filename(complete_data['item'])}_{complete_data['receipt_number']}_{complete_data['cost']}.pdf"
    
    st.download_button(
        "Download Renamed Receipt",
        data=st.session_state.current_receipt,
        file_name=filename,
        mime="application/pdf"
    )
    
    if st.button("Process Another Receipt"):
        reset_processing()
