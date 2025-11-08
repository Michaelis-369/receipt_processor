import re
from io import BytesIO
import streamlit as st
import PyPDF2
import hashlib
from processor import ReceiptProcessor
from datetime import datetime

# Initialize session state
def init_session_state():
    session_vars = {
        'authenticated': False,
        'current_receipt': None,
        'receipt_details': None,
        'processing_stage': "upload",
        'duplicate_receipt': False,
        'file_type': None,
        'file_hash': None
    }
    for key, value in session_vars.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Authentication
def check_auth():
    try:
        VALID_TOKENS = {
            "client1": "token-abc123",
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
    },
    openai_api_key=st.secrets["OPENAI_API_KEY"]
)

def reset_processing():
    st.session_state.current_receipt = None
    st.session_state.receipt_details = None
    st.session_state.processing_stage = "upload"
    st.session_state.duplicate_receipt = False
    st.session_state.file_type = None
    st.session_state.file_hash = None
    st.rerun()

def sanitize_filename(text):
    return re.sub(r'[^\w_.-]', '', text.replace(' ', '_'))

def analyze_pdf_content(file_bytes):
    """Quickly determine if PDF contains extractable text"""
    try:
        reader = PyPDF2.PdfReader(BytesIO(file_bytes))
        # Check first page only for speed
        text = reader.pages[0].extract_text() or ""
        return len(text.strip()) > 50  # Has substantial text
    except:
        return False

def extract_text_from_pdf(file_bytes):
    """Extract text from PDF efficiently"""
    try:
        reader = PyPDF2.PdfReader(BytesIO(file_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text.strip()
    except Exception as e:
        print(f"PDF text extraction error: {e}")
        return ""

def get_file_extension(filename):
    """Extract file extension from filename"""
    return filename.lower().split('.')[-1] if '.' in filename else ""

st.title("📄 Professional Receipt Processor")

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
                options=["Operational", "Carpenter", "Equipment", "McCabe", "Macken E90"],
                index=0
            )
        
        notes = st.text_area("Notes", max_chars=200)
        
        col5, col6 = st.columns(2)
        with col5:
            submitted = st.form_submit_button("Submit Verified Details")
        with col6:
            cancel_verify = st.form_submit_button("Cancel")
        
        if cancel_verify:
            reset_processing()
            return None
            
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
                'payment_type': payment_type,
                'category': category,
                'notes': notes
            }
    return None

# Main processing flow
if st.session_state.processing_stage == "upload":
    st.subheader("1. Upload Receipt")
    uploaded_file = st.file_uploader("Select PDF or image receipt", 
                                   type=["pdf", "jpg", "jpeg", "png", "webp"])
    
    if uploaded_file:
        file_bytes = uploaded_file.read()
        st.session_state.current_receipt = file_bytes
        st.session_state.file_hash = hashlib.md5(file_bytes).hexdigest()
        file_extension = get_file_extension(uploaded_file.name)
        
        with st.spinner("Analyzing file type..."):
            try:
                processing_method = None
                extracted_data = None
                
                if file_extension == "pdf":
                    # Quick PDF content analysis to choose optimal method
                    has_text = analyze_pdf_content(file_bytes)
                    
                    if has_text:
                        # Use cheaper text extraction for text-based PDFs
                        st.info("📄 Text PDF detected - extracting text efficiently...")
                        text_content = extract_text_from_pdf(file_bytes)
                        if text_content:
                            extracted_data = processor.parse_receipt_text(text_content)
                            processing_method = "text_extraction"
                        else:
                            st.warning("Text extraction failed, trying AI vision...")
                            has_text = False
                    
                    if not has_text or not extracted_data:
                        # Fallback to vision for image-based PDFs or failed text extraction
                        st.info("🖼️ Image PDF detected - using AI vision...")
                        extracted_data = processor.parse_receipt_image(file_bytes, "pdf")
                        processing_method = "vision"
                
                else:
                    # Image files - use vision directly
                    st.info("📸 Image detected - analyzing with AI...")
                    if file_extension in ['jpg', 'jpeg']:
                        file_type = 'jpeg'
                    else:
                        file_type = file_extension
                    
                    extracted_data = processor.parse_receipt_image(file_bytes, file_type)
                    processing_method = "vision"
                    st.image(file_bytes, caption="Uploaded Receipt", use_container_width=True)
                
                if not extracted_data:
                    st.error("Could not extract data from file")
                    st.session_state.processing_stage = "upload"
                    st.stop()
                
                # Check for duplicate receipt
                if processor.check_duplicate_receipt(extracted_data['receipt_number']):
                    st.session_state.duplicate_receipt = True
                    st.session_state.receipt_details = extracted_data
                    st.warning('⚠️ This receipt appears to have already been processed.\nClick the "X" to cancel or click "Process another receipt"')
                    st.json(st.session_state.receipt_details)
                else:
                    st.session_state.receipt_details = extracted_data
                    st.session_state.processing_stage = "verify"
                    st.rerun()
                    
            except Exception as e:
                st.error(f"Error processing file: {str(e)}")
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
            st.session_state.processing_stage = "submit"
            st.rerun()

elif st.session_state.processing_stage == "submit":
    st.subheader("3. Submit to Google Sheets")
    
    if st.session_state.receipt_details and st.session_state.current_receipt:
        complete_data = st.session_state.receipt_details
        
        filename = f"{sanitize_filename(complete_data['item'])}_{complete_data['receipt_number']}_{complete_data['cost']}.pdf"
        
        st.json({
            "Item": complete_data['item'],
            "Cost": complete_data['cost'],
            "Date": complete_data['date'],
            "Vendor/Source": complete_data['source'],
            "Receipt Number": complete_data['receipt_number'],
            "Payment Type": complete_data.get('payment_type', 'Reimbursement'),
            "Category": complete_data.get('category', 'Operational'),
            "Notes": complete_data.get('notes', '')
        })
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Confirm and Submit", type="primary"):
                with st.spinner("Saving to Google Sheets..."):
                    try:
                        cost_value = float(complete_data['cost'])
                        
                        # Convert date to proper format for Google Sheets
                        # Keep it as YYYY-MM-DD format which Google Sheets automatically recognizes as a date
                        # The user can then format the column in Sheets to display as MM/DD/YYYY
                        sheet_data = [
                            complete_data['date'],  # Keep as YYYY-MM-DD for proper date recognition
                            complete_data['source'],
                            complete_data.get('payment_type', 'Reimbursement'),
                            cost_value if complete_data.get('category') == 'Operational' else '',
                            cost_value if complete_data.get('category') == 'Carpenter' else '',
                            cost_value if complete_data.get('category') == 'Equipment' else '',
                            cost_value if complete_data.get('category') == 'McCabe' else '',
                            cost_value if complete_data.get('category') == 'Macken E90' else '',
                            complete_data.get('notes', ''),
                            complete_data['item'],
                            complete_data['receipt_number']
                        ]
                        
                        result = processor.append_to_sheet(sheet_data)
                        if result and result.get("status") == "success":
                            st.session_state.processing_stage = "complete"
                            st.rerun()
                        else:
                            st.error(result.get("message", "Submission failed"))
                    except Exception as e:
                        st.error(f"Submission failed: {str(e)}")
        with col2:
            if st.button("Cancel"):
                reset_processing()

elif st.session_state.processing_stage == "complete":
    st.success("✅ Processing complete! Data saved to Google Sheets.")
    
    complete_data = st.session_state.receipt_details
    filename = f"{sanitize_filename(complete_data['item'])}_{complete_data['receipt_number']}_{complete_data['cost']}.pdf"
    
    st.download_button(
        "Download Renamed Receipt",
        data=st.session_state.current_receipt,
        file_name=filename,
        mime="application/pdf"
    )
    
    if st.button("Process Another Receipt"):
        reset_processing()
