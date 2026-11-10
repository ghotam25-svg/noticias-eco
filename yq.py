"""Cliente mínimo de Yahoo Finance (cookie + crumb): cotizaciones con pre/post-market y cadena de opciones."""
import sys
import threading

import requests

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}
_lock = threading.Lock()
_s = None
_crumb = None


def _session():
    global _s, _crumb
    with _lock:
        if _s is not None and _crumb:
            return _s, _crumb
        s = requests.Session()
        s.headers.update(H)
        try:
            s.get("https://fc.yahoo.com", timeout=15)  # entrega la cookie (responde 404, es normal)
            c = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15)
            c.raise_for_status()
            _s, _crumb = s, c.text
        except Exception as ex:
            print("  ! yahoo crumb:", ex, file=sys.stderr)
            return None, None
        return _s, _crumb


def quotes(symbols):
    """{símbolo: dict de Yahoo} (precio, % del día, marketState, pre/post-market, earningsTimestamp...)."""
    s, crumb = _session()
    if not s or not symbols:
        return {}
    out = {}
    for i in range(0, len(symbols), 40):
        chunk = symbols[i:i + 40]
        try:
            r = s.get("https://query1.finance.yahoo.com/v7/finance/quote",
                      params={"symbols": ",".join(chunk), "crumb": crumb}, timeout=20)
            r.raise_for_status()
            for x in r.json()["quoteResponse"]["result"]:
                out[x["symbol"]] = x
        except Exception as ex:
            print("  ! yahoo quote:", ex, file=sys.stderr)
    return out


def implied_move(sym, report_day_ts):
    """Movimiento esperado (%) según opciones: straddle ATM del primer vencimiento posterior al reporte.
    Aproximado: depende de que haya cotización de opciones al momento de la consulta."""
    s, crumb = _session()
    if not s:
        return None
    try:
        r = s.get(f"https://query1.finance.yahoo.com/v7/finance/options/{sym}", params={"crumb": crumb}, timeout=20)
        r.raise_for_status()
        o = r.json()["optionChain"]["result"][0]
        px = o["quote"]["regularMarketPrice"]
        exps = o["expirationDates"]
        ex = next((e for e in exps if e >= report_day_ts + 86400 - 3600), None)
        if ex is None:
            return None
        r = s.get(f"https://query1.finance.yahoo.com/v7/finance/options/{sym}",
                  params={"crumb": crumb, "date": ex}, timeout=20)
        r.raise_for_status()
        ch = r.json()["optionChain"]["result"][0]["options"][0]
        calls = {c["strike"]: c for c in ch["calls"]}
        puts = {p["strike"]: p for p in ch["puts"]}
        both = [k for k in calls if k in puts]
        if not both:
            return None
        k = min(both, key=lambda k: abs(k - px))

        def mid(c):
            b, a = c.get("bid") or 0, c.get("ask") or 0
            return (b + a) / 2 if b > 0 and a > 0 else (c.get("lastPrice") or 0)
        st = mid(calls[k]) + mid(puts[k])
        # 0,85 x straddle: aproximación habitual del movimiento esperado (el vencimiento incluye días previos al reporte)
        return round(0.85 * st / px * 100, 1) if st and px else None
    except Exception as ex:
        print(f"  ! opciones {sym}: {ex}", file=sys.stderr)
        return None
