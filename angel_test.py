from SmartApi import SmartConnect
import pyotp
import urllib.request
import json

# ==========================================
# 1. ENTER YOUR ANGEL ONE CREDENTIALS HERE
# ==========================================
API_KEY = "QeeRUvEK"
CLIENT_ID = "B371431"
PIN = "1214"
TOTP_SECRET = "TQTHBKJXNH5KCNZKQASR566R6M" # The long string of letters

def test_angel_connection():
    print("Starting Angel One connection...")
    
    # Initialize the SmartConnect object
    smartApi = SmartConnect(api_key=API_KEY)
    
    try:
        # Generate the live 6-digit TOTP automatically
        totp = pyotp.TOTP(TOTP_SECRET).now()
        
        # Log in
        data = smartApi.generateSession(CLIENT_ID, PIN, totp)
        
        if data['status'] == False:
            print("Login Failed:", data['message'])
            return
            
        print("✅ Login Successful! Tokens received.")
        
        # We need the authorization token to pull data
        feed_token = smartApi.getfeedToken()
        
        # Let's test pulling a single live quote for Reliance (Token: 2885)
        exchange = "NSE"
        symboltoken = "2885" 
        
        quote = smartApi.ltpData(exchange, "RELIANCE-EQ", symboltoken)
        
        print("\n--- Live Data Test ---")
        print(f"Reliance Live Price: ₹{quote['data']['ltp']}")
        print("----------------------\n")
        
    except Exception as e:
        print("An error occurred: ", e)

if __name__ == "__main__":
    test_angel_connection()