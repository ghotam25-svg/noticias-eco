"""Sentimiento de otros traders: Fear & Greed (CNN) y StockTwits (mensajes etiquetados alcista/bajista)."""
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SYMBOLS = [("US100 / Nasdaq", "QQQ"), ("S&P 500", "SPY"), ("Nvidia", "NVDA"), ("Apple", "AAPL"),
           ("Microsoft", "MSFT"), ("Tesla", "TSLA"), ("Bitcoin", "BTC.X"), ("Oro", "GLD")]
RATING_ES = {"extreme fear": "Miedo extremo", "fear": "Miedo", "neutral": "Neutral", "greed": "Codicia",
             "extreme greed": "Codicia extrema"}

BULL = re.compile(r"upgrade|\bbuy\b|bullish|rally|breakout|\blong\b|outperform|raises? (?:price )?target|"
                  r"target raised|surge|soar|jumps?|gains?|record high|beats?\b|calls\b|higher|rebound|upside", re.I)
BEAR = re.compile(r"downgrade|\bsell\b|bearish|plunge|drop|\bshort\b|underperform|cuts? (?:price )?target|"
                  r"target cut|lowers? (?:price )?target|miss(?:es)?\b|puts\b|lower|trap|bears?\b|selloff|slump|downside|"
                  r"warning|falls?\b|tumbles?|slides?|losses|lows?\b|weak(?:ens|er)?", re.I)


def stance(text):
    b, s = len(BULL.findall(text)), len(BEAR.findall(text))
    if b > s:
        return "alcista"
    if s > b:
        return "bajista"
    return "neutral"


def fear_greed():
    try:
        j = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", headers=H, timeout=20).json()
        f = j["fear_and_greed"]
        return {"score": round(f["score"]), "rating": RATING_ES.get(f["rating"], f["rating"]),
                "prev": round(f.get("previous_close", 0)), "week": round(f.get("previous_1_week", 0))}
    except Exception as ex:
        print("  ! fear&greed:", ex, file=sys.stderr)
        return None


def _st(item):
    name, sym = item
    try:
        r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json", headers=H, timeout=20)
        r.raise_for_status()
        msgs = r.json()["messages"]
    except Exception as ex:
        print(f"  ! stocktwits {sym}: {ex}", file=sys.stderr)
        return None
    bull = bear = 0
    best = []
    for m in msgs:
        s = (m["entities"].get("sentiment") or {}).get("basic")
        if s == "Bullish":
            bull += 1
        elif s == "Bearish":
            bear += 1
        if s and 40 < len(m["body"]) < 300:
            best.append({"side": "alcista" if s == "Bullish" else "bajista", "text": m["body"].replace("\n", " "),
                         "user": m["user"]["username"], "likes": (m.get("likes") or {}).get("total", 0)})
    best.sort(key=lambda x: -x["likes"])
    return {"name": name, "symbol": sym, "bull": bull, "bear": bear, "n": len(msgs), "msgs": best[:2]}


def sentiment(translate_batch):
    with ThreadPoolExecutor(4) as ex:
        st = [x for x in ex.map(_st, SYMBOLS) if x]
    texts = [m["text"] for s in st for m in s["msgs"]]
    if texts:
        tr = translate_batch(texts)
        i = 0
        for s in st:
            for m in s["msgs"]:
                m["text_es"] = tr[i] or m["text"]
                i += 1
    print(f"  sentimiento traders: {len(st)} símbolos")
    return {"fng": fear_greed(), "stocktwits": st}
