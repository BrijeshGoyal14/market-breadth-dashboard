import requests
import re
import difflib

def normalize(text):
    """Removes special chars, spaces, and makes uppercase for pure text matching."""
    return re.sub(r'[^A-Z0-9]', '', text.upper())

print("1. Reading your Book2.csv file...")
with open("Book2.csv", "r") as f:
    raw_lines = f.readlines()

csv_names = []
for line in raw_lines:
    cleaned = line.strip().replace('"', '').replace(',', '').replace('-EQ', '').strip()
    if cleaned:
        csv_names.append(cleaned)

print("2. Fetching Official Tickers from Angel One (NSE + BSE)...")
url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
response = requests.get(url).json()

master_dict = {} 

for item in response:
    seg = item.get("exch_seg")
    sym = item.get("symbol", "")
    name = item.get("name", "")
    
    yahoo_ticker = None
    # Catch NSE stocks and format for Yahoo
    if seg == "NSE" and sym.endswith("-EQ"):
        yahoo_ticker = sym.replace("-EQ", ".NS")
    # Catch BSE stocks and format for Yahoo
    elif seg == "BSE":
        yahoo_ticker = sym + ".BO"
        
    if yahoo_ticker:
        norm_name = normalize(name)
        master_dict[norm_name] = yahoo_ticker
        # Also map the symbol itself in case the CSV already has exact symbols
        master_dict[normalize(sym.replace('-EQ', ''))] = yahoo_ticker

print("3. Running aggressive Fuzzy Matching...")
official_tickers = []
unmatched = []
master_keys = list(master_dict.keys())

for name in csv_names:
    norm_name = normalize(name)
    
    # Strategy A: Exact normalized match
    if norm_name in master_dict:
        official_tickers.append(master_dict[norm_name])
        continue
        
    # Strategy B: Substring match (e.g. "TATA MOTORS LTD" matches "TATAMOTORS")
    matched = False
    for m_key in master_keys:
        if (norm_name in m_key or m_key in norm_name) and len(m_key) > 4:
            official_tickers.append(master_dict[m_key])
            matched = True
            break
    if matched:
        continue
        
    # Strategy C: Statistical Fuzzy Match (80% similarity threshold)
    close_matches = difflib.get_close_matches(norm_name, master_keys, n=1, cutoff=0.8)
    if close_matches:
        official_tickers.append(master_dict[close_matches[0]])
    else:
        unmatched.append(name)

official_tickers = list(set(official_tickers)) # Remove duplicates

print(f"\n✅ Successfully matched {len(official_tickers)} Yahoo tickers!")
if unmatched:
    print(f"⚠️ Skipped {len(unmatched)} highly obscure or delisted names.")

print("4. Saving to VCP_Stocks_Yahoo.csv...")
with open("VCP_Stocks_Yahoo.csv", "w") as f:
    for ticker in official_tickers:
        f.write(f"{ticker}\n")
        
print("🎉 Done! You can now use VCP_Stocks_Yahoo.csv in your dashboard.")