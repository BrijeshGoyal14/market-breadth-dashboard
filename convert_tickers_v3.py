import requests
import re
import difflib
import urllib.parse
import time

def normalize(text):
    return re.sub(r'[^A-Z0-9]', '', text.upper())

def search_yahoo_directly(company_name):
    """Pings Yahoo Finance's live search engine to guess the ticker."""
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(company_name)}&quotesCount=3"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'} # Yahoo requires a User-Agent
    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        if 'quotes' in data:
            for quote in data['quotes']:
                sym = quote.get('symbol', '')
                # Force it to pick the Indian listing (.NS or .BO)
                if sym.endswith('.NS') or sym.endswith('.BO'):
                    return sym
    except Exception:
        pass
    return None

print("1. Reading your Book2.csv file...")
with open("Book2.csv", "r") as f:
    raw_lines = f.readlines()

csv_names = [line.strip().replace('"', '').replace(',', '').replace('-EQ', '').strip() for line in raw_lines if line.strip()]

print("2. Fetching Official Tickers from Angel One...")
url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
response = requests.get(url).json()

master_dict = {} 
for item in response:
    seg = item.get("exch_seg")
    sym = item.get("symbol", "")
    name = item.get("name", "")
    
    yahoo_ticker = None
    if seg == "NSE" and sym.endswith("-EQ"):
        yahoo_ticker = sym.replace("-EQ", ".NS")
    elif seg == "BSE":
        yahoo_ticker = sym + ".BO"
        
    if yahoo_ticker:
        master_dict[normalize(name)] = yahoo_ticker
        master_dict[normalize(sym.replace('-EQ', ''))] = yahoo_ticker

print("3. Running primary matches...")
official_tickers = []
unmatched_names = []
master_keys = list(master_dict.keys())

for name in csv_names:
    norm_name = normalize(name)
    
    # Strategy A & B: Exact or Substring
    if norm_name in master_dict:
        official_tickers.append(master_dict[norm_name])
        continue
        
    matched = False
    for m_key in master_keys:
        if (norm_name in m_key or m_key in norm_name) and len(m_key) > 4:
            official_tickers.append(master_dict[m_key])
            matched = True
            break
            
    if not matched:
        unmatched_names.append(name)

print(f"Matched {len(official_tickers)} locally. Sending the remaining {len(unmatched_names)} to Yahoo Finance Search...")

# Strategy C: Live Yahoo Search for the stubborn ones
yahoo_matches = 0
for name in unmatched_names:
    time.sleep(0.1) # Be polite to Yahoo's servers
    found_ticker = search_yahoo_directly(name)
    if found_ticker:
        official_tickers.append(found_ticker)
        yahoo_matches += 1
    else:
        # If Yahoo can't find it, it likely doesn't exist or was delisted
        print(f"  [Skipping] Completely unfindable on Yahoo: {name}")

official_tickers = list(set(official_tickers)) # Remove duplicates

print(f"\n✅ Total Final Tickers Recovered: {len(official_tickers)}!")
print("4. Saving to VCP_Stocks_Yahoo.csv...")

with open("VCP_Stocks_Yahoo.csv", "w") as f:
    for ticker in official_tickers:
        f.write(f"{ticker}\n")
        
print("🎉 Done! Your dashboard is ready to process the full list.")