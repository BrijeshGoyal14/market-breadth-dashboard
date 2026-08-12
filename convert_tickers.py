import pandas as pd
import requests
import re

def clean_name(text):
    """Removes quotes, commas, and the incorrect -EQ tags to extract the raw name."""
    cleaned = text.strip().replace('"', '').replace(',', '').replace('-EQ', '').strip()
    return cleaned.upper()

print("1. Reading your Book2.csv file...")
with open("Book2.csv", "r") as f:
    raw_lines = f.readlines()

csv_names = [clean_name(line) for line in raw_lines if line.strip()]

print("2. Fetching Official NSE Tickers from Angel One...")
url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
response = requests.get(url).json()

# Create a mapping of Company Name -> Official Symbol (e.g., "NESTLE INDIA" -> "NESTLEIND-EQ")
# We also map the Symbol to itself just in case some of your entries are already correct
name_to_symbol = {}
for item in response:
    if item.get("exch_seg") == "NSE" and item.get("symbol").endswith("-EQ"):
        sym = item["symbol"]
        name_to_symbol[item["name"].upper()] = sym
        name_to_symbol[sym.replace('-EQ', '').upper()] = sym

print("3. Matching and creating new list...")
official_tickers = []
unmatched = []

for name in csv_names:
    if name in name_to_symbol:
        official_tickers.append(name_to_symbol[name])
    else:
        # Tries partial matching if exact match fails
        matched = False
        for master_name, master_sym in name_to_symbol.items():
            if name.startswith(master_name) or master_name.startswith(name):
                official_tickers.append(master_sym)
                matched = True
                break
        if not matched:
            unmatched.append(name)

# Remove duplicates
official_tickers = list(set(official_tickers))

print(f"\n✅ Successfully matched {len(official_tickers)} official tickers!")
if unmatched:
    print(f"⚠️ Could not find exact matches for {len(unmatched)} obscure names. (They will be skipped)")

print("4. Saving to VCP_Stocks.csv...")
with open("VCP_Stocks.csv", "w") as f:
    for ticker in official_tickers:
        f.write(f"{ticker}\n")
        
print("🎉 Done! You can now use VCP_Stocks.csv in your dashboard.")