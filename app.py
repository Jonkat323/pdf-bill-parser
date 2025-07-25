import streamlit as st
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import json
import re
import pandas as pd
import openai
from openai import OpenAI
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
api_key = st.secrets["OPENAI_API_KEY"]
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# ---------- Setup ----------
st.set_page_config(page_title="Electricity Bill Parser", layout="wide")

st.title("⚡ Electricity Bill Parser")
st.markdown("Upload scanned or digital PDF electricity bills to extract structured CSV data.")

# Session state for file handling
if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = []

if "parsed_results" not in st.session_state:
    st.session_state.parsed_results = []

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# Prompt template
def build_prompt(text):
    return f"""
You are an assistant that extracts structured electricity billing data from South African municipal invoices.

From the bill text below, extract ONLY the charges related to ELECTRICITY. Ignore charges for water, sewer, refuse, property rates, and any other services.

Return:
- Provider
- Account Number
- Bill Period Start Date
- Bill Period End Date
- Total Electricity Usage in kWh (sum all usage across tariffs)
- Cost Per kWh
- Total Service Charge (sum across periods)
- Reading Type (Actual/Estimated)
- Amount Due (electricity only, not total that has VAT — no arrears or other services)
- Tariff Split: true if more than one tariff appears
- Notes: short summary if a split tariff or special case is detected

Rules:
- Your response must be valid JSON. Do not include comments, extra text, or formatting outside the JSON block.
- All values must be strings or numbers — no units, commas, or text artifacts
- Dates must be in YYYY-MM-DD
- If a field isn’t available, return an empty string
- Do not use trailing commas or quotation marks on numbers.
- For all numeric fields (`kWh_usage`, `cost_per_kWh`, `service_charge`, `amount_due`), return only the number — no units (e.g. "kWh", "R", "ZAR") and no commas.
- Afrikaans terms (e.g. “Elektrisiteit”, “Verbruik”, “Bedrag”, “Rekening”, “BTW”, etc.) must be correctly interpreted and mapped to the above fields.

Bill text:
{text}
"""

# ---------- Utility Functions ----------
def extract_text_from_pdf(uploaded_file):
    text = ""
    #try:
    #   with fitz.open(stream=uploaded_file.read(), filetype="pdf") as doc:
    #        for page in doc:
    #            page_text = page.get_text().strip()
    #            if page_text:
    #                text += page_text + "\n"
    #            else:
    #                pix = page.get_pixmap(dpi=300)
    #                image = Image.open(io.BytesIO(pix.tobytes("png")))
    #                text += pytesseract.image_to_string(image) + "\n"
    #except Exception as e:
    #    return "", f"Failed to extract text: {e}"
    #return text.strip(), None
    try:
    # Try PyMuPDF or PyPDF2 here
    if not extracted_text.strip():
        raise ValueError("No extractable text found in PDF")

except Exception:
    st.warning("This PDF appears to be scanned and needs OCR, which isn’t supported on this server.")

def parse_with_gpt(text):
    prompt = build_prompt(text)
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        output = response.choices[0].message.content.strip()

        if not output:
            return {"error": "GPT returned empty response."}

        # Try direct load first
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # Try to extract JSON block manually if extra text present
            match = re.search(r"\{.*\}", output, re.DOTALL)
            if match:
                json_part = match.group(0)
                return json.loads(json_part)
            else:
                return {"error": f"Could not extract JSON from GPT output:\n{output}"}

    except Exception as e:
        return {"error": f"OpenAI API error: {str(e)}"}


# ---------- File Upload ----------
uploaded = st.file_uploader(
    "Upload one or more PDF bills",
    type="pdf",
    accept_multiple_files=True,
    key=st.session_state.uploader_key
)

# Only reprocess if new files are uploaded
if uploaded:
    # Only reprocess if results are empty or different files were uploaded
    if (
        not st.session_state.parsed_results or
        len(uploaded) != len(st.session_state.uploaded_files) or
        any(f.name != s.name for f, s in zip(uploaded, st.session_state.uploaded_files))
    ):
        st.session_state.uploaded_files = uploaded
        st.session_state.parsed_results = []

        with st.spinner("⏳ Processing uploaded files..."):
            for file in uploaded:
                filename = file.name
                raw_text, error = extract_text_from_pdf(file)

                if error or not raw_text.strip():
                    st.session_state.parsed_results.append({
                        "filename": filename,
                        "error": error or "No readable text found."
                    })
                    continue

                data = parse_with_gpt(raw_text)
                if "error" in data:
                    st.session_state.parsed_results.append({
                        "filename": filename,
                        "error": data["error"]
                    })
                else:
                    data["filename"] = filename
                    st.session_state.parsed_results.append(data)



# ---------- Clear Button ----------
if st.button("🗑️ Clear Uploaded Files"):
    st.session_state.uploaded_files = []
    st.session_state.parsed_results = []
    st.session_state.uploader_key += 1  # Force reset uploader component
    st.rerun()


# ---------- Results Table & Download ----------
if st.session_state.parsed_results:
    st.success("✅ All files processed successfully.")
    st.subheader("📋 Extracted Data")
    df = pd.DataFrame(st.session_state.parsed_results)
    st.dataframe(df)

    csv = df.to_csv(index=False)
    st.download_button(
        label="⬇️ Download CSV",
        data=csv,
        file_name="electricity_bills.csv",
        mime="text/csv"
    )