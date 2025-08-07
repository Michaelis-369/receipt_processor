import re
import hashlib
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
    }
    for key, value in session_vars.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# Authentication and processor initialization remain the same
[... keep your existing auth and processor init code ...]

def reset_processing():
    st.session_state.current_receipt = None
    st.session_state.receipt_details = None
    st.session_state.processing_stage = "upload"
    st.rerun()

def sanitize_filename(text):
    return re.sub(r'[^\w_.-]', '', text.replace(' ', '_'))

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
            date = st.date_input("Date*", datetime.strptime(date_str, "%Y-%m-%d") if 'date' in extracted_data else datetime.now())
            source = st.text_input("Source", extracted_data.get('source', 'unknown'))
        
        receipt_number = st.text_input("Receipt Number", extracted_data.get('receipt_number', ''))
        
        submitted = st.form_submit_button("Submit Verified Details")
        if submitted:
            if not item or not cost:
                st.error("Required fields marked with *")
                return None
            
            clean_cost = re.sub(r'[^\d.]', '', cost) or "0"
            formatted_cost = f"{float(clean_cost):.2f}"
            
            return {
                'item': ' '.join(item.split()[:2]).lower(),
                'cost': formatted_cost,
                'date': date.strftime("%Y-%m-%d"),
                'source': source.lower(),
                'receipt_number': receipt_number or f"receipt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            }
    return None

# Main processing flow
if st.session_state.processing_stage == "upload":
    st.subheader("1. Upload Receipt")
    uploaded_file = st.file_uploader("Select PDF receipt", type="pdf")
    
    if uploaded_file:
        with st.spinner("Extracting receipt data..."):
            file_bytes = uploaded_file.read()
            
            try:
                text = "\n".join(
                    page.extract_text() or "" 
                    for page in PyPDF2.PdfReader(BytesIO(file_bytes)).pages
                )
                extracted_data = processor.parse_receipt_text(text)
                
                if extracted_data:
                    st.session_state.receipt_details = extracted_data
                    st.session_state.current_receipt = file_bytes
                    st.session_state.processing_stage = "verify"
                    st.rerun()
                else:
                    st.error("Could not extract data from PDF")
                    st.session_state.processing_stage = "verify"
            except Exception as e:
                st.error(f"PDF processing error: {str(e)}")
                st.session_state.processing_stage = "verify"

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
        
        # Generate standardized filename
        filename = f"{sanitize_filename(complete_data.get('name', 'receipt'))}_{sanitize_filename(complete_data['item'])}_{complete_data['receipt_number']}_{complete_data['cost']}.pdf"
        
        st.json({
            "Item": complete_data['item'],
            "Cost": complete_data['cost'],
            "Date": complete_data['date'],
            "Source": complete_data['source'],
            "Receipt Number": complete_data['receipt_number'],
            "Filename": filename
        })
        
        if st.button("Confirm and Submit"):
            with st.spinner("Saving to Google Sheets..."):
                try:
                    # Send to Google Sheets
                    if processor.append_to_sheet([
                        complete_data.get('name', 'Manual Entry'),
                        complete_data.get('email', 'no_email@example.com'),
                        complete_data['item'],
                        complete_data['cost'],
                        complete_data['date'],
                        complete_data['source'],
                        complete_data['receipt_number']
                    ]):
                        st.session_state.processing_stage = "complete"
                        st.rerun()
                except Exception as e:
                    st.error(f"Submission failed: {str(e)}")

elif st.session_state.processing_stage == "complete":
    st.success("✅ Processing complete! Data saved to Google Sheets.")
    
    # Generate download filename
    complete_data = st.session_state.receipt_details
    filename = f"{sanitize_filename(complete_data.get('name', 'receipt'))}_{sanitize_filename(complete_data['item'])}_{complete_data['receipt_number']}_{complete_data['cost']}.pdf"
    
    st.download_button(
        "Download Renamed Receipt",
        data=st.session_state.current_receipt,
        file_name=filename,
        mime="application/pdf"
    )
    
    if st.button("Process Another Receipt"):
        reset_processing()
