import os
import re
import json
import time
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import numpy as np
import requests

# ── Dynamic Configuration Storage ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ALIASES_FILE = os.path.join(DATA_DIR, "aliases.json")
NAMES_FILE = os.path.join(DATA_DIR, "names.json")

def load_data(file_path, default_val):
    if not os.path.exists(file_path):
        return default_val
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return default_val

def save_data(file_path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Global instances (load once at start)
STOCK_NAMES = load_data(NAMES_FILE, {})
STOCK_ALIASES = load_data(ALIASES_FILE, {})

# ── Simple In-Memory Cache ──
STOCK_CACHE = {} # { ticker: { "data": ..., "expires": ... } }
CACHE_TTL = 300  # 5 minutes

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.dirname(os.path.abspath(__file__))), name="static")

# ── Alias Management API ──
@app.get("/api/admin/aliases")
def get_aliases():
    return {
        "aliases": STOCK_ALIASES,
        "names": STOCK_NAMES
    }

@app.post("/api/admin/aliases")
async def update_alias(data: dict):
    alias_key = data.get("alias")
    ticker = data.get("ticker")
    display_name = data.get("name")

    if not alias_key or not ticker:
        raise HTTPException(status_code=400, detail="Missing alias or ticker")

    # Update global state
    STOCK_ALIASES[alias_key] = ticker
    if display_name:
        STOCK_NAMES[ticker] = display_name

    # Persist
    save_data(ALIASES_FILE, STOCK_ALIASES)
    save_data(NAMES_FILE, STOCK_NAMES)
    
    return {"status": "success"}

@app.delete("/api/admin/aliases/{key}")
def delete_alias(key: str):
    if key in STOCK_ALIASES:
        del STOCK_ALIASES[key]
        save_data(ALIASES_FILE, STOCK_ALIASES)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Alias not found")


# ───────── Reverse Lookup Alias Dictionary ─────────
# Maps Chinese names / aliases → ticker symbol
# Supports: 多對一 (many-to-one), ADR variants, common abbreviations

def get_stock_name(ticker: str) -> str:
    """Zero-latency name lookup. Returns Chinese name or empty string."""
    t_upper = ticker.upper()
    return STOCK_NAMES.get(t_upper, STOCK_NAMES.get(ticker, ""))

def resolve_ticker(raw_input: str) -> str:
    """
    Smart ticker resolution:
    1. Strip whitespace
    2. Check exact/case-insensitive alias match
    3. Look for 4-6 digit codes inside the string (e.g. "力致3483" -> "3483")
    4. If digits found -> Use alias or append .TW
    5. Fallback: pass through
    """
    q = raw_input.strip()
    if not q: return q

    # Step 1: Exact / Case-insensitive Alias
    if q in STOCK_ALIASES: return STOCK_ALIASES[q]
    q_upper = q.upper()
    if q_upper in STOCK_ALIASES: return STOCK_ALIASES[q_upper]

    # Step 2: Extract numeric code (4-6 digits)
    # Skip if already has a dot (indicator of a handled suffix like .T, .HK, .TW)
    if "." not in q:
        match = re.search(r'(\d{4,6})', q)
        if match:
            code = match.group(1)
            if code in STOCK_ALIASES: return STOCK_ALIASES[code]
            return code

    # Step 3: CHINESE DYNAMIC SEARCH
    # Detect if contains Chinese characters: [\u4e00-\u9fff]
    if re.search(r'[\u4e00-\u9fff]', q):
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        params = {"q": q, "quotesCount": 5}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=3)
            data = resp.json()
            quotes = data.get("quotes", [])
            for res in quotes:
                # Prefer EQUITY, ETF, or INDEX matches
                if res.get("quoteType") in ["EQUITY", "ETF", "INDEX"]:
                    return res.get("symbol")
        except Exception as e:
            print(f"[Dynamic Alias] Error searching for {q}: {e}")
        return None # Explicitly fail Chinese resolution instead of passing raw Chinese

    # Step 4: Pass through
    return q_upper

# ───────── Technical Indicator Calculations ─────────

def calculate_rsi(data, period=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_kd(data, period=9):
    low_min = data['Low'].rolling(window=period).min()
    high_max = data['High'].rolling(window=period).max()
    rsv = 100 * ((data['Close'] - low_min) / (high_max - low_min))
    k = rsv.rolling(window=3).mean()
    d = k.rolling(window=3).mean()
    return k, d

# ───────── Granville 8 Rules Engine ─────────

def classify_granville(close, ma20, prev_close, prev_ma20, ma20_slope):
    """
    Full Granville 8 rules classification.
    B1-B4 = Buy signals, S1-S4 = Sell signals
    """
    above = close > ma20
    prev_above = prev_close > prev_ma20
    ma_rising = ma20_slope > 0

    # B1: Price crosses above a rising MA
    if not prev_above and above and ma_rising:
        return "B1", "偏多訊號", "buy"
    # B2: Price dips below rising MA then recovers
    if not above and ma_rising and prev_close > prev_ma20:
        return "B2", "回測支撐", "buy"
    # B3: Price is above MA and stays above (continuation)
    if above and prev_above and ma_rising:
        return "B3", "偏多延續", "buy"
    # B4: Price far below falling MA (oversold bounce)
    if not above and not ma_rising and (ma20 - close) / ma20 > 0.05:
        return "B4", "超跌反彈", "buy"

    # S1: Price crosses below a falling MA
    if prev_above and not above and not ma_rising:
        return "S1", "偏空訊號", "sell"
    # S2: Price bounces to falling MA then falls again
    if above and not ma_rising and not prev_above:
        return "S2", "反彈遇壓", "sell"
    # S3: Price is below MA and stays below (continuation)
    if not above and not prev_above and not ma_rising:
        return "S3", "弱勢整理", "sell"
    # S4: Price far above rising MA (overbought)
    if above and ma_rising and (close - ma20) / ma20 > 0.08:
        return "S4", "過熱回落", "sell"

    # Default fallback
    if above:
        return "B3", "偏多延續", "buy"
    else:
        return "S3", "弱勢整理", "sell"

# ───────── Strategy War Room Logic ─────────

def build_strategy(price, ma5, ma20, ma60, rsi, k, d, support, resistance, granville_code, granville_label, signal_type):
    """
    Generates comprehensive strategy analysis matching V14 features:
    - 適合動作 (Recommended Action)
    - 進場時機 (Entry Timing)
    - 持有者動作 (Holder Advice)
    - 判斷依據 (Judgment Basis list)
    - 風險提醒 (Risk Warnings)
    - 綜合分數 (Composite Score)
    """
    reasons = []
    risks = []
    score = 0

    # ── Price vs MA analysis ──
    if price > ma20:
        reasons.append("價格在 20MA 之上，短期偏多")
        score += 2
    else:
        reasons.append("價格在 20MA 之下，短期偏弱")
        score -= 2

    if ma5 > ma20:
        reasons.append("短線均線在中期均線之上，趨勢向上")
        score += 1
    else:
        reasons.append("短線均線仍在中期均線之下，趨勢偏弱")
        score -= 1

    if ma20 > ma60:
        reasons.append("中期趨勢比長期趨勢強")
        score += 1
    else:
        reasons.append("中期趨勢弱於長期趨勢")
        score -= 1

    # ── RSI analysis ──
    if rsi > 70:
        reasons.append(f"RSI={rsi:.1f}，已進入超買區域")
        risks.append("RSI 超買警示，短線可能拉回修正")
        score -= 1
    elif rsi < 30:
        reasons.append(f"RSI={rsi:.1f}，已進入超賣區域，可能反彈")
        score += 1
    elif rsi >= 50:
        reasons.append(f"RSI={rsi:.1f}，位置偏健康")
        score += 1
    else:
        reasons.append(f"RSI={rsi:.1f}，偏弱但未超賣")

    # ── KD analysis ──
    if k > d and k < 30:
        reasons.append(f"KD 在低檔黃金交叉 (K={k:.1f}, D={d:.1f})，短線反彈訊號")
        score += 2
    elif k < d and k > 70:
        reasons.append(f"KD 在高檔死亡交叉 (K={k:.1f}, D={d:.1f})，短線回檔訊號")
        score -= 2
    elif k > d:
        reasons.append(f"KD 呈黃金交叉 (K={k:.1f}, D={d:.1f})")
        score += 1
    else:
        reasons.append(f"KD 呈死亡交叉 (K={k:.1f}, D={d:.1f})")
        score -= 1

    # ── Support/Resistance risk ──
    dist_to_support = (price - support) / price * 100
    dist_to_resistance = (resistance - price) / price * 100

    if dist_to_support < 2:
        risks.append(f"股價逼近支撐位 {support:.0f}，距離僅 {dist_to_support:.1f}%，跌破恐加速下跌")
    if dist_to_resistance < 2:
        risks.append(f"股價逼近壓力位 {resistance:.0f}，距離僅 {dist_to_resistance:.1f}%，突破則看多")

    # ── Generate action recommendations ──
    if signal_type == "buy" and score >= 3:
        action = "可以考慮分批佈局，趨勢偏多。"
        timing = "技術面偏強，可逢回找買點。"
        holder = "繼續持有，設好停利點。"
        overall = "偏強"
    elif signal_type == "buy" and score >= 0:
        action = "可小量試單，但需留意風險。"
        timing = "尚可，但建議配合量能觀察。"
        holder = "持股續抱，但注意均線是否轉弱。"
        overall = "中性偏多"
    elif signal_type == "sell" and score <= -3:
        action = "暫時不要新買，先保守。"
        timing = "現在不是好的進場點。"
        holder = "若已持有，先觀察支撐是否守住，跌破可考慮減碼。"
        overall = "偏弱"
        risks.append("多項指標轉弱，建議提高警覺")
    else:
        action = "觀望為主，等待方向明朗。"
        timing = "尚未出現明確進場訊號。"
        holder = "持股者可暫時持有，但設好停損。"
        overall = "中性偏弱"

    return {
        "composite_score": score,
        "overall_state": overall,
        "action": action,
        "timing": timing,
        "holder_advice": holder,
        "reasons": reasons,
        "risks": risks if risks else ["目前無重大風險警示"],
        "support": round(support, 1),
        "resistance": round(resistance, 1),
        "dist_to_support_pct": round(dist_to_support, 2),
        "dist_to_resistance_pct": round(dist_to_resistance, 2),
    }

# ───────── API Endpoint ─────────

@app.get("/api/search")
async def search_suggestions(q: str):
    """Autocomplete: returns suggestions from Yahoo Finance search API."""
    if not q: return {"quotes": []}
    
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&quotesCount=10"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        # Note: In production, consider using httpx (async) but requests is already in requirements.
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        
        # Filter and format: [Symbol] Name (Exchange)
        results = []
        for q in data.get("quotes", []):
            if q.get("quoteType") in ["EQUITY", "ETF", "INDEX"]:
                results.append({
                    "symbol": q.get("symbol"),
                    "name": q.get("shortname") or q.get("longname") or "",
                    "exchDisp": q.get("exchDisp") or q.get("exchange") or "",
                })
        return {"quotes": results}
        
    except Exception as e:
        # Fallback or empty on error to avoid breaking the UI
        print(f"[Search Engine] Error: {e}")
        return {"quotes": []}

@app.get("/api/stock/{ticker}")
async def get_stock_data_api(ticker: str, name: str = Query(None)):
    """
    Unified stock data endpoint with 5-minute caching.
    """
    resolved = resolve_ticker(ticker)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Cannot resolve ticker: {ticker}")

    # Check Cache
    now = time.time()
    if resolved in STOCK_CACHE:
        cached = STOCK_CACHE[resolved]
        if now < cached["expires"]:
            print(f"[Cache Hit] {resolved}")
            # Return cached data but override the name if provided
            data = cached["data"].copy()
            if name: data["stock_name"] = name
            return data

    try:
        data = get_stock_data_logic(resolved, name)
        # Update Cache
        STOCK_CACHE[resolved] = {
            "data": data,
            "expires": now + CACHE_TTL
        }
        return data
    except Exception as e:
        # Check if it's a 429
        error_str = str(e)
        if "429" in error_str:
            raise HTTPException(status_code=429, detail="Yahoo Finance rate limit exceeded")
        raise HTTPException(status_code=500, detail=error_str)

# Rename the original function to avoid conflict and keep original logic
def get_stock_data_logic(ticker: str, name: str = None):
    try:
        # ── Ticker Normalization & Resolution ──
        resolved = resolve_ticker(ticker)
        if not resolved or re.search(r'[\u4e00-\u9fff]', resolved):
             raise HTTPException(status_code=404, detail=f"Invalid or unresolvable ticker: {ticker}")
             
        actual_ticker = resolved.upper()
        df = pd.DataFrame()
        
        # If it's a 4-6 digit code, or a code that ends with .TW
        is_tw_numeric = actual_ticker.isdigit() or (len(actual_ticker) > 3 and actual_ticker[:-3].isdigit() and actual_ticker.endswith(".TW"))
        
        if is_tw_numeric:
            base_code = actual_ticker[:-3] if actual_ticker.endswith(".TW") else actual_ticker
            # Step 1: Try .TW (Listed)
            primary = f"{base_code}.TW"
            stock = yf.Ticker(primary)
            df = stock.history(period="6mo")
            
            # Step 2: Fallback to .TWO (OTC) if .TW returns nothing
            if df.empty:
                secondary = f"{base_code}.TWO"
                stock = yf.Ticker(secondary)
                df = stock.history(period="6mo")
                # Step 3: Final Fallback to RAW numeric (e.g. 7974 JP)
                if df.empty:
                    actual_ticker = base_code
                    stock = yf.Ticker(actual_ticker)
                    df = stock.history(period="6mo")
                else:
                    actual_ticker = secondary
            else:
                actual_ticker = primary
        else:
            # Regular ticker (US, HK, JP or already suffixed)
            stock = yf.Ticker(actual_ticker)
            df = stock.history(period="6mo")
            
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
        
        # ── NAME RESOLUTION ──
        # 1. Use passed name (frontend suggestion)
        # 2. Use STOCK_NAMES (hardcoded Top 30)
        # 3. Leave empty or use ticker
        final_name = name if name else get_stock_name(actual_ticker)
        
        ticker = actual_ticker # Update ticker for the rest of processing
        df = df.dropna()

        # Calculate all indicators
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        df['RSI'] = calculate_rsi(df)
        df['K'], df['D'] = calculate_kd(df)
        df = df.dropna()

        if df.empty or len(df) < 3:
            raise HTTPException(status_code=404, detail="Not enough data.")

        # Latest values
        price = float(df['Close'].iloc[-1])
        prev_price = float(df['Close'].iloc[-2])
        ma5 = float(df['MA5'].iloc[-1])
        ma20_now = float(df['MA20'].iloc[-1])
        ma20_prev = float(df['MA20'].iloc[-2])
        ma60_now = float(df['MA60'].iloc[-1])
        rsi = float(df['RSI'].iloc[-1])
        k_val = float(df['K'].iloc[-1])
        d_val = float(df['D'].iloc[-1])
        volume = float(df['Volume'].iloc[-1])
        vol_ma20 = float(df['Volume'].rolling(window=20).mean().iloc[-1])

        # Support & Resistance (20-day low/high)
        support = float(df['Low'].tail(20).min())
        resistance = float(df['High'].tail(20).max())

        # MA slope (rising or falling)
        ma20_slope = ma20_now - ma20_prev

        # Granville classification
        granville_code, granville_label, signal_type = classify_granville(
            price, ma20_now, prev_price, ma20_prev, ma20_slope
        )

        # Build full strategy war room
        strategy = build_strategy(
            price, ma5, ma20_now, ma60_now, rsi, k_val, d_val,
            support, resistance, granville_code, granville_label, signal_type
        )

        # Currency resolution
        ticker_upper = ticker.upper()
        if ticker_upper.endswith('.TW') or ticker_upper.endswith('.TWO'):
            currency = 'NT$'
        elif ticker_upper.endswith('.T'):
            currency = '¥'
        else:
            currency = 'US$'

        change = price - prev_price
        change_pct = (change / prev_price) * 100

        # Chart data - filter out NaN values for indicators
        dates = df.index.strftime('%Y-%m-%d').tolist()
        candles = [{"time": d, "open": round(float(r['Open']), 2), "high": round(float(r['High']), 2),
                    "low": round(float(r['Low']), 2), "close": round(float(r['Close']), 2)}
                   for d, (_, r) in zip(dates, df.iterrows())]
        ma20_chart = [{"time": d, "value": round(float(v), 2)} for d, v in zip(dates, df['MA20']) if not pd.isna(v)]
        ma60_chart = [{"time": d, "value": round(float(v), 2)} for d, v in zip(dates, df['MA60']) if not pd.isna(v)]
        kd_chart = [{"time": d, "k": round(float(k), 2), "d": round(float(dv), 2)} for d, k, dv in zip(dates, df['K'], df['D']) if not pd.isna(k) and not pd.isna(dv)]
        rsi_chart = [{"time": d, "value": round(float(v), 2)} for d, v in zip(dates, df['RSI']) if not pd.isna(v)]

        return {
            "ticker": ticker,
            "stock_name": final_name,
            "currency": currency,
            "latest_price": round(price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "candles": candles,
            "ma20": ma20_chart,
            "ma60": ma60_chart,
            "indicators": {"kd": kd_chart, "rsi": rsi_chart},
            # ── Enhanced Signal Data ──
            "signal": {
                "granville_code": granville_code,
                "granville_label": granville_label,
                "type": signal_type,  # 'buy' or 'sell'
            },
            # ── NEW: Strategy War Room ──
            "strategy": strategy,
            # ── NEW: Indicator Grid ──
            "grid": {
                "ma5": round(ma5, 1),
                "ma20": round(ma20_now, 1),
                "ma60": round(ma60_now, 1),
                "rsi": round(rsi, 1),
                "k": round(k_val, 1),
                "d": round(d_val, 1),
                "volume": int(volume),
                "vol_ma20": int(vol_ma20),
                "support": round(support, 1),
                "resistance": round(resistance, 1),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def root():
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(fp, "r", encoding="utf-8") as f:
        return f.read()
