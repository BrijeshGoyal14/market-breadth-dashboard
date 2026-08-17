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
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

st.set_page_config(layout="wide", page_title="Indian Sector Dashboard")

API_KEY = os.getenv("API_KEY")
CLIENT_ID = os.getenv("CLIENT_ID")
PIN = os.getenv("PIN")
TOTP_SECRET = os.getenv("TOTP_SECRET")

def load_css(file_name):
    file_path = os.path.join(os.path.dirname(__file__), file_name)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

load_css("design.css")

def get_vcp_stocks(file_name="VCP_Stocks_Yahoo.csv"):
    file_path = os.path.join(os.path.dirname(__file__), file_name)
    vcp_list = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f.readlines():
                cleaned = line.strip().replace('"', '').replace(',', '')
                if cleaned:
                    vcp_list.append(cleaned)
    return vcp_list

def analyze_vcp(df, nifty_close):
    if len(df) < 200: return None
    close, volume = df["close"], df["volume"]
    latest_price = close.iloc[-1]
    
    c_50 = close.rolling(50).mean().iloc[-1]
    c_150 = close.rolling(150).mean().iloc[-1]
    c_200 = close.rolling(200).mean().iloc[-1]
    c_200_20d_ago = close.rolling(200).mean().iloc[-20]
    
    high_52w = close.iloc[-252:].max() if len(close) >= 252 else close.max()
    low_52w = close.iloc[-252:].min() if len(close) >= 252 else close.min()
    
    if not (latest_price > c_150 and latest_price > c_200 and c_150 > c_200 and 
            c_200 > c_200_20d_ago and c_50 > c_150 and c_50 > c_200 and 
            latest_price > c_50 and latest_price >= (1.25 * low_52w) and 
            latest_price >= (0.75 * high_52w)):
        return None

    aligned_nifty = nifty_close.reindex(df.index, method="ffill")
    stk_ret = (latest_price - close.iloc[-56]) / close.iloc[-56] if len(close) >= 56 else 0
    nft_ret = (aligned_nifty.iloc[-1] - aligned_nifty.iloc[-56]) / aligned_nifty.iloc[-56] if len(aligned_nifty) >= 56 else 0
    rs_55 = stk_ret - nft_ret
    if rs_55 <= 0: return None

    base_high, base_low = close.iloc[-60:].max(), close.iloc[-60:].min()
    recent_high, recent_low = close.iloc[-10:].max(), close.iloc[-10:].min()
    
    base_depth_pct = ((base_high - base_low) / base_high) * 100
    pivot_tightness_pct = ((recent_high - recent_low) / recent_high) * 100
    contraction_ratio = (recent_high - recent_low) / (base_high - base_low + 1e-5)
    
    tr = np.maximum(df.get("high", close) - df.get("low", close), np.abs(df.get("high", close) - close.shift(1)))
    atr_ratio = tr.rolling(10).mean().iloc[-1] / (tr.rolling(50).mean().iloc[-1] + 1e-5)

    vdu_ratio = volume.rolling(5).mean().iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-5)
    is_vdu = vdu_ratio < 0.65  
    dist_from_52w_high = ((high_52w - latest_price) / high_52w) * 100
    
    vcp_score = 100
    if pivot_tightness_pct > 6.0: vcp_score -= 20
    if contraction_ratio > 0.40: vcp_score -= 20
    if not is_vdu: vcp_score -= 25
    if dist_from_52w_high > 10.0: vcp_score -= 15
    if atr_ratio > 0.70: vcp_score -= 20

    return {
        "LatestPrice": latest_price, "DistFrom52wHigh": dist_from_52w_high,
        "BaseDepthPct": base_depth_pct, "PivotTightnessPct": pivot_tightness_pct,
        "ContractionRatio": contraction_ratio, "VDURatio": vdu_ratio, "IsVDU": is_vdu,
        "ATRRatio": atr_ratio, "RS55": rs_55 * 100, "VCPScore": max(0, vcp_score)
    }

def analyze_pocket_pivot(df):
    if len(df) < 15: return False
    latest_close = df["close"].iloc[-1]
    prev_close = df["close"].iloc[-2]
    if latest_close <= prev_close: return False
    
    latest_volume = df["volume"].iloc[-1]
    max_down_volume = 0
    for i in range(-11, -1):
        day_close = df["close"].iloc[i]
        day_prev = df["close"].iloc[i-1]
        day_vol = df["volume"].iloc[i]
        if day_close < day_prev:
            if day_vol > max_down_volume: max_down_volume = day_vol
                
    sma_50 = df["close"].rolling(50).mean().iloc[-1]
    is_above_sma = latest_close > sma_50 if pd.notna(sma_50) else True
    return latest_volume > max_down_volume and is_above_sma

def analyze_avwap_squeeze(df):
    if len(df) < 60: return None
    lookback_window = min(120, len(df))
    anchor_idx = df["low"].iloc[-lookback_window:].idxmin()
    
    df_anchored = df.loc[anchor_idx:].copy()
    if len(df_anchored) < 10: return None
    
    typical_price = (df_anchored.get("high", df_anchored["close"]) + df_anchored.get("low", df_anchored["close"]) + df_anchored["close"]) / 3
    pv = typical_price * df_anchored["volume"]
    avwap = pv.cumsum() / df_anchored["volume"].cumsum()
    
    df_anchored["avwap"] = avwap
    latest_price = df_anchored["close"].iloc[-1]
    latest_avwap = df_anchored["avwap"].iloc[-1]
    
    dist_from_avwap_pct = abs((latest_price - latest_avwap) / latest_avwap) * 100
    recent_high = df_anchored["close"].iloc[-5:].max()
    recent_low = df_anchored["close"].iloc[-5:].min()
    tightness_pct = ((recent_high - recent_low) / latest_avwap) * 100
    
    sma_50 = df["close"].rolling(50).mean().iloc[-1]
    is_uptrend = latest_price > sma_50 if pd.notna(sma_50) else True

    if dist_from_avwap_pct <= 2.5 and tightness_pct <= 5.0 and is_uptrend:
        return {
            "LatestPrice": latest_price,
            "AVWAP": latest_avwap,
            "DistPct": dist_from_avwap_pct,
            "TightnessPct": tightness_pct
        }
    return None

STOCKS = {
    "HDFCBANK-EQ": "Financials", "ICICIBANK-EQ": "Financials", "SBIN-EQ": "Financials",
    "AXISBANK-EQ": "Financials", "KOTAKBANK-EQ": "Financials", "BAJFINANCE-EQ": "Financials",
    "CHOLAFIN-EQ": "Financials", "MUTHOOTFIN-EQ": "Financials", "PFC-EQ": "Financials",
    "RECLTD-EQ": "Financials", "HDFCLIFE-EQ": "Financials", "SBILIFE-EQ": "Financials",
    "BAJAJFINSV-EQ": "Financials", "INDUSINDBK-EQ": "Financials", "PNB-EQ": "Financials",
    "BANKBARODA-EQ": "Financials", "IOB-EQ": "Financials", "UNIONBANK-EQ": "Financials",
    "CANBK-EQ": "Financials", "IDFCFIRSTB-EQ": "Financials", "FEDERALBNK-EQ": "Financials",
    "TCS-EQ": "IT", "INFY-EQ": "IT", "WIPRO-EQ": "IT", "HCLTECH-EQ": "IT", "TECHM-EQ": "IT",
    "PERSISTENT-EQ": "IT", "COFORGE-EQ": "IT", "MPHASIS-EQ": "IT",
    "KPITTECH-EQ": "IT", "TATAELXSI-EQ": "IT", "OFSS-EQ": "IT", "CYIENT-EQ": "IT",
    "BSOFT-EQ": "IT", "SONATSOFTW-EQ": "IT", "INTELLECT-EQ": "IT",
    "RELIANCE-EQ": "Oil & Gas", "ONGC-EQ": "Oil & Gas", "COALINDIA-EQ": "Oil & Gas",
    "BPCL-EQ": "Oil & Gas", "IOC-EQ": "Oil & Gas", "HINDPETRO-EQ": "Oil & Gas",
    "GAIL-EQ": "Oil & Gas", "IGL-EQ": "Oil & Gas", "MGL-EQ": "Oil & Gas",
    "PETRONET-EQ": "Oil & Gas", "GUJENERGY-EQ": "Oil & Gas", "OIL-EQ": "Oil & Gas",
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
    "ENGINERSIN-EQ": "Infrastructure", "PNCINFRA-EQ": "Infrastructure", "GRINFRA-EQ": "Infrastructure",
    "GUJENERGY-EQ": "Oil & Gas"
}

VCP_STOCKS = get_vcp_stocks()

@st.cache_data(ttl=86400)
def get_market_caps():
    caps = {}
    def fetch_cap(symbol):
        try:
            return symbol, yf.Ticker(symbol.replace("-EQ", ".NS")).info.get('marketCap', 1)
        except:
            return symbol, 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        for future in concurrent.futures.as_completed([executor.submit(fetch_cap, sym) for sym in STOCKS.keys()]):
            sym, cap = future.result()
            caps[sym] = cap
    return caps

@st.cache_data(ttl=86400)
def get_token_map():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code != 200: return {}
        angel_nse_map = {item.get("symbol", ""): item.get("token", "") for item in res.json() if item.get("exch_seg") == "NSE"}
        aliases = {
            "HINDUNILVR-EQ": ["HINDUNILVR-EQ", "HUL-EQ"],
            "LODHA-EQ": ["LODHA-EQ", "MACROTECH-EQ"],
            "MCDOWELL-N-EQ": ["MCDOWELL-N-EQ", "UNITDSPR-EQ"],
            "NYKAA-EQ": ["NYKAA-EQ", "FSN-EQ"],
            "ZYDUSLIFE-EQ": ["ZYDUSLIFE-EQ", "CADILAHC-EQ"],
            "LTIMINDTREE-EQ": ["LTIM-EQ", "LTIM"],
            "GUJENERGY-EQ": ["GUJGASLTD-EQ", "GUJARATGAS-EQ", "GUJGAS-EQ", "GUJGASLTD"],
            "AEGISCHEM-EQ": ["AEGISLOG-EQ", "AEGISCHEM"],
            "ZOMATO-EQ": ["ETERNAL-EQ", "ETERNAL"],
            "GMRINFRA-EQ": ["GMRAIRPORT-EQ", "GMRINFRA"]
        }
        token_map = {"NIFTY": "99926000"}
        for stock_key in STOCKS.keys():
            base_sym = stock_key.replace("-EQ", "") 
            if stock_key in angel_nse_map: token_map[stock_key] = angel_nse_map[stock_key]
            elif base_sym in angel_nse_map: token_map[stock_key] = angel_nse_map[base_sym]
            elif stock_key in aliases:
                for alt_sym in aliases[stock_key]:
                    if alt_sym in angel_nse_map: token_map[stock_key] = angel_nse_map[alt_sym]; break
        return token_map
    except: return {}

def get_smart_api_session():
    if not TOTP_SECRET: return None
    smartApi = SmartConnect(api_key=API_KEY)
    session = smartApi.generateSession(CLIENT_ID, PIN, pyotp.TOTP(TOTP_SECRET).now())
    return smartApi if session.get('status') else None

def fetch_with_retry_sequential(smartApi, params, max_retries=3):
    for _ in range(max_retries):
        try:
            res = smartApi.getCandleData(params)
            if res and res.get("status") and res.get("data"): return res
            time.sleep(1.0)
        except: time.sleep(2.0)
    return None

@st.cache_data(ttl=300)
def fetch_and_calculate():
    smartApi = get_smart_api_session()
    token_map = get_token_map()
    if not smartApi or not token_map: return {"data": pd.DataFrame(), "missing": []}

    mcaps = get_market_caps()
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    to_date = datetime.now(ist_offset).strftime("%Y-%m-%d %H:%M")
    from_date = (datetime.now(ist_offset) - timedelta(days=365)).strftime("%Y-%m-%d %H:%M")

    nifty_res = fetch_with_retry_sequential(smartApi, {"exchange": "NSE", "symboltoken": token_map["NIFTY"], "interval": "ONE_DAY", "fromdate": from_date, "todate": to_date})
    if not nifty_res: return {"data": pd.DataFrame(), "missing": []}

    nifty_df = pd.DataFrame(nifty_res["data"], columns=["time", "open", "high", "low", "close", "volume"])
    nifty_df['time'] = pd.to_datetime(nifty_df['time'], utc=True).dt.tz_convert(None).dt.normalize()
    nifty_df.set_index('time', inplace=True)
    nifty_close = nifty_df["close"].ffill()

    results, missing_stocks = [], []
    progress_bar = st.progress(0, text="Fetching Market Breadth Data from Angel One...")
    total_stocks = len(STOCKS)
    
    for i, (symbol, sector) in enumerate(STOCKS.items()):
        progress_bar.progress((i + 1) / total_stocks, text=f"Downloading: {i+1}/{total_stocks} stocks ({symbol})")
        token = token_map.get(symbol)
        if not token: missing_stocks.append(f"{symbol} (Token Missing)"); continue

        time.sleep(0.35) 
        res = fetch_with_retry_sequential(smartApi, {"exchange": "NSE", "symboltoken": token, "interval": "ONE_DAY", "fromdate": from_date, "todate": to_date})
        if not res: missing_stocks.append(f"{symbol} (API Rejected)"); continue

        df = pd.DataFrame(res["data"], columns=["time", "open", "high", "low", "close", "volume"])
        df['time'] = pd.to_datetime(df['time'], utc=True).dt.tz_convert(None).dt.normalize()
        df.set_index('time', inplace=True)
        df["close"] = df["close"].ffill()
        if len(df) < 2: missing_stocks.append(f"{symbol} (Not enough data)"); continue

        latest, prev_close = df.iloc[-1], df["close"].iloc[-2]
        current_price = latest["close"]
        delta = df["close"].diff()
        rs = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean() / (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rsi_14 = 100 - (100 / (1 + rs.iloc[-1]))
        
        aligned_nifty = nifty_close.reindex(df.index, method="ffill")
        rs_vals = {p: (df["close"].pct_change(periods=p).iloc[-1] - aligned_nifty.pct_change(periods=p).iloc[-1]) for p in [21, 55, 100]}

        results.append({
            "Ticker": symbol.replace("-EQ", ""), "Sector": sector, "MarketCap": mcaps.get(symbol, 1),
            "CurrentPrice": current_price, "ChangeRs": current_price - prev_close, "ChangePct": ((current_price - prev_close) / prev_close) * 100,
            "RSI_14": rsi_14, "RS_21": rs_vals[21], "RS_55": rs_vals[55], "RS_100": rs_vals[100],
            "SMA_20": df["close"].rolling(20).mean().iloc[-1], "SMA_50": df["close"].rolling(50).mean().iloc[-1],
            "SMA_100": df["close"].rolling(100).mean().iloc[-1], "SMA_200": df["close"].rolling(200).mean().iloc[-1],
            "Volume": latest["volume"], "AvgVolume": df["volume"].rolling(20).mean().iloc[-1]
        })

    progress_bar.empty()
    return {"data": pd.DataFrame(results), "missing": missing_stocks}

@st.cache_data(ttl=86400)
def fetch_and_run_vcp(vcp_stocks_list):
    if not vcp_stocks_list: return {"error": "CSV list is empty."}
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        nifty_data = yf.download("^NSEI", period="1y", interval="1d", progress=False, session=session)
        nifty_col = "Adj Close" if "Adj Close" in nifty_data else "Close"
        nifty_close = nifty_data[nifty_col].ffill()
        if isinstance(nifty_close, pd.DataFrame): nifty_close = nifty_close.iloc[:, 0]
    except: return {"error": "Nifty fetch crashed."}

    vcp_results = []
    progress_bar = st.progress(0, text="Starting VCP Scan...")
    chunk_size = 100
    total_chunks = (len(vcp_stocks_list) // chunk_size) + 1
    
    for i in range(0, len(vcp_stocks_list), chunk_size):
        chunk_num = (i // chunk_size) + 1
        progress_bar.progress(chunk_num / total_chunks, text=f"VCP Scan: Processing batch {chunk_num}/{total_chunks}...")
        chunk = vcp_stocks_list[i:i + chunk_size]
        try:
            vcp_data = yf.download(chunk, period="1y", interval="1d", threads=True, progress=False, session=session)
            if vcp_data.empty: continue
            is_multi = isinstance(vcp_data.columns, pd.MultiIndex)
            close_col = "Adj Close" if ("Adj Close" in vcp_data.columns.get_level_values(0) if is_multi else "Adj Close" in vcp_data) else "Close"
            for sym in chunk:
                try:
                    if is_multi:
                        if sym not in vcp_data[close_col]: continue
                        c_s, v_s = vcp_data[close_col][sym], vcp_data["Volume"][sym] if "Volume" in vcp_data else vcp_data[close_col][sym]
                        h_s, l_s = vcp_data["High"][sym] if "High" in vcp_data else c_s, vcp_data["Low"][sym] if "Low" in vcp_data else c_s
                    else:
                        c_s, v_s = vcp_data[close_col], vcp_data.get("Volume", vcp_data[close_col])
                        h_s, l_s = vcp_data.get("High", c_s), vcp_data.get("Low", c_s)
                    df = pd.DataFrame({"close": c_s, "volume": v_s, "high": h_s, "low": l_s}).dropna()
                    res = analyze_vcp(df, nifty_close)
                    if res: res["Ticker"] = sym.replace(".NS", "").replace(".BO", ""); vcp_results.append(res)
                except: continue
        except: continue
        time.sleep(0.1)
    progress_bar.empty()
    return {"data": vcp_results}

@st.cache_data(ttl=86400)
def fetch_and_run_pocket_pivots(vcp_stocks_list):
    if not vcp_stocks_list: return []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    pp_results = []
    progress_bar = st.progress(0, text="Starting Pocket Pivot Scan...")
    chunk_size = 100
    total_chunks = (len(vcp_stocks_list) // chunk_size) + 1
    
    for i in range(0, len(vcp_stocks_list), chunk_size):
        chunk_num = (i // chunk_size) + 1
        progress_bar.progress(chunk_num / total_chunks, text=f"Pocket Pivot Scan: Batch {chunk_num}/{total_chunks}...")
        chunk = vcp_stocks_list[i:i + chunk_size]
        try:
            data = yf.download(chunk, period="6mo", interval="1d", threads=True, progress=False, session=session)
            if data.empty: continue
            is_multi = isinstance(data.columns, pd.MultiIndex)
            close_col = "Adj Close" if ("Adj Close" in data.columns.get_level_values(0) if is_multi else "Adj Close" in data) else "Close"
            for sym in chunk:
                try:
                    if is_multi:
                        if sym not in data[close_col]: continue
                        c_s, v_s = data[close_col][sym], data["Volume"][sym] if "Volume" in data else data[close_col][sym]
                    else:
                        c_s, v_s = data[close_col], data.get("Volume", data[close_col])
                    df = pd.DataFrame({"close": c_s, "volume": v_s}).dropna()
                    if analyze_pocket_pivot(df):
                        latest_price = df["close"].iloc[-1]
                        prev_close = df["close"].iloc[-2]
                        change_pct = ((latest_price - prev_close) / prev_close) * 100
                        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
                        pp_results.append({
                            "Ticker": sym.replace(".NS", "").replace(".BO", ""), "Sector": "VCP Universe",
                            "LatestPrice": latest_price, "ChangePct": change_pct, "Volume": df["volume"].iloc[-1], "AvgVolume": avg_vol if pd.notna(avg_vol) else 1
                        })
                except: continue
        except: continue
        time.sleep(0.1)
    progress_bar.empty()
    return pp_results

@st.cache_data(ttl=86400)
def fetch_and_run_avwap_squeezes(vcp_stocks_list):
    if not vcp_stocks_list: return []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    avwap_results = []
    progress_bar = st.progress(0, text="Starting AVWAP Squeeze Scan...")
    chunk_size = 100
    total_chunks = (len(vcp_stocks_list) // chunk_size) + 1
    
    for i in range(0, len(vcp_stocks_list), chunk_size):
        chunk_num = (i // chunk_size) + 1
        progress_bar.progress(chunk_num / total_chunks, text=f"AVWAP Squeeze Scan: Batch {chunk_num}/{total_chunks}...")
        chunk = vcp_stocks_list[i:i + chunk_size]
        try:
            data = yf.download(chunk, period="1y", interval="1d", threads=True, progress=False, session=session)
            if data.empty: continue
            is_multi = isinstance(data.columns, pd.MultiIndex)
            close_col = "Adj Close" if ("Adj Close" in data.columns.get_level_values(0) if is_multi else "Adj Close" in data) else "Close"
            for sym in chunk:
                try:
                    if is_multi:
                        if sym not in data[close_col]: continue
                        c_s = data[close_col][sym]
                        v_s = data["Volume"][sym] if "Volume" in data else c_s
                        h_s = data["High"][sym] if "High" in data else c_s
                        l_s = data["Low"][sym] if "Low" in data else c_s
                    else:
                        c_s = data[close_col]
                        v_s = data.get("Volume", c_s)
                        h_s = data.get("High", c_s)
                        l_s = data.get("Low", c_s)
                    df = pd.DataFrame({"close": c_s, "volume": v_s, "high": h_s, "low": l_s}).dropna()
                    res = analyze_avwap_squeeze(df)
                    if res:
                        res["Ticker"] = sym.replace(".NS", "").replace(".BO", "")
                        avwap_results.append(res)
                except: continue
        except: continue
        time.sleep(0.1)
    progress_bar.empty()
    return avwap_results

st.markdown("<br>", unsafe_allow_html=True)
_, col2, _ = st.columns([1, 2, 1])

with col2:
    selected_tab = st.radio("Navigation", ["📊 Market Breadth", "🚀 VCP Screener", "🎯 Pocket Pivot Tracker", "⚓ AVWAP Squeeze"], horizontal=True, label_visibility="collapsed")
st.divider()

if selected_tab == "📊 Market Breadth":
    st.sidebar.header("Strategy Parameters")
    rs_period = st.sidebar.selectbox("Relative Strength Period", ["21 Days", "55 Days", "100 Days"], index=1)
    rsi_thresh = st.sidebar.slider("Minimum RSI", 30, 80, 50)
    display_mode = st.sidebar.radio("Weighting Mode", ["Number of Stocks", "% of Sector Market Cap"])

    st.title("Indian Market Sector Dashboard")
    st.markdown("Advanced breadth tracking with dynamic Relative Strength and volume profiling.")

    if "market_data" not in st.session_state:
        st.session_state.market_data = fetch_and_calculate()
            
    payload = st.session_state.market_data
    master_df = payload.get("data", pd.DataFrame()) if isinstance(payload, dict) else pd.DataFrame()
    missing_list = payload.get("missing", []) if isinstance(payload, dict) else []

    if missing_list:
        with st.expander(f"⚠️ {len(missing_list)} Stocks Failed to Load (Click to view)"):
            st.write(", ".join(missing_list))

    if not master_df.empty:
        rs_col = {"21 Days": "RS_21", "55 Days": "RS_55", "100 Days": "RS_100"}[rs_period]

        master_df["RS_Pass"] = master_df[rs_col].apply(lambda x: 1 if pd.notna(x) and x > 0 else 0)
        master_df["RSI_Pass"] = master_df["RSI_14"].apply(lambda x: 1 if pd.notna(x) and x > rsi_thresh else 0)
        master_df["SMA20_Pass"] = master_df.apply(lambda r: 1 if pd.notna(r["SMA_20"]) and r["CurrentPrice"] > r["SMA_20"] else 0, axis=1)
        master_df["SMA50_Pass"] = master_df.apply(lambda r: 1 if pd.notna(r["SMA_50"]) and r["CurrentPrice"] > r["SMA_50"] else 0, axis=1)
        master_df["SMA100_Pass"] = master_df.apply(lambda r: 1 if pd.notna(r["SMA_100"]) and r["CurrentPrice"] > r["SMA_100"] else 0, axis=1)
        master_df["SMA200_Pass"] = master_df.apply(lambda r: 1 if pd.notna(r["SMA_200"]) and r["CurrentPrice"] > r["SMA_200"] else 0, axis=1)
        master_df["VolumeSurge"] = master_df.apply(lambda r: 1 if r["Volume"] > (1.5 * r["AvgVolume"]) else 0, axis=1)

        dash_tbl, dash_cht = [], []
        for sector in master_df["Sector"].unique():
            sec_df = master_df[master_df["Sector"] == sector]
            total_mc, total_stocks = sec_df["MarketCap"].sum(), len(sec_df)

            def get_val(flag, ret_fmt="table"):
                val = sec_df[flag].sum() if display_mode == "Number of Stocks" else (sec_df[sec_df[flag] == 1]["MarketCap"].sum() / max(total_mc, 1) * 100)
                if ret_fmt == "chart": return (val / max(total_stocks, 1) * 100) if display_mode == "Number of Stocks" else val
                return f"{val} / {total_stocks}" if display_mode == "Number of Stocks" else f"{val:.1f}%"

            dash_tbl.append({"Sectors": sector, f"RS > 0 ({rs_period})": get_val("RS_Pass"), f"RSI > {rsi_thresh}": get_val("RSI_Pass"), "SMA 20": get_val("SMA20_Pass"), "SMA 50": get_val("SMA50_Pass"), "SMA 100": get_val("SMA100_Pass"), "SMA 200": get_val("SMA200_Pass")})
            dash_cht.append({"Sectors": sector, f"RS > 0 ({rs_period})": get_val("RS_Pass", "chart")})

        st.subheader(f"Sector Rotation ({display_mode})")
        st.plotly_chart(px.bar(pd.DataFrame(dash_cht), x="Sectors", y=f"RS > 0 ({rs_period})", color="Sectors", text_auto='.1f', title=f"Percentage of Sector Outperforming Nifty ({rs_period})"), width="stretch")

        st.subheader("Market Breadth Data")
        st.dataframe(pd.DataFrame(dash_tbl), width="stretch", hide_index=True)
        
        if st.button("Refresh Live Data"):
            fetch_and_calculate.clear()
            get_token_map.clear()
            st.session_state.pop("market_data", None)
            st.rerun()

        st.markdown("---")
        st.subheader("Screener & Export")
        
        sel1, sel2, sel3 = st.columns(3)
        with sel1: sel_sec = st.selectbox("1. Select a Sector:", pd.DataFrame(dash_tbl)["Sectors"].tolist())
        with sel2: sel_ind = st.selectbox("2. Select an Indicator:", ["Relative Strength", "RSI Threshold", "SMA 20", "SMA 50", "SMA 100", "SMA 200", "Volume Surge"])
        with sel3: sort_by = st.selectbox("3. Sort Results By:", ["Highest % Gain", "Highest RSI", "Highest RS"])
        
        flag_map = {"Relative Strength": "RS_Pass", "RSI Threshold": "RSI_Pass", "SMA 20": "SMA20_Pass", "SMA 50": "SMA50_Pass", "SMA 100": "SMA100_Pass", "SMA 200": "SMA200_Pass", "Volume Surge": "VolumeSurge"}
        winning = master_df[(master_df["Sector"] == sel_sec) & (master_df[flag_map[sel_ind]] == 1)].copy()

        if sort_by == "Highest % Gain": winning = winning.sort_values(by="ChangePct", ascending=False)
        elif sort_by == "Highest RSI": winning = winning.sort_values(by="RSI_14", ascending=False)
        else: winning = winning.sort_values(by=rs_col, ascending=False)

        if not winning.empty:
            st.download_button("Download Data (CSV)", winning[["Ticker", "CurrentPrice", "ChangePct", "RSI_14", rs_col, "VolumeSurge"]].to_csv(index=False).encode('utf-8'), f"{sel_sec}_screener.csv", "text/csv")
            cols = st.columns(3)
            for i, (_, stock) in enumerate(winning.iterrows()):
                col = cols[i % 3] 
                color, sign = ("green", "+") if stock["ChangeRs"] >= 0 else ("red", "")
                surge = " | <strong>Volume Breakout</strong>" if stock["VolumeSurge"] == 1 else ""
                with col:
                    html_card = (
                        f'<div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 24px; border-radius: 18px; margin-bottom: 16px;">'
                        f'<span style="font-family: -apple-system, sans-serif; font-weight: 600; font-size: 17px; color: #1d1d1f;">{stock["Ticker"]}</span>'
                        f'<span style="color: #0066cc; font-size: 14px; font-weight: 400;">{surge}</span><br>'
                        f'<div style="margin-top: 12px; font-size: 17px; color: #1d1d1f; font-weight: 400; line-height: 1.47;">'
                        f'₹{stock["CurrentPrice"]:.2f} <br>'
                        f'<span style="color: {color}; font-weight: 600;">{sign}₹{stock["ChangeRs"]:.2f} ({sign}{stock["ChangePct"]:.2f}%)</span><br></div>'
                        f'<div style="margin-top: 17px; font-size: 14px; color: #7a7a7a; font-weight: 400;">RSI: {stock["RSI_14"]:.1f} &nbsp;|&nbsp; RS: {stock[rs_col]*100:.1f}%</div></div>'
                    )
                    st.markdown(html_card, unsafe_allow_html=True)
        else: st.write("No stocks meet this criteria right now.")

elif selected_tab == "🚀 VCP Screener":
    st.markdown("<h2 style='font-family: -apple-system, sans-serif; font-weight: 600; color: #1d1d1f; letter-spacing: -0.374px;'>Minervini Volatility Contraction Pattern (VCP) Screener</h2><p style='font-size: 17px; color: #7a7a7a; margin-bottom: 24px;'>Identifies Stage-2 uptrend stocks experiencing extreme volatility compression and volume dry-up (VDU) prior to explosive breakouts.</p>", unsafe_allow_html=True)

    if st.button("🔄 Refresh VCP Scan Data"):
        fetch_and_run_vcp.clear()
        st.session_state.pop("vcp_results", None)
        st.rerun()

    st.sidebar.markdown("### VCP Parameters")
    min_vcp_score = st.sidebar.slider("Minimum VCP Score", 50, 90, 60, 5)
    max_tightness = st.sidebar.slider("Max Pivot Tightness (%)", 2.0, 10.0, 6.0, 0.5)

    if "vcp_results" not in st.session_state:
        with st.spinner(f"Analyzing universe of {len(VCP_STOCKS)} stocks..."):
            st.session_state.vcp_results = fetch_and_run_vcp(VCP_STOCKS)
            
    raw_results = st.session_state.vcp_results
    if isinstance(raw_results, dict) and "error" in raw_results:
        st.error(f"⚠️ {raw_results['error']}")
    else:
        actual_data = raw_results.get("data", []) if isinstance(raw_results, dict) else raw_results
        if not actual_data:
            st.warning("No data returned or calculation pending. Click 'Refresh VCP Scan Data'.")
        else:
            filtered = [r for r in actual_data if r["VCPScore"] >= min_vcp_score and r["PivotTightnessPct"] <= max_tightness]
            if not filtered:
                st.warning(f"No stocks meet VCP Score ≥ {min_vcp_score} and Tightness ≤ {max_tightness}%.")
            else:
                vcp_df = pd.DataFrame(filtered).sort_values(by="VCPScore", ascending=False)
                st.markdown(f"**Found {len(vcp_df)} Institutional VCP Setups out of {len(VCP_STOCKS)} stocks**")
                cols = st.columns(3)
                for idx, row in vcp_df.reset_index(drop=True).iterrows():
                    col = cols[idx % 3]
                    vdu = '<span style="background-color: #0066cc; color: white; font-size: 11px; padding: 3px 8px; border-radius: 9999px; font-weight: 600;">VDU ACTIVE</span>' if row['IsVDU'] else ''
                    with col:
                        html_card = (
                            f'<div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 24px; border-radius: 18px; margin-bottom: 20px;">'
                            f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                            f'<span style="font-family: -apple-system, sans-serif; font-weight: 600; font-size: 21px; color: #1d1d1f;">{row["Ticker"]}</span>{vdu}</div>'
                            f'<div style="margin-top: 16px; font-size: 28px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.28px;">₹{row["LatestPrice"]:.2f}</div>'
                            f'<div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; font-size: 14px; color: #1d1d1f; line-height: 1.6;">'
                            f'<b>VCP Rating Score:</b> <span style="color: #0066cc; font-weight: 600;">{row["VCPScore"]}/100</span><br>'
                            f'<b>Pivot Tightness:</b> {row["PivotTightnessPct"]:.1f}% (10-Day Range)<br>'
                            f'<b>Base Depth:</b> {row["BaseDepthPct"]:.1f}%<br>'
                            f'<b>Dist. from 52W High:</b> {row["DistFrom52wHigh"]:.1f}%<br>'
                            f'<b>55D Rel. Strength:</b> +{row["RS55"]:.1f}%</div></div>'
                        )
                        st.markdown(html_card, unsafe_allow_html=True)

elif selected_tab == "🎯 Pocket Pivot Tracker":
    st.markdown("<h2 style='font-family: -apple-system, sans-serif; font-weight: 600; color: #1d1d1f; letter-spacing: -0.374px;'>Institutional Pocket Pivot Tracker</h2><p style='font-size: 17px; color: #7a7a7a; margin-bottom: 24px;'>Identifies quiet institutional accumulation days across your VCP stock universe.</p>", unsafe_allow_html=True)

    if st.button("🔄 Refresh Pocket Pivot Scan"):
        fetch_and_run_pocket_pivots.clear()
        st.session_state.pop("pocket_pivot_results", None)
        st.rerun()

    if "pocket_pivot_results" not in st.session_state:
        with st.spinner(f"Scanning universe of {len(VCP_STOCKS)} stocks via Yahoo Finance..."):
            st.session_state.pocket_pivot_results = fetch_and_run_pocket_pivots(VCP_STOCKS)

    pp_data = st.session_state.pocket_pivot_results
    if not pp_data:
        st.warning("No Pocket Pivot setups detected in your VCP stock file today.")
    else:
        st.markdown(f"**Found {len(pp_data)} Institutional Pocket Pivot Setups**")
        cols = st.columns(3)
        for idx, row in enumerate(pp_data):
            col = cols[idx % 3]
            with col:
                html_card = (
                    f'<div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 24px; border-radius: 18px; margin-bottom: 20px;">'
                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                    f'<span style="font-family: -apple-system, sans-serif; font-weight: 600; font-size: 21px; color: #1d1d1f;">{row["Ticker"]}</span>'
                    f'<span style="background-color: #34c759; color: white; font-size: 11px; padding: 3px 8px; border-radius: 9999px; font-weight: 600;">POCKET PIVOT</span></div>'
                    f'<div style="margin-top: 16px; font-size: 28px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.28px;">₹{row["LatestPrice"]:.2f}</div>'
                    f'<div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; font-size: 14px; color: #1d1d1f; line-height: 1.6;">'
                    f'<b>Day Change:</b> <span style="color: #34c759; font-weight: 600;">+{row["ChangePct"]:.2f}%</span><br>'
                    f'<b>Volume vs Avg:</b> {(row["Volume"]/row["AvgVolume"]):.1f}x Average</div></div>'
                )
                st.markdown(html_card, unsafe_allow_html=True)

elif selected_tab == "⚓ AVWAP Squeeze":
    st.markdown("<h2 style='font-family: -apple-system, sans-serif; font-weight: 600; color: #1d1d1f; letter-spacing: -0.374px;'>Anchored VWAP (AVWAP) Squeeze Screener</h2><p style='font-size: 17px; color: #7a7a7a; margin-bottom: 24px;'>Identifies stocks coiling tightly against their institutional swing-low Anchored VWAP line.</p>", unsafe_allow_html=True)

    if st.button("🔄 Refresh AVWAP Squeeze Scan"):
        fetch_and_run_avwap_squeezes.clear()
        st.session_state.pop("avwap_squeeze_results", None)
        st.rerun()

    if "avwap_squeeze_results" not in st.session_state:
        with st.spinner(f"Scanning universe of {len(VCP_STOCKS)} stocks for AVWAP Squeezes..."):
            st.session_state.avwap_squeeze_results = fetch_and_run_avwap_squeezes(VCP_STOCKS)

    avwap_data = st.session_state.avwap_squeeze_results
    if not avwap_data:
        st.warning("No AVWAP Squeeze setups detected in your VCP stock file today.")
    else:
        st.markdown(f"**Found {len(avwap_data)} Institutional AVWAP Squeeze Setups**")
        cols = st.columns(3)
        for idx, row in enumerate(avwap_data):
            col = cols[idx % 3]
            with col:
                html_card = (
                    f'<div style="background-color: #ffffff; border: 1px solid #e0e0e0; padding: 24px; border-radius: 18px; margin-bottom: 20px;">'
                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                    f'<span style="font-family: -apple-system, sans-serif; font-weight: 600; font-size: 21px; color: #1d1d1f;">{row["Ticker"]}</span>'
                    f'<span style="background-color: #007aff; color: white; font-size: 11px; padding: 3px 8px; border-radius: 9999px; font-weight: 600;">AVWAP SQUEEZE</span></div>'
                    f'<div style="margin-top: 16px; font-size: 28px; font-weight: 600; color: #1d1d1f; letter-spacing: -0.28px;">₹{row["LatestPrice"]:.2f}</div>'
                    f'<div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; font-size: 14px; color: #1d1d1f; line-height: 1.6;">'
                    f'<b>AVWAP Level:</b> ₹{row["AVWAP"]:.2f}<br>'
                    f'<b>Distance from AVWAP:</b> {row["DistPct"]:.2f}%<br>'
                    f'<b>Recent Tightness:</b> {row["TightnessPct"]:.2f}%</div></div>'
                )
                st.markdown(html_card, unsafe_allow_html=True)