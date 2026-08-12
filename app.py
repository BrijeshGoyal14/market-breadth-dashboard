import streamlit as st
import pandas as pd
import pyotp
import requests
import time
import yfinance as yf
import concurrent.futures
import plotly.express as px
import numpy as np
from SmartApi import SmartConnect
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==========================================
# 1. API CREDENTIALS & PAGE CONFIG
# ==========================================
st.set_page_config(layout="wide", page_title="Indian Sector Dashboard")

API_KEY = os.getenv("API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
PIN = os.getenv("PIN")
TOTP_SECRET = os.getenv("TOTP_SECRET")

# ==========================================
# 2. HELPER FUNCTIONS & STYLING
# ==========================================
def load_css(file_name):
    file_path = os.path.join(os.path.dirname(__file__), file_name)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Inject Apple Design System
load_css("design.css")

def get_vcp_stocks(file_name="VCP_Stocks_Yahoo.csv"):
    """Reads the VCP stocks directly from the uploaded CSV to keep app.py clean."""
    file_path = os.path.join(os.path.dirname(__file__), file_name)
    vcp_list = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f.readlines():
                cleaned = line.strip().replace('"', '').replace(',', '')
                if cleaned:
                    vcp_list.append(cleaned)
    return vcp_list

# ==========================================
# 3. CORE ANALYTICAL ENGINES
# ==========================================
def analyze_vcp(df, nifty_close):
    if len(df) < 200:
        return None

    close = df["close"]
    volume = df["volume"]
    latest_price = close.iloc[-1]
    
    sma_50 = close.rolling(50).mean()
    sma_150 = close.rolling(150).mean()
    sma_200 = close.rolling(200).mean()
    
    c_50 = sma_50.iloc[-1]
    c_150 = sma_150.iloc[-1]
    c_200 = sma_200.iloc[-1]
    c_200_20d_ago = sma_200.iloc[-20]
    
    high_52w = close.iloc[-252:].max() if len(close) >= 252 else close.max()
    low_52w = close.iloc[-252:].min() if len(close) >= 252 else close.min()
    
    t1 = latest_price > c_150 and latest_price > c_200
    t2 = c_150 > c_200
    t3 = c_200 > c_200_20d_ago
    t4 = c_50 > c_150 and c_50 > c_200
    t5 = latest_price > c_50
    t6 = latest_price >= (1.25 * low_52w)
    t7 = latest_price >= (0.75 * high_52w)
    
    aligned_nifty = nifty_close.reindex(df.index, method="ffill")
    stk_ret = (latest_price - close.iloc[-56]) / close.iloc[-56] if len(close) >= 56 else 0
    nft_ret = (aligned_nifty.iloc[-1] - aligned_nifty.iloc[-56]) / aligned_nifty.iloc[-56] if len(aligned_nifty) >= 56 else 0
    rs_55 = stk_ret - nft_ret
    t8 = rs_55 > 0

    if not all([t1, t2, t3, t4, t5, t6, t7, t8]):
        return None

    base_high = close.iloc[-60:].max()
    base_low = close.iloc[-60:].min()
    base_depth_pct = ((base_high - base_low) / base_high) * 100
    
    recent_high = close.iloc[-10:].max()
    recent_low = close.iloc[-10:].min()
    pivot_tightness_pct = ((recent_high - recent_low) / recent_high) * 100
    
    contraction_ratio = (recent_high - recent_low) / (base_high - base_low + 1e-5)
    
    high_prices = df.get("high", close)
    low_prices = df.get("low", close)
    tr = np.maximum(high_prices - low_prices, np.abs(high_prices - close.shift(1)))
    atr_10 = tr.rolling(10).mean().iloc[-1]
    atr_50 = tr.rolling(50).mean().iloc[-1]
    atr_ratio = atr_10 / (atr_50 + 1e-5)

    vol_avg_20 = volume.rolling(20).mean().iloc[-1]
    vol_avg_5 = volume.rolling(5).mean().iloc[-1]
    vdu_ratio = vol_avg_5 / (vol_avg_20 + 1e-5)
    is_vdu = vdu_ratio < 0.65  

    dist_from_52w_high = ((high_52w - latest_price) / high_52w) * 100
    
    vcp_score = 100
    if pivot_tightness_pct > 6.0: vcp_score -= 20
    if contraction_ratio > 0.40: vcp_score -= 20
    if not is_vdu: vcp_score -= 25
    if dist_from_52w_high > 10.0: vcp_score -= 15
    if atr_ratio > 0.70: vcp_score -= 20

    return {
        "LatestPrice": latest_price,
        "DistFrom52wHigh": dist_from_52w_high,
        "BaseDepthPct": base_depth_pct,
        "PivotTightnessPct": pivot_tightness_pct,
        "ContractionRatio": contraction_ratio,
        "VDURatio": vdu_ratio,
        "IsVDU": is_vdu,
        "ATRRatio": atr_ratio,
        "RS55": rs_55 * 100,
        "VCPScore": max(0, vcp_score)
    }

# ==========================================
# 4. DATA DICTIONARIES
# ==========================================
STOCKS = {
    "HDFCBANK-EQ": "Financials", "ICICIBANK-EQ": "Financials", "SBIN-EQ": "Financials",
    "AXISBANK-EQ": "Financials", "KOTAKBANK-EQ": "Financials", "BAJFINANCE-EQ": "Financials",
    "CHOLAFIN-EQ": "Financials", "MUTHOOTFIN-EQ": "Financials", "PFC-EQ": "Financials",
    "RECLTD-EQ": "Financials", "HDFCLIFE-EQ": "Financials", "SBILIFE-EQ": "Financials",
    "BAJAJFINSV-EQ": "Financials", "INDUSINDBK-EQ": "Financials", "PNB-EQ": "Financials",
    "BANKBARODA-EQ": "Financials", "IOB-EQ": "Financials", "UNIONBANK-EQ": "Financials",
    "CANBK-EQ": "Financials", "IDFCFIRSTB-EQ": "Financials", "FEDERALBNK-EQ": "Financials",
    "TCS-EQ": "IT", "INFY-EQ": "IT", "WIPRO-EQ": "IT", "HCLTECH-EQ": "IT", "TECHM-EQ": "IT",
    "LTIM-EQ": "IT", "PERSISTENT-EQ": "IT", "COFORGE-EQ": "IT", "MPHASIS-EQ": "IT",
    "KPITTECH-EQ": "IT", "TATAELXSI-EQ": "IT", "OFSS-EQ": "IT", "CYIENT-EQ": "IT",
    "BSOFT-EQ": "IT", "SONATSOFTW-EQ": "IT", "INTELLECT-EQ": "IT",
    "RELIANCE-EQ": "Oil & Gas", "ONGC-EQ": "Oil & Gas", "COALINDIA-EQ": "Oil & Gas",
    "BPCL-EQ": "Oil & Gas", "IOC-EQ": "Oil & Gas", "HINDPETRO-EQ": "Oil & Gas",
    "GAIL-EQ": "Oil & Gas", "IGL-EQ": "Oil & Gas", "MGL-EQ": "Oil & Gas",
    "PETRONET-EQ": "Oil & Gas", "GUJGASLTD-EQ": "Oil & Gas", "OIL-EQ": "Oil & Gas",
    "CASTROLIND-EQ": "Oil & Gas", "AEGISCHEM-EQ": "Oil & Gas",
    "BAJAJ-AUTO-EQ": "Automobile", "M&M-EQ": "Automobile", "MARUTI-EQ": "Automobile",
    "HEROMOTOCO-EQ": "Automobile", "EICHERMOT-EQ": "Automobile", "TVSMOTOR-EQ": "Automobile", 
    "ASHOKLEY-EQ": "Automobile", "MRF-EQ": "Automobile", "BOSCHLTD-EQ": "Automobile", 
    "MOTHERSON-EQ": "Automobile", "BALKRISIND-EQ": "Automobile", "TIINDIA-EQ": "Automobile",
    "ESCORTS-EQ": "Automobile", "SONACOMS-EQ": "Automobile", "ENDURANCE-EQ": "Automobile",
    "SUNPHARMA-EQ": "Healthcare", "CIPLA-EQ": "Healthcare", "DRREDDY-EQ": "Healthcare",
    "DIVISLAB-EQ": "Healthcare", "APOLLOHOSP-EQ": "Healthcare", "LUPIN-EQ": "Healthcare",
    "AUROPHARMA-EQ": "Healthcare", "ZYDUSLIFE-EQ": "Healthcare", "BIOCON-EQ": "Healthcare",
    "MAXHEALTH-EQ": "Healthcare", "SYNGENE-EQ": "Healthcare", "LALPATHLAB-EQ": "Healthcare",
    "GLENMARK-EQ": "Healthcare", "IPCALAB-EQ": "Healthcare", "ALKEM-EQ": "Healthcare",
    "ITC-EQ": "FMCG", "HINDUNILVR-EQ": "FMCG", "NESTLEIND-EQ": "FMCG", "BRITANNIA-EQ": "FMCG",
    "TATACONSUM-EQ": "FMCG", "GODREJCP-EQ": "FMCG", "DABUR-EQ": "FMCG", "MARICO-EQ": "FMCG",
    "COLPAL-EQ": "FMCG", "VBL-EQ": "FMCG", "UBL-EQ": "FMCG", "MCDOWELL-N-EQ": "FMCG",
    "EMAMILTD-EQ": "FMCG", "RADICO-EQ": "FMCG", "PGHH-EQ": "FMCG",
    "TATASTEEL-EQ": "Metals", "JSWSTEEL-EQ": "Metals", "HINDALCO-EQ": "Metals",
    "VEDL-EQ": "Metals", "JINDALSTEL-EQ": "Metals", "NMDC-EQ": "Metals",
    "SAIL-EQ": "Metals", "NATIONALUM-EQ": "Metals", "HINDZINC-EQ": "Metals",
    "APLAPOLLO-EQ": "Metals", "JSL-EQ": "Metals", "WELCORP-EQ": "Metals", 
    "SHYAMMETL-EQ": "Metals", "RATNAMANI-EQ": "Metals",
    "GRASIM-EQ": "Construction Mat", "ULTRACEMCO-EQ": "Construction Mat", "SHREECEM-EQ": "Construction Mat",
    "AMBUJACEM-EQ": "Construction Mat", "ACC-EQ": "Construction Mat", "DALBHARAT-EQ": "Construction Mat",
    "RAMCOCEM-EQ": "Construction Mat", "JKCEMENT-EQ": "Construction Mat", "COROMANDEL-EQ": "Construction Mat",
    "INDIACEM-EQ": "Construction Mat", "JKLAKSHMI-EQ": "Construction Mat", "BIRLACORPN-EQ": "Construction Mat",
    "STARCEMENT-EQ": "Construction Mat", "NUVOCO-EQ": "Construction Mat",
    "BHARTIARTL-EQ": "Telecom", "IDEA-EQ": "Telecom", "TATACOMM-EQ": "Telecom",
    "INDUSTOWER-EQ": "Telecom", "ROUTE-EQ": "Telecom", "TEJASNET-EQ": "Telecom",
    "HFCL-EQ": "Telecom", "RAILTEL-EQ": "Telecom", "ITI-EQ": "Telecom",
    "NTPC-EQ": "Power", "POWERGRID-EQ": "Power", "TATAPOWER-EQ": "Power",
    "ADANIGREEN-EQ": "Power", "ADANIPOWER-EQ": "Power", "JSWENERGY-EQ": "Power",
    "NHPC-EQ": "Power", "TORNTPOWER-EQ": "Power", "CESC-EQ": "Power",
    "SJVN-EQ": "Power", "NLCINDIA-EQ": "Power", "IEX-EQ": "Power", "PTC-EQ": "Power",
    "SIEMENS-EQ": "Capital Goods", "ABB-EQ": "Capital Goods", "HAL-EQ": "Capital Goods",
    "BEL-EQ": "Capital Goods", "CUMMINSIND-EQ": "Capital Goods", "CGPOWER-EQ": "Capital Goods",
    "POLYCAB-EQ": "Capital Goods", "HAVELLS-EQ": "Capital Goods", "SUZLON-EQ": "Capital Goods",
    "BDL-EQ": "Capital Goods", "MAZDOCK-EQ": "Capital Goods", "COCHINSHIP-EQ": "Capital Goods",
    "BHEL-EQ": "Capital Goods", "THERMAX-EQ": "Capital Goods", "KEI-EQ": "Capital Goods",
    "PIDILITIND-EQ": "Chemicals", "SRF-EQ": "Chemicals", "TATACHEM-EQ": "Chemicals",
    "DEEPAKNTR-EQ": "Chemicals", "AARTIIND-EQ": "Chemicals", "ATUL-EQ": "Chemicals",
    "NAVINFLUOR-EQ": "Chemicals", "PIIND-EQ": "Chemicals", "UPL-EQ": "Chemicals",
    "LINDEINDIA-EQ": "Chemicals", "SOLARINDS-EQ": "Chemicals", "BALAMINES-EQ": "Chemicals",
    "ALKYLAMINE-EQ": "Chemicals", "CLEAN-EQ": "Chemicals", "SUMICHEM-EQ": "Chemicals",
    "TRENT-EQ": "Consumer Retail", "ZOMATO-EQ": "Consumer Retail", "NYKAA-EQ": "Consumer Retail",
    "DMART-EQ": "Consumer Retail", "TITAN-EQ": "Consumer Retail", "JUBLFOOD-EQ": "Consumer Retail",
    "IRCTC-EQ": "Consumer Retail", "PAGEIND-EQ": "Consumer Retail", "BATAINDIA-EQ": "Consumer Retail",
    "DEVYANI-EQ": "Consumer Retail", "WESTLIFE-EQ": "Consumer Retail", "RELAXO-EQ": "Consumer Retail",
    "METROBRAND-EQ": "Consumer Retail", "KALYANKJIL-EQ": "Consumer Retail", "SAPPHIRE-EQ": "Consumer Retail",
    "DLF-EQ": "Real Estate", "LODHA-EQ": "Real Estate", "GODREJPROP-EQ": "Real Estate",
    "OBEROIRLTY-EQ": "Real Estate", "PRESTIGE-EQ": "Real Estate", "PHOENIXLTD-EQ": "Real Estate",
    "BRIGADE-EQ": "Real Estate", "SOBHA-EQ": "Real Estate", "MAHLIFE-EQ": "Real Estate",
    "PURVA-EQ": "Real Estate", "SUNTECK-EQ": "Real Estate",
    "LT-EQ": "Infrastructure", "GMRINFRA-EQ": "Infrastructure", "IRB-EQ": "Infrastructure",
    "RVNL-EQ": "Infrastructure", "IRCON-EQ": "Infrastructure", "KEC-EQ": "Infrastructure",
    "NBCC-EQ": "Infrastructure", "NCC-EQ": "Infrastructure", "RITES-EQ": "Infrastructure",
    "ENGINERSIN-EQ": "Infrastructure", "PNCINFRA-EQ": "Infrastructure", "GRINFRA-EQ": "Infrastructure"
}

# Dynamically load the matched NSE/BSE tickers
VCP_STOCKS = get_vcp_stocks("VCP_Stocks_Yahoo.csv")

# ==========================================
# 5. CACHED DATA FETCHERS
# ==========================================
@st.cache_data(ttl=86400)
def get_market_caps():
    caps = {}
    def fetch_cap(symbol):
        yf_symbol = symbol.replace("-EQ", ".NS")
        try:
            return symbol, yf.Ticker(yf_symbol).info.get('marketCap', 1)
        except Exception:
            return symbol, 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(fetch_cap, sym) for sym in STOCKS.keys()]
        for future in concurrent.futures.as_completed(futures):
            sym, cap = future.result()
            caps[sym] = cap
            
    return caps

@st.cache_data(ttl=86400)
def get_token_map():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    try:
        response = requests.get(url).json()
        token_map = {item["symbol"]: item["token"] for item in response if item.get("exch_seg") == "NSE" and item.get("symbol") in STOCKS}
        token_map["NIFTY"] = "99926000"
        return token_map
    except Exception:
        return {}

def get_smart_api_session():
    smartApi = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    session = smartApi.generateSession(CLIENT_ID, PIN, totp)
    if session.get('status') == False:
        st.error(f"Login Failed: {session.get('message')}")
        return None
    return smartApi

@st.cache_data(ttl=300)
def fetch_and_calculate():
    smartApi = get_smart_api_session()
    if not smartApi:
        return pd.DataFrame()

    token_map = get_token_map()
    mcaps = get_market_caps()
    
    to_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d %H:%M")

    nifty_params = {
        "exchange": "NSE",
        "symboltoken": token_map.get("NIFTY", "99926000"),
        "interval": "ONE_DAY",
        "fromdate": from_date,
        "todate": to_date
    }
    nifty_response = smartApi.getCandleData(nifty_params)
    if not nifty_response.get("status") or not nifty_response.get("data"):
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
            df["SMA_200"] = df["close"].rolling(window=200).mean()

            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
            rs = gain / loss
            df["RSI_14"] = 100 - (100 / (1 + rs))

            aligned_nifty = nifty_close.reindex(df.index, method="ffill")
            for period in [21, 55, 100]:
                df[f"RS_{period}"] = df["close"].pct_change(periods=period) - aligned_nifty.pct_change(periods=period)

            df["AvgVolume"] = df["volume"].rolling(window=20).mean()

            latest = df.iloc[-1]
            current_price = latest["close"]
            prev_close = df["close"].iloc[-2]
            
            results.append({
                "Ticker": symbol.replace("-EQ", ""),
                "Sector": sector,
                "MarketCap": mcaps.get(symbol, 1),
                "CurrentPrice": current_price,
                "ChangeRs": current_price - prev_close,
                "ChangePct": ((current_price - prev_close) / prev_close) * 100,
                "RSI_14": latest.get("RSI_14", 0),
                "RS_21": latest.get("RS_21", 0),
                "RS_55": latest.get("RS_55", 0),
                "RS_100": latest.get("RS_100", 0),
                "SMA_20": latest.get("SMA_20", 0),
                "SMA_50": latest.get("SMA_50", 0),
                "SMA_100": latest.get("SMA_100", 0),
                "SMA_200": latest.get("SMA_200", 0),
                "Volume": latest.get("volume", 0),
                "AvgVolume": latest.get("AvgVolume", 0)
            })
        except Exception:
            continue

    return pd.DataFrame(results)

@st.cache_data(ttl=86400)
def fetch_and_run_vcp(vcp_stocks_list):
    if not vcp_stocks_list:
        return []

    # 1. First fetch Nifty 50 close index as benchmark
    try:
        nifty_data = yf.download("^NSEI", period="1y", interval="1d", progress=False)
        nifty_col = "Adj Close" if "Adj Close" in nifty_data else "Close"
        nifty_close = nifty_data[nifty_col].ffill()
        if isinstance(nifty_close, pd.DataFrame):
            nifty_close = nifty_close.iloc[:, 0]
    except Exception:
        nifty_close = pd.Series(1.0)

    vcp_results = []
    
    # 2. Process stocks in safer batches of 100 
    chunk_size = 100
    for i in range(0, len(vcp_stocks_list), chunk_size):
        chunk = vcp_stocks_list[i:i + chunk_size]
        
        try:
            vcp_data = yf.download(chunk, period="1y", interval="1d", threads=True, progress=False)
            if vcp_data.empty:
                continue

            # Safely handle Yahoo's shifting MultiIndex formatting
            is_multi = isinstance(vcp_data.columns, pd.MultiIndex)
            close_col = "Adj Close" if ("Adj Close" in vcp_data.columns.get_level_values(0) if is_multi else "Adj Close" in vcp_data) else "Close"
            
            for yf_symbol in chunk:
                try:
                    if is_multi:
                        if yf_symbol not in vcp_data[close_col]:
                            continue
                        close_series = vcp_data[close_col][yf_symbol]
                        volume_series = vcp_data["Volume"][yf_symbol] if "Volume" in vcp_data else close_series
                        high_series = vcp_data["High"][yf_symbol] if "High" in vcp_data else close_series
                        low_series = vcp_data["Low"][yf_symbol] if "Low" in vcp_data else close_series
                    else:
                        # Fallback for single-ticker chunks
                        close_series = vcp_data[close_col]
                        volume_series = vcp_data.get("Volume", close_series)
                        high_series = vcp_data.get("High", close_series)
                        low_series = vcp_data.get("Low", close_series)

                    df = pd.DataFrame({
                        "close": close_series,
                        "volume": volume_series,
                        "high": high_series,
                        "low": low_series
                    }).dropna()

                    if df.empty or len(df) < 200:
                        continue

                    res = analyze_vcp(df, nifty_close)
                    if res:
                        res["Ticker"] = yf_symbol.replace(".NS", "").replace(".BO", "")
                        vcp_results.append(res)
                except Exception:
                    continue
        except Exception:
            continue

    return vcp_results


# ==========================================
# 6. UI RENDERING & NAVIGATION
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    selected_tab = st.radio(
        "Navigation",
        ["📊 Market Breadth", "🚀 VCP Screener"],
        horizontal=True,
        label_visibility="collapsed"
    )

st.divider()

# ==========================================
# TAB 1: MARKET BREADTH DASHBOARD
# ==========================================
if selected_tab == "📊 Market Breadth":
    
    st.sidebar.header("Strategy Parameters")
    rs_period = st.sidebar.selectbox("Relative Strength Period", ["21 Days", "55 Days", "100 Days"], index=1)
    rsi_thresh = st.sidebar.slider("Minimum RSI", 30, 80, 50)
    display_mode = st.sidebar.radio("Weighting Mode", ["Number of Stocks", "% of Sector Market Cap"])

    st.title("Indian Market Sector Dashboard")
    st.markdown("Advanced breadth tracking with dynamic Relative Strength and volume profiling.")

    # --- SESSION STATE IMPLEMENTATION ---
    if "market_data" not in st.session_state:
        with st.spinner("Fetching live market data (this may take a minute)..."):
            st.session_state.market_data = fetch_and_calculate()
            
    # Safely load the data from memory so sliders update instantly
    master_df = st.session_state.market_data.copy() if not st.session_state.market_data.empty else pd.DataFrame()

    if not master_df.empty:
        rs_col = {"21 Days": "RS_21", "55 Days": "RS_55", "100 Days": "RS_100"}[rs_period]

        master_df["RS_Pass"] = master_df[rs_col].apply(lambda x: 1 if pd.notna(x) and x > 0 else 0)
        master_df["RSI_Pass"] = master_df["RSI_14"].apply(lambda x: 1 if pd.notna(x) and x > rsi_thresh else 0)
        master_df["SMA20_Pass"] = master_df.apply(lambda row: 1 if pd.notna(row["SMA_20"]) and row["CurrentPrice"] > row["SMA_20"] else 0, axis=1)
        master_df["SMA50_Pass"] = master_df.apply(lambda row: 1 if pd.notna(row["SMA_50"]) and row["CurrentPrice"] > row["SMA_50"] else 0, axis=1)
        master_df["SMA100_Pass"] = master_df.apply(lambda row: 1 if pd.notna(row["SMA_100"]) and row["CurrentPrice"] > row["SMA_100"] else 0, axis=1)
        master_df["SMA200_Pass"] = master_df.apply(lambda row: 1 if pd.notna(row["SMA_200"]) and row["CurrentPrice"] > row["SMA_200"] else 0, axis=1)
        master_df["VolumeSurge"] = master_df.apply(lambda row: 1 if row["Volume"] > (1.5 * row["AvgVolume"]) else 0, axis=1)

        sectors = master_df["Sector"].unique()
        
        dashboard_data_table = []
        dashboard_data_chart = []

        for sector in sectors:
            sec_df = master_df[master_df["Sector"] == sector]
            total_mc = sec_df["MarketCap"].sum()
            total_stocks = len(sec_df)

            def get_table_val(flag):
                if display_mode == "Number of Stocks":
                    return f"{sec_df[flag].sum()} / {total_stocks}"
                else:
                    passed_mc = sec_df[sec_df[flag] == 1]["MarketCap"].sum()
                    return f"{(passed_mc / total_mc * 100):.1f}%" if total_mc > 0 else "0.0%"

            def get_chart_val(flag):
                if display_mode == "Number of Stocks":
                    return (sec_df[flag].sum() / total_stocks * 100) if total_stocks > 0 else 0
                else:
                    passed_mc = sec_df[sec_df[flag] == 1]["MarketCap"].sum()
                    return (passed_mc / total_mc * 100) if total_mc > 0 else 0

            dashboard_data_table.append({
                "Sectors": sector,
                f"RS > 0 ({rs_period})": get_table_val("RS_Pass"),
                f"RSI > {rsi_thresh}": get_table_val("RSI_Pass"),
                "SMA 20": get_table_val("SMA20_Pass"),
                "SMA 50": get_table_val("SMA50_Pass"),
                "SMA 100": get_table_val("SMA100_Pass"),
                "SMA 200": get_table_val("SMA200_Pass")
            })
            
            dashboard_data_chart.append({
                "Sectors": sector,
                f"RS > 0 ({rs_period})": get_chart_val("RS_Pass")
            })

        final_table_df = pd.DataFrame(dashboard_data_table)
        final_chart_df = pd.DataFrame(dashboard_data_chart)

        st.subheader(f"Sector Rotation ({display_mode})")
        fig = px.bar(final_chart_df, x="Sectors", y=f"RS > 0 ({rs_period})", color="Sectors", text_auto='.1f', title=f"Percentage of Sector Outperforming Nifty 50 ({rs_period})")
        st.plotly_chart(fig, width="stretch")

        st.subheader("Market Breadth Data")
        st.dataframe(final_table_df, width="stretch", hide_index=True)
        
        # --- EXPLICIT REFRESH BUTTON ---
        if st.button("Refresh Live Data"):
            fetch_and_calculate.clear()
            if "market_data" in st.session_state:
                del st.session_state.market_data
            st.rerun()

        st.markdown("---")
        
        st.subheader("Screener & Export")
        
        sel_col1, sel_col2, sel_col3 = st.columns(3)
        with sel_col1:
            selected_sector = st.selectbox("1. Select a Sector:", final_table_df["Sectors"].tolist())
        with sel_col2:
            selected_indicator = st.selectbox(
                "2. Select an Indicator:", 
                ["Relative Strength", "RSI Threshold", "SMA 20", "SMA 50", "SMA 100", "SMA 200", "Volume Surge"]
            )
        with sel_col3:
            sort_by = st.selectbox("3. Sort Results By:", ["Highest % Gain", "Highest RSI", "Highest RS"])
        
        flag_map = {
            "Relative Strength": "RS_Pass", 
            "RSI Threshold": "RSI_Pass", 
            "SMA 20": "SMA20_Pass", 
            "SMA 50": "SMA50_Pass", 
            "SMA 100": "SMA100_Pass", 
            "SMA 200": "SMA200_Pass", 
            "Volume Surge": "VolumeSurge"
        }
        
        winning_stocks = master_df[(master_df["Sector"] == selected_sector) & (master_df[flag_map[selected_indicator]] == 1)].copy()

        if sort_by == "Highest % Gain":
            winning_stocks = winning_stocks.sort_values(by="ChangePct", ascending=False)
        elif sort_by == "Highest RSI":
            winning_stocks = winning_stocks.sort_values(by="RSI_14", ascending=False)
        else:
            winning_stocks = winning_stocks.sort_values(by=rs_col, ascending=False)

        if not winning_stocks.empty:
            csv = winning_stocks[["Ticker", "CurrentPrice", "ChangePct", "RSI_14", rs_col, "VolumeSurge"]].to_csv(index=False).encode('utf-8')
            st.download_button(label="Download Data (CSV)", data=csv, file_name=f"{selected_sector}_screener.csv", mime="text/csv")
            
            st.write("")
            cols = st.columns(3)
            for i, (_, stock) in enumerate(winning_stocks.iterrows()):
                col = cols[i % 3] 
                color = "green" if stock["ChangeRs"] >= 0 else "red"
                sign = "+" if stock["ChangeRs"] >= 0 else ""
                surge_text = " | <strong>Volume Breakout</strong>" if stock["VolumeSurge"] == 1 else ""
                
                with col:
                    st.markdown(
                        f"""<div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 24px; border-radius: 18px; margin-bottom: 16px;">
<span style="font-family: -apple-system, sans-serif; font-weight: 600; font-size: 17px; color: #1d1d1f;">{stock['Ticker']}</span>
<span style="color: #0066cc; font-size: 14px; font-weight: 400;">{surge_text}</span><br>
<div style="margin-top: 12px; font-size: 17px; color: #1d1d1f; font-weight: 400; line-height: 1.47;">
₹{stock['CurrentPrice']:.2f} <br>
<span style="color: {color}; font-weight: 600;">{sign}₹{stock['ChangeRs']:.2f} ({sign}{stock['ChangePct']:.2f}%)</span><br>
</div>
<div style="margin-top: 17px; font-size: 14px; color: #7a7a7a; font-weight: 400;">
RSI: {stock['RSI_14']:.1f} &nbsp;|&nbsp; RS: {stock[rs_col]*100:.1f}%
</div>
</div>""", 
                        unsafe_allow_html=True
                    )
        else:
            st.write("No stocks meet this criteria right now.")
    else:
        st.error("Failed to load dashboard data.")

# ==========================================
# TAB 2: VCP SCREENER
# ==========================================
elif selected_tab == "🚀 VCP Screener":
    
    st.markdown("""
        <h2 style='font-family: -apple-system, sans-serif; font-weight: 600; color: #1d1d1f; letter-spacing: -0.374px;'>
            Minervini Volatility Contraction Pattern (VCP) Screener
        </h2>
        <p style='font-size: 17px; color: #7a7a7a; margin-bottom: 24px;'>
            Identifies Stage-2 uptrend stocks experiencing extreme volatility compression and volume dry-up (VDU) prior to explosive breakouts.
        </p>
    """, unsafe_allow_html=True)

    # --- EXPLICIT REFRESH BUTTON ---
    if st.button("🔄 Refresh VCP Scan Data"):
        fetch_and_run_vcp.clear()
        if "vcp_results" in st.session_state:
            del st.session_state.vcp_results
        st.rerun()

    st.sidebar.markdown("### VCP Parameters")
    min_vcp_score = st.sidebar.slider("Minimum VCP Score", min_value=50, max_value=90, value=60, step=5)
    max_tightness = st.sidebar.slider("Max Pivot Tightness (%)", min_value=2.0, max_value=10.0, value=6.0, step=0.5)

    # --- SESSION STATE IMPLEMENTATION ---
    if "vcp_results" not in st.session_state:
        with st.spinner(f"Analyzing universe of {len(VCP_STOCKS)} stocks for Stage 2 VCP setups..."):
            st.session_state.vcp_results = fetch_and_run_vcp(VCP_STOCKS)
            
    # Safely load the data from memory so sliders update instantly
    raw_results = st.session_state.vcp_results

    if not raw_results:
        st.warning("No data returned or calculation pending. Click 'Refresh VCP Scan Data' to run the scan. (Note: Also check your CSV ticker symbols are standard NSE tickers).")
    else:
        filtered_results = [
            r for r in raw_results 
            if r["VCPScore"] >= min_vcp_score and r["PivotTightnessPct"] <= max_tightness
        ]

        if not filtered_results:
            st.warning(f"No stocks currently meet a VCP Score ≥ {min_vcp_score} and Tightness ≤ {max_tightness}%.")
        else:
            vcp_df = pd.DataFrame(filtered_results).sort_values(by="VCPScore", ascending=False)
            
            st.markdown(f"**Found {len(vcp_df)} Institutional VCP Setups out of {len(VCP_STOCKS)} stocks**")
            
            cols = st.columns(3)
            for idx, row in vcp_df.reset_index(drop=True).iterrows():
                col = cols[idx % 3]
                
                vdu_badge = '<span style="background-color: #0066cc; color: white; font-size: 11px; padding: 3px 8px; border-radius: 9999px; font-weight: 600;">VDU ACTIVE</span>' if row['IsVDU'] else ''
                
                with col:
                    st.markdown(
                        f"""<div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 24px; border-radius: 18px; margin-bottom: 20px;">
<div style="display: flex; justify-content: space-between; align-items: center;">
    <span style="font-family: -apple-system, sans-serif; font-weight: 600; font-size: 21px; color: #1d1d1f;">{row['Ticker']}</span>
    {vdu_badge}
</div>

<div style="margin-top: 16px; font-size: 28px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.28px;">
    ₹{row['LatestPrice']:.2f}
</div>

<div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; font-size: 14px; color: #1d1d1f; line-height: 1.6;">
    <b>VCP Rating Score:</b> <span style="color: #0066cc; font-weight: 600;">{row['VCPScore']}/100</span><br>
    <b>Pivot Tightness:</b> {row['PivotTightnessPct']:.1f}% (10-Day Range)<br>
    <b>Base Depth:</b> {row['BaseDepthPct']:.1f}%<br>
    <b>Dist. from 52W High:</b> {row['DistFrom52wHigh']:.1f}%<br>
    <b>55D Rel. Strength:</b> +{row['RS55']:.1f}%
</div>
</div>""",
                        unsafe_allow_html=True
                    )