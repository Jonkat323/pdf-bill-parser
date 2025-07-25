import openai
import os
import csv
import json
import re
import pdfplumber
import pytesseract
import streamlit as st
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from pdf2image import convert_from_path

load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Folder paths
INPUT_FOLDER = Path("bills")
OUTPUT_FILE = Path("output/results.csv")
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Set up the CSV headers
csv_headers = ["filename", "provider", "account_number", "start_date", "end_date", "kWh_usage", "cost_per_kWh", "service_charge", "reading_type", "amount_due", "tariff_split", "notes"]

def is_scanned_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text and text.strip():
                return False  # Text found
    return True  # No text on any page

def extract_text_from_scanned_pdf(pdf_path):
    images = convert_from_path(pdf_path, dpi=300)
    text = ""
    for img in images:
        text += pytesseract.image_to_string(img, lang='eng+afr') + "\n"
    return text

def extract_data_from_gpt(text, filename):
    prompt = f"""
    You are an assistant that extracts structured **electricity billing data** from South African municipal invoices. These invoices may be in **English or Afrikaans**.

    From the bill text below, extract ONLY information related to ELECTRICITY. 
    🛑 Ignore all other services such as water, sewer, refuse, property rates, deposits, sundry charges, or arrears.

    Extract the following fields:
    - **provider**: The name of the municipality or electricity supplier (e.g. City of Cape Town, Eskom, eThekwini).
    - **account_number**: The customer’s electricity account number.
    - **start_date**: The start date of the billing period (format: YYYY-MM-DD).
    - **end_date**: The end date of the billing period (format: YYYY-MM-DD).
    - **kWh_usage**: Total electricity usage in kilowatt-hours (kWh) — actual usage only, not estimated or carried forward.
    - **cost_per_kWh**: Average or stated cost per kilowatt-hour. If multiple rates apply, use the blended or dominant rate.
    - **service_charge**: Any fixed or daily service/connection charges for electricity only.
    - **reading_type**: Indicate "Actual" or "Estimated". Default to "Actual" if not clearly stated.
    - **amount_due**: Total amount due for electricity charges only, including VAT. Do NOT include arrears or unrelated services. If the amount is "R 59,670.31", return it as **59670.31** — never drop digits due to formatting.

    **Important formatting instructions:**
    - Your response must be valid JSON. Do not include comments, extra text, or formatting outside the JSON block.
    - Each key-value pair must be separated by a comma.
    - Do not use trailing commas or quotation marks on numbers.
    - For all numeric fields (`kWh_usage`, `cost_per_kWh`, `service_charge`, `amount_due`), return only the number — no units (e.g. "kWh", "R", "ZAR") and no commas.
    - For missing or unknown fields, return an **empty string**.
    - All dates must follow the **YYYY-MM-DD** format.
    - Afrikaans terms (e.g. “Elektrisiteit”, “Verbruik”, “Bedrag”, “Rekening”, “BTW”, etc.) must be correctly interpreted and mapped to the above fields.

    If the bill includes **multiple tariff periods** (e.g. due to a tariff or service charge change during the billing cycle):

    - Sum the total electricity usage (in kWh) across all periods.
    - Sum any fixed electricity service charges across periods.
    - Use a **blended cost per kWh** if applicable, or leave that field blank.
    - Set `"tariff_split"` to `true`
    - In the `"notes"` field, briefly describe the tariff changes and periods, e.g.:
    "Two tariff periods: 2024-06-15 to 2024-06-30 at R2.3459/kWh and 2024-07-01 to 2024-07-15 at R2.6099/kWh"

    If no split tariffs are present:
    - Set `"tariff_split"` to `false`
    - Leave `"notes"` as an empty string

    Return the result as JSON exactly like this:

    {{
    "provider": "City of Cape Town",
    "account_number": "113220507",
    "start_date": "2023-08-01",
    "end_date": "2023-08-31",
    "kWh_usage": 59154.37,
    "cost_per_kWh": 2.34,
    "service_charge": 2495.50,
    "reading_type": "Actual",
    "amount_due": 162836.21,
    "tariff_split": true,
    "notes": "Two tariff periods: 2024-06-15 to 2024-06-30 at R2.3459 and 2024-07-01 to 2024-07-15 at R2.6099"
    }}

    Bill text:
    {text}
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",  # or "gpt-4o" if needed
        messages=[{"role": "user", "content": prompt}]
    )

    content = response.choices[0].message.content  # ✅ Now defined

    try:
        json_str = re.search(r'\{.*\}', content, re.DOTALL).group()
        data = json.loads(json_str)
        data["filename"] = filename
        return data
    except Exception as e:
        print(f"❌ Failed to parse GPT output for {filename}: {e}")
        print("GPT Response:\n", content)
        return None
    
def extract_text_from_pdf(pdf_path):
    if is_scanned_pdf(pdf_path):
        print(f"📷 Detected scanned PDF: {pdf_path}")
        return extract_text_from_scanned_pdf(pdf_path)
    else:
        print(f"📄 Detected text-based PDF: {pdf_path}")
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text

def main():
    results = []

    for pdf_file in INPUT_FOLDER.glob("*.pdf"):
        print(f"Processing {pdf_file.name}")
        text = extract_text_from_pdf(pdf_file)
        result = extract_data_from_gpt(text, pdf_file.name)
        if result:
            results.append(result)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_headers)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✅ Exported {len(results)} bills to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
