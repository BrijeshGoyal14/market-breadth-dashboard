import streamlit as st
import pandas as pd
import pyotp
import requests
import time
import yfinance as yf
import concurrent.futures
from SmartApi import SmartConnect
from datetime import datetime, timedelta

# NEW: Import os and dotenv to read the hidden .env file
import os
from dotenv import load_dotenv

# Load environment variables from the .env file BEFORE setting credentials
load_dotenv()

# ==========================================
# 1. ANGEL ONE CREDENTIALS
# ==========================================
API_KEY = os.getenv("API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
PIN = os.getenv("PIN")
TOTP_SECRET = os.getenv("TOTP_SECRET")

# Page Configuration
st.set_page_config(layout="wide", page_title="Angel One Indian Sector Dashboard")
st.title("⚡ Indian Market Sector Dashboard (Angel One SmartAPI)")
st.markdown("Fast live tracking for SMA, RSI, and RS 55 across Indian sectors.")

# 2. Define Stocks and Sectors
STOCKS = {
    # Financial Services
    "HDFCBANK-EQ": "Financials", "ICICIBANK-EQ": "Financials", "SBIN-EQ": "Financials",
    "AXISBANK-EQ": "Financials", "KOTAKBANK-EQ": "Financials", "BAJFINANCE-EQ": "Financials",
    "CHOLAFIN-EQ": "Financials", "MUTHOOTFIN-EQ": "Financials", "PFC-EQ": "Financials",
    "RECLTD-EQ": "Financials", "HDFCLIFE-EQ": "Financials", "SBILIFE-EQ": "Financials",
    "BAJAJFINSV-EQ": "Financials", "INDUSINDBK-EQ": "Financials", "PNB-EQ": "Financials",
    "BANKBARODA-EQ": "Financials", "IOB-EQ": "Financials", "UNIONBANK-EQ": "Financials",

    # Information Technology
    "TCS-EQ": "IT", "INFY-EQ": "IT", "WIPRO-EQ": "IT",
    "HCLTECH-EQ": "IT", "TECHM-EQ": "IT", "LTIM-EQ": "IT",
    "PERSISTENT-EQ": "IT", "COFORGE-EQ": "IT", "MPHASIS-EQ": "IT",
    "KPITTECH-EQ": "IT", "TATAELXSI-EQ": "IT", "OFSS-EQ": "IT", "CYIENT-EQ": "IT",

    # Oil, Gas & Consumable Fuels
    "RELIANCE-EQ": "Oil & Gas", "ONGC-EQ": "Oil & Gas", "COALINDIA-EQ": "Oil & Gas",
    "BPCL-EQ": "Oil & Gas", "IOC-EQ": "Oil & Gas", "HINDPETRO-EQ": "Oil & Gas",
    "GAIL-EQ": "Oil & Gas", "IGL-EQ": "Oil & Gas", "MGL-EQ": "Oil & Gas",
    "PETRONET-EQ": "Oil & Gas", "GUJGASLTD-EQ": "Oil & Gas", "OIL-EQ": "Oil & Gas",

    # Automobile and Auto Components
    "BAJAJ-AUTO-EQ": "Automobile", "M&M-EQ": "Automobile", "MARUTI-EQ": "Automobile",
    "HEROMOTOCO-EQ": "Automobile", "EICHERMOT-EQ": "Automobile", "TVSMOTOR-EQ": "Automobile", 
    "ASHOKLEY-EQ": "Automobile", "MRF-EQ": "Automobile", "BOSCHLTD-EQ": "Automobile", 
    "MOTHERSON-EQ": "Automobile", "BALKRISIND-EQ": "Automobile", "TIINDIA-EQ": "Automobile",

    # Healthcare
    "SUNPHARMA-EQ": "Healthcare", "CIPLA-EQ": "Healthcare", "DRREDDY-EQ": "Healthcare",
    "DIVISLAB-EQ": "Healthcare", "APOLLOHOSP-EQ": "Healthcare", "LUPIN-EQ": "Healthcare",
    "AUROPHARMA-EQ": "Healthcare", "ZYDUSLIFE-EQ": "Healthcare", "BIOCON-EQ": "Healthcare",
    "MAXHEALTH-EQ": "Healthcare", "SYNGENE-EQ": "Healthcare", "LALPATHLAB-EQ": "Healthcare",

    # Fast Moving Consumer Goods (FMCG)
    "ITC-EQ": "FMCG", "HUL-EQ": "FMCG", "NESTLEIND-EQ": "FMCG",
    "BRITANNIA-EQ": "FMCG", "TATACONSUM-EQ": "FMCG", "GODREJCP-EQ": "FMCG",
    "DABUR-EQ": "FMCG", "MARICO-EQ": "FMCG", "COLPAL-EQ": "FMCG",
    "VBL-EQ": "FMCG", "UBL-EQ": "FMCG", "MCDOWELL-N-EQ": "FMCG",

    # Metals & Mining
    "TATASTEEL-EQ": "Metals", "JSWSTEEL-EQ": "Metals", "HINDALCO-EQ": "Metals",
    "VEDL-EQ": "Metals", "JINDALSTEL-EQ": "Metals", "NMDC-EQ": "Metals",
    "SAIL-EQ": "Metals", "NATIONALUM-EQ": "Metals", "HINDZINC-EQ": "Metals",

    # Construction Materials (Cement)
    "GRASIM-EQ": "Construction Mat", "ULTRACEMCO-EQ": "Construction Mat", "SHREECEM-EQ": "Construction Mat",
    "AMBUJACEM-EQ": "Construction Mat", "ACC-EQ": "Construction Mat", "DALBHARAT-EQ": "Construction Mat",
    "RAMCOCEM-EQ": "Construction Mat", "JKCEMENT-EQ": "Construction Mat", "COROMANDEL-EQ": "Construction Mat",

    # Telecommunication
    "BHARTIARTL-EQ": "Telecom", "IDEA-EQ": "Telecom", "TATACOMM-EQ": "Telecom",
    "INDUSTOWER-EQ": "Telecom", "ROUTE-EQ": "Telecom", "TEJASNET-EQ": "Telecom",

    # Power
    "NTPC-EQ": "Power", "POWERGRID-EQ": "Power", "TATAPOWER-EQ": "Power",
    "ADANIGREEN-EQ": "Power", "ADANIPOWER-EQ": "Power", "JSWENERGY-EQ": "Power",
    "NHPC-EQ": "Power", "TORNTPOWER-EQ": "Power", "CESC-EQ": "Power",

    # Capital Goods & Defence
    "SIEMENS-EQ": "Capital Goods", "ABB-EQ": "Capital Goods", "HAL-EQ": "Capital Goods",
    "BEL-EQ": "Capital Goods", "CUMMINSIND-EQ": "Capital Goods", "CGPOWER-EQ": "Capital Goods",
    "POLYCAB-EQ": "Capital Goods", "HAVELLS-EQ": "Capital Goods", "SUZLON-EQ": "Capital Goods",

    # Chemicals
    "PIDILITIND-EQ": "Chemicals", "SRF-EQ": "Chemicals", "TATACHEM-EQ": "Chemicals",
    "DEEPAKNTR-EQ": "Chemicals", "AARTIIND-EQ": "Chemicals", "ATUL-EQ": "Chemicals",
    "NAVINFLUOR-EQ": "Chemicals", "PIIND-EQ": "Chemicals", "UPL-EQ": "Chemicals",

    # Consumer Services & Retail
    "TRENT-EQ": "Consumer Retail", "ZOMATO-EQ": "Consumer Retail", "NYKAA-EQ": "Consumer Retail",
    "DMART-EQ": "Consumer Retail", "TITAN-EQ": "Consumer Retail", "JUBLFOOD-EQ": "Consumer Retail",
    "IRCTC-EQ": "Consumer Retail", "PAGEIND-EQ": "Consumer Retail", "BATAINDIA-EQ": "Consumer Retail",

    # Realty / Real Estate
    "DLF-EQ": "Real Estate", "MACROTECH-EQ": "Real Estate", "GODREJPROP-EQ": "Real Estate",
    "OBEROIRLTY-EQ": "Real Estate", "PRESTIGE-EQ": "Real Estate", "PHOENIXLTD-EQ": "Real Estate",

    # Infrastructure & Construction
    "LT-EQ": "Infrastructure", "GMRINFRA-EQ": "Infrastructure", "IRB-EQ": "Infrastructure",
    "RVNL-EQ": "Infrastructure", "IRCON-EQ": "Infrastructure", "KEC-EQ": "Infrastructure"
}

# 3. Helper: Fetch Market Caps Fast (Parallel) via Yahoo Finance
@st.cache_data(ttl=86400) # Caches once per day
def get_market_caps():
    caps = {}
    def fetch_cap(symbol):
        yf_symbol = symbol.replace("-EQ", ".NS")
        try:
            return symbol, yf.Ticker(yf_symbol).info.get('marketCap', 1)
        except Exception:
            return symbol, 1 # Fallback to equal weight if data is missing

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(fetch_cap, sym) for sym in STOCKS.keys()]
        for future in concurrent.futures.as_completed(futures):
            sym, cap = future.result()
            caps[sym] = cap
            
    return caps

# 4. Helper: Fetch Instrument Tokens
@st.cache_data(ttl=86400)
def get_token_map():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    response = requests.get(url).json()
    token_map = {}
    for item in response:
        if item.get("exch_seg") == "NSE" and item.get("symbol") in STOCKS:
            token_map[item["symbol"]] = item["token"]
    
    token_map["NIFTY"] = "99926000"
    return token_map

# 5. Helper: Connect to SmartAPI
def get_smart_api_session():
    smartApi = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    session = smartApi.generateSession(CLIENT_ID, PIN, totp)
    if session.get('status') == False:
        st.error(f"Angel One Login Failed: {session.get('message')}")
        return None
    return smartApi

# 6. Data Processing Engine
@st.cache_data(ttl=300)
def fetch_and_calculate():
    smartApi = get_smart_api_session()
    if not smartApi:
        return pd.DataFrame()

    token_map = get_token_map()
    mcaps = get_market_caps()
    
    to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    from_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d %H:%M")

    nifty_params = {
        "exchange": "NSE",
        "symboltoken": token_map.get("NIFTY", "99926000"),
        "interval": "ONE_DAY",
        "fromdate": from_date,
        "todate": to_date
    }
    nifty_response = smartApi.getCandleData(nifty_params)
    if not nifty_response.get("status") or not nifty_response.get("data"):
        st.error("Failed to fetch Nifty 50 index data.")
        return pd.DataFrame()

    nifty_df = pd.DataFrame(nifty_response["data"], columns=["time", "open", "high", "low", "close", "volume"])
    nifty_df['time'] = pd.to_datetime(nifty_df['time'])
    nifty_df.set_index('time', inplace=True)
    nifty_close = nifty_df["close"].ffill()

    results = []

    for symbol, sector in STOCKS.items():
        token = token_map.get(symbol)
        if not token:
            continue

        try:
            time.sleep(0.4) 
            
            candle_params = {
                "exchange": "NSE",
                "symboltoken": token,
                "interval": "ONE_DAY",
                "fromdate": from_date,
                "todate": to_date
            }
            res = smartApi.getCandleData(candle_params)
            if not res.get("status") or not res.get("data"):
                continue

            df = pd.DataFrame(res["data"], columns=["time", "open", "high", "low", "close", "volume"])
            df['time'] = pd.to_datetime(df['time'])
            df.set_index('time', inplace=True)
            df["close"] = df["close"].ffill()

            if len(df) < 2: 
                continue

            df["SMA_20"] = df["close"].rolling(window=20).mean()
            df["SMA_50"] = df["close"].rolling(window=50).mean()
            df["SMA_100"] = df["close"].rolling(window=100).mean()

            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            df["RSI_14"] = 100 - (100 / (1 + rs))

            aligned_nifty = nifty_close.reindex(df.index, method="ffill")
            df["Stock_Ret_55"] = df["close"].pct_change(periods=55)
            nifty_ret_55 = aligned_nifty.pct_change(periods=55)
            df["RS_55"] = df["Stock_Ret_55"] - nifty_ret_55

            latest = df.iloc[-1]
            current_price = latest["close"]
            prev_close = df["close"].iloc[-2]
            daily_change_rs = current_price - prev_close
            daily_change_pct = (daily_change_rs / prev_close) * 100

            results.append({
                "Ticker": symbol.replace("-EQ", ""),
                "Sector": sector,
                "MarketCap": mcaps.get(symbol, 1),
                "CurrentPrice": current_price,
                "ChangeRs": daily_change_rs,
                "ChangePct": daily_change_pct,
                "RS_55_Pass": 1 if (pd.notna(latest.get("RS_55")) and latest.get("RS_55") > 0) else 0,
                "RSI_Pass": 1 if (pd.notna(latest.get("RSI_14")) and latest.get("RSI_14") > 50) else 0,
                "SMA20_Pass": 1 if (pd.notna(latest.get("SMA_20")) and current_price > latest.get("SMA_20")) else 0,
                "SMA50_Pass": 1 if (pd.notna(latest.get("SMA_50")) and current_price > latest.get("SMA_50")) else 0,
                "SMA100_Pass": 1 if (pd.notna(latest.get("SMA_100")) and current_price > latest.get("SMA_100")) else 0,
            })
        except Exception:
            continue

    return pd.DataFrame(results)

# Render UI
with st.spinner("Fetching live data from Angel One SmartAPI..."):
    master_df = fetch_and_calculate()

if not master_df.empty:
    sectors = master_df["Sector"].unique()
    
    left_col, right_col = st.columns([2.5, 1.5], gap="large")

    with left_col:
        st.subheader("Market Breadth")
        
        # --- NEW DISPLAY TOGGLE ---
        display_mode = st.radio("Display Mode:", ["Number of Stocks", "% of Sector Market Cap"], horizontal=True)

        dashboard_data = []
        for sector in sectors:
            sec_df = master_df[master_df["Sector"] == sector]
            total_mc = sec_df["MarketCap"].sum()

            def calc_metric(flag):
                if display_mode == "Number of Stocks":
                    return f"{sec_df[flag].sum()} / {len(sec_df)}"
                else:
                    passed_mc = sec_df[sec_df[flag] == 1]["MarketCap"].sum()
                    pct = (passed_mc / total_mc * 100) if total_mc > 0 else 0
                    return f"{pct:.1f}%"

            dashboard_data.append({
                "Sectors": sector,
                "RS 55 > 0": calc_metric("RS_55_Pass"),
                "RSI > 50": calc_metric("RSI_Pass"),
                "SMA 20": calc_metric("SMA20_Pass"),
                "SMA 50": calc_metric("SMA50_Pass"),
                "SMA 100": calc_metric("SMA100_Pass")
            })

        final_df = pd.DataFrame(dashboard_data)
        st.dataframe(final_df, width="stretch", hide_index=True)

        if st.button("Refresh Live Data"):
            st.cache_data.clear()
            st.rerun()

    with right_col:
        st.subheader("Stock Details")
        selected_sector = st.selectbox("1. Select a Sector:", final_df["Sectors"].tolist())
        selected_indicator = st.selectbox(
            "2. Select an Indicator:", 
            ["RS 55 > 0", "RSI > 50", "SMA 20", "SMA 50", "SMA 100"]
        )

        st.markdown(f"**Showing:** {selected_sector} stocks where {selected_indicator}")

        flag_map = {
            "RS 55 > 0": "RS_55_Pass",
            "RSI > 50": "RSI_Pass",
            "SMA 20": "SMA20_Pass",
            "SMA 50": "SMA50_Pass",
            "SMA 100": "SMA100_Pass"
        }

        flag = flag_map[selected_indicator]
        winning_stocks = master_df[(master_df["Sector"] == selected_sector) & (master_df[flag] == 1)]

        if winning_stocks.empty:
            st.write("No stocks meet this criteria right now.")
        else:
            for _, stock in winning_stocks.iterrows():
                color = "green" if stock["ChangeRs"] >= 0 else "red"
                sign = "+" if stock["ChangeRs"] >= 0 else ""

                st.markdown(
                    f"""
                    <div style="border:1px solid #ddd; padding:10px; border-radius:5px; margin-bottom:10px;">
                        <strong>{stock['Ticker']}</strong><br>
                        Price: ₹{stock['CurrentPrice']:.2f} <br>
                        Change: <span style="color:{color};">{sign}₹{stock['ChangeRs']:.2f} ({sign}{stock['ChangePct']:.2f}%)</span>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
else:
    st.error("Failed to load dashboard data. Please check your Angel One credentials and terminal logs.")