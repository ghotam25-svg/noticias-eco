"""Sentimiento de otros traders: Fear & Greed (CNN), StockTwits (mensajes etiquetados alcista/bajista,
temas del momento) y lectura del tono de analistas. Todo son opiniones de terceros, no recomendaciones."""
import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SYMBOLS = [("US100 · Nasdaq 100", "QQQ"), ("S&P 500", "SPY"), ("Nvidia", "NVDA"), ("Apple", "AAPL"),
           ("Microsoft", "MSFT"), ("Amazon", "AMZN"), ("Alphabet", "GOOGL"), ("Meta", "META"), ("Tesla", "TSLA"),
           ("AMD", "AMD"), ("Bitcoin", "BTC.X"), ("Oro", "GLD")]
PAGES = 2  # 2 páginas x 30 mensajes por activo
RATING_ES = {"extreme fear": "Miedo extremo", "fear": "Miedo", "neutral": "Neutral", "greed": "Codicia",
             "extreme greed": "Codicia extrema"}
FNG_PARTS = {"market_momentum_sp500": "Momentum S&P 500", "stock_price_strength": "Fortaleza de precios",
             "stock_price_breadth": "Amplitud del mercado", "put_call_options": "Opciones put/call",
             "market_volatility_vix": "Volatilidad (VIX)", "junk_bond_demand": "Demanda bonos basura",
             "safe_haven_demand": "Refugio seguro"}

BULL = re.compile(r"upgrade|\bbuy\b|bullish|rally|breakout|\blong\b|outperform|raises? (?:price )?target|"
                  r"target raised|surge|soar|jumps?|gains?|record high|beats?\b|calls\b|higher|rebound|upside", re.I)
BEAR = re.compile(r"downgrade|\bsell\b|bearish|plunge|drop|\bshort\b|underperform|cuts? (?:price )?target|"
                  r"target cut|lowers? (?:price )?target|miss(?:es)?\b|puts\b|lower|trap|bears?\b|selloff|slump|downside|"
                  r"warning|falls?\b|tumbles?|slides?|losses|lows?\b|weak(?:ens|er)?", re.I)
UPG = re.compile(r"upgrad|raises? (?:its )?(?:price )?target|target raised|initiates? .{0,30}(?:buy|outperform|overweight)", re.I)
DNG = re.compile(r"downgrad|cuts? (?:its )?(?:price )?target|lowers? (?:its )?(?:price )?target|target cut|"
                 r"initiates? .{0,30}(?:sell|underperform|underweight)", re.I)


def stance(text):
    b, s = len(BULL.findall(text)), len(BEAR.findall(text))
    if b > s:
        return "alcista"
    if s > b:
        return "bajista"
    return "neutral"


def action(text):
    """Tipo de movimiento de un analista (mejora / rebaja de calificación o precio objetivo)."""
    if DNG.search(text):
        return "rebaja"
    if UPG.search(text):
        return "mejora"
    return ""


def fear_greed():
    try:
        j = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", headers=H, timeout=20).json()
        f = j["fear_and_greed"]
        parts = []
        for k, label in FNG_PARTS.items():
            v = j.get(k)
            if v and "score" in v:
                parts.append({"name": label, "score": round(v["score"]), "rating": RATING_ES.get(v.get("rating"), v.get("rating", ""))})
        return {"score": round(f["score"]), "rating": RATING_ES.get(f["rating"], f["rating"]),
                "prev": round(f.get("previous_close", 0)), "week": round(f.get("previous_1_week", 0)),
                "month": round(f.get("previous_1_month", 0)), "parts": parts}
    except Exception as ex:
        print("  ! fear&greed:", ex, file=sys.stderr)
        return None


def _page(sym, max_id=None):
    r = requests.get(f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json",
                     params={"max": max_id} if max_id else None, headers=H, timeout=20)
    r.raise_for_status()
    return r.json()["messages"]


def _st(item):
    name, sym = item
    msgs = []
    try:
        mid = None
        for _ in range(PAGES):
            page = _page(sym, mid)
            if not page:
                break
            msgs += page
            mid = page[-1]["id"] - 1
    except Exception as ex:
        print(f"  ! stocktwits {sym}: {ex}", file=sys.stderr)
        if not msgs:
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
    # un mensaje destacado de cada lado, si existe
    pick = []
    for side in ("alcista", "bajista"):
        for b in best:
            if b["side"] == side:
                pick.append(b)
                break
    return {"name": name, "symbol": sym, "bull": bull, "bear": bear, "n": len(msgs), "msgs": pick}


def trending():
    try:
        r = requests.get("https://api.stocktwits.com/api/2/trending/symbols.json", headers=H, timeout=20)
        r.raise_for_status()
        return [{"symbol": s["symbol"], "title": s.get("title", "")} for s in r.json()["symbols"][:10]]
    except Exception as ex:
        print("  ! trending:", ex, file=sys.stderr)
        return []


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
    print(f"  sentimiento traders: {len(st)} símbolos, {sum(s['n'] for s in st)} mensajes")
    return {"fng": fear_greed(), "stocktwits": st, "trending": trending()}


# ----------------------------------------------------------------------------- presentación
def _verdict(pb, tot):
    if tot < 4:
        return "muestra muy chica", "neutral"
    if pb >= 65:
        return "claramente alcista 🟢", "bu"
    if pb >= 55:
        return "algo alcista 🟢", "bu"
    if pb <= 35:
        return "claramente bajista 🔴", "be"
    if pb <= 45:
        return "algo bajista 🔴", "be"
    return "dividido ⚪", "neutral"


def render(sn, news_items):
    """HTML de la parte de sentimiento de la pestaña Traders."""
    e = html.escape
    out = ['<div class="warn">⚠️ Son opiniones de terceros (usuarios de StockTwits, analistas y medios), no recomendaciones '
           'de inversión. Pueden estar equivocadas; decide con tu propio análisis.</div>']
    st = sn.get("stocktwits", [])

    # --- Termómetro general ---
    rows = []
    for x in st:
        tot = x["bull"] + x["bear"]
        pb = round(x["bull"] / tot * 100) if tot else 50
        rows.append((x, tot, pb, _verdict(pb, tot)))
    nb = sum(1 for r in rows if r[3][1] == "bu")
    nr = sum(1 for r in rows if r[3][1] == "be")
    ups = sum(1 for i in news_items if i.get("action") == "mejora")
    dns = sum(1 for i in news_items if i.get("action") == "rebaja")
    total_msgs = sum(x["n"] for x in st)
    if rows:
        out.append('<div class="fg"><div class="t">🌡️ Termómetro de traders</div>'
                   f'<div class="x" style="margin-top:6px">De {len(rows)} activos analizados: <b>{nb} con ánimo alcista</b> · '
                   f'<b>{nr} bajista</b> · {len(rows) - nb - nr} divididos o sin datos.</div>'
                   f'<div class="x">Analistas (últimos 2 días): <b>{ups}</b> mejoras de calificación o precio objetivo · '
                   f'<b>{dns}</b> rebajas.</div>'
                   f'<div class="x">Base: {total_msgs} mensajes recientes de StockTwits.</div></div>')

    # --- Miedo y codicia ---
    f = sn.get("fng")
    if f:
        parts = "".join(f'<div class="fp"><span>{e(p["name"])}</span><b>{p["score"]}</b><small>{e(p["rating"])}</small></div>'
                        for p in f.get("parts", []))
        out.append(f'<div class="fg"><div class="t">😨🤑 Miedo y Codicia (CNN): <b>{f["score"]}/100 · {e(f["rating"])}</b></div>'
                   f'<div class="bar"><i style="left:{f["score"]}%"></i></div>'
                   f'<div class="x">Ayer {f["prev"]} · hace 1 semana {f["week"]} · hace 1 mes {f.get("month", "-")} · '
                   f'0 = miedo extremo, 100 = codicia extrema</div>'
                   f'{"<div class=fpg>" + parts + "</div>" if parts else ""}</div>')

    # --- Lo más comentado ---
    tr = sn.get("trending") or []
    if tr:
        chips = "".join(f'<span class="tag">{e(t["symbol"])}</span>' for t in tr)
        out.append(f'<h2>🔥 Lo más comentado ahora (StockTwits)</h2><div class="m" style="margin:0 4px 6px">{chips}</div>')

    # --- Por activo ---
    if st:
        out.append("<h2>💬 Ánimo de los traders por activo</h2>")
        for x, tot, pb, (verdict, kind) in sorted(rows, key=lambda r: -r[1]):
            if tot:
                bar = (f'<div class="sb"><u style="width:{pb}%"></u><s style="width:{100 - pb}%"></s></div>')
                line = f'<b>{pb}% alcista</b> · {100 - pb}% bajista — {verdict} <span class="x">({tot} opinan de {x["n"]} mensajes)</span>'
            else:
                bar, line = "", "Sin opiniones etiquetadas en la muestra"
            msgs = "".join(f'<div class="q">{"🟢" if m["side"] == "alcista" else "🔴"} “{e(m.get("text_es", m["text"]))[:200]}” — @{e(m["user"])}</div>'
                           for m in x["msgs"])
            out.append(f'<div class="st"><div class="t">{e(x["name"])} <small style="color:var(--mut)">({e(x["symbol"])})</small></div>{bar}'
                       f'<div class="x" style="color:var(--tx)">{line}</div>{msgs}</div>')
        out.append('<div class="x" style="margin-bottom:8px">Solo cuentan los mensajes que el autor etiquetó como alcista o bajista '
                   '(una minoría). Sirve como termómetro del ánimo, no como señal de compra o venta.</div>')
    out.append("<h2>📰 Analistas y pronósticos</h2>")
    return "".join(out)
