"""Agenda: calendario económico (ForexFactory) + fechas de resultados de grandes empresas Nasdaq."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

import yq

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Santiago")
except Exception:  # sin tzdata
    TZ = timezone(timedelta(hours=-3))

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}
FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
FLAG = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵", "CNY": "🇨🇳", "AUD": "🇦🇺", "CAD": "🇨🇦",
        "CHF": "🇨🇭", "NZD": "🇳🇿"}
# Grandes del Nasdaq que siempre queremos ver
WATCH = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO", "NFLX", "COST", "AMD", "ADBE",
    "QCOM", "INTC", "CSCO", "PEP", "TMUS", "AMAT", "INTU", "MU", "ASML", "PANW", "ARM", "PYPL", "SBUX",
    "MRVL", "LRCX", "KLAC", "CDNS", "SNPS", "ABNB", "BKNG", "MELI", "CRWD", "MDLZ", "ADP", "GILD", "AMGN",
}
MIN_CAP = 100e9  # además, cualquier empresa de más de US$100.000 millones
NY = ZoneInfo("America/New_York") if "ZoneInfo" in globals() else None

# Composición conocida de los índices (puede cambiar con rebalanceos; es orientativa)
NDX = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO", "NFLX", "COST", "AMD", "ADBE", "QCOM",
    "INTC", "CSCO", "PEP", "TMUS", "AMAT", "INTU", "MU", "ASML", "PANW", "ARM", "PYPL", "SBUX", "MRVL", "LRCX",
    "KLAC", "CDNS", "SNPS", "ABNB", "BKNG", "MELI", "CRWD", "MDLZ", "ADP", "GILD", "AMGN", "TXN", "ISRG", "HON",
    "VRTX", "REGN", "CMCSA", "ADI", "LIN", "CSX", "ORLY", "MAR", "FTNT", "WDAY", "DDOG", "TEAM", "ROP", "PLTR",
}
DOW = {
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS", "HD", "HON", "IBM", "JNJ", "JPM",
    "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT",
}
NOT_SP = {  # extranjeras / ADR / fuera del S&P 500
    "ASML", "ARM", "MELI", "HSBC", "TM", "SAP", "SNY", "NVS", "UL", "BP", "SHEL", "TSM", "TTE", "BTI", "DEO", "SONY",
    "SMFG", "MUFG", "HDB", "IBN", "BABA", "PDD", "NVO", "AZN", "RY", "TD", "BNS", "BMO", "ENB", "SHOP", "TCEHY",
    "TME", "JD", "BIDU", "MUFG", "NTES", "SE", "CP", "CNQ", "SU", "BHP", "RIO", "VALE", "PBR", "ITUB", "LYG", "BCS",
}


def indices(sym):
    out = []
    if sym in NDX:
        out.append("Nasdaq 100 (US100)")
    if sym not in NOT_SP:
        out.append("S&P 500")
    if sym in DOW:
        out.append("Dow Jones")
    return out


def release_window(date_iso, when):
    """Ventana típica de publicación convertida a hora de Chile (la hora exacta la confirma cada empresa)."""
    if NY is None or when not in ("time-pre-market", "time-after-hours"):
        return ""
    y, m, d = map(int, date_iso.split("-"))
    a, b = ((7, 0), (9, 0)) if when == "time-pre-market" else ((16, 5), (16, 30))
    t1 = datetime(y, m, d, a[0], a[1], tzinfo=NY).astimezone(TZ)
    t2 = datetime(y, m, d, b[0], b[1], tzinfo=NY).astimezone(TZ)
    return f"{t1:%H:%M}–{t2:%H:%M}"
SESSION = {"time-pre-market": "antes de la apertura", "time-after-hours": "después del cierre",
           "time-not-supplied": "hora por confirmar"}


def _cap(s):
    try:
        return float(str(s).replace("$", "").replace(",", ""))
    except Exception:
        return 0.0


def macro_events(translate_batch):
    raw = []
    for u in FF_URLS:
        try:
            r = requests.get(u, headers=H, timeout=20)
            if r.ok:
                raw += r.json()
        except Exception as ex:
            print("  ! ForexFactory:", ex, file=sys.stderr)
    now = datetime.now(timezone.utc)
    ev = []
    for x in raw:
        if x.get("impact") not in ("High", "Medium"):
            continue
        try:
            d = datetime.fromisoformat(x["date"])
        except Exception:
            continue
        if d < now - timedelta(hours=2):
            continue
        ev.append({"ts": d.timestamp(), "country": x["country"], "flag": FLAG.get(x["country"], ""),
                   "title": x["title"], "impact": x["impact"],
                   "forecast": x.get("forecast", ""), "previous": x.get("previous", "")})
    ev.sort(key=lambda e: e["ts"])
    ev = ev[:120]
    if ev:
        tr = translate_batch([e["title"] for e in ev])
        for e, t in zip(ev, tr):
            e["title_es"] = t or e["title"]
    print(f"  calendario económico: {len(ev)} eventos")
    return ev


def _earn_day(day):
    try:
        r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": day.isoformat()},
                         headers={**H, "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"},
                         timeout=20)
        rows = r.json()["data"]["rows"] or []
    except Exception as ex:
        print(f"  ! earnings {day}: {ex}", file=sys.stderr)
        return []
    out = []
    for q in rows:
        cap = _cap(q.get("marketCap"))
        if q["symbol"] in WATCH or cap >= MIN_CAP:
            out.append({"date": day.isoformat(), "symbol": q["symbol"], "name": q.get("name", ""),
                        "session": SESSION.get(q.get("time"), "hora por confirmar"),
                        "when": q.get("time", ""), "cap": cap, "eps": q.get("epsForecast", ""),
                        "quarter": q.get("fiscalQuarterEnding", ""), "watch": q["symbol"] in WATCH,
                        "window": release_window(day.isoformat(), q.get("time")),
                        "indices": indices(q["symbol"])})
    return out


def earnings(days=10):
    today = datetime.now(timezone.utc).date()
    ds = [today + timedelta(days=k) for k in range(days) if (today + timedelta(days=k)).weekday() < 5]
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(_earn_day, ds))
    seen, out = set(), []
    for rows in res:
        for r in sorted(rows, key=lambda r: -r["cap"]):
            k = (r["name"], r["date"])  # GOOG/GOOGL son la misma empresa
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
    print(f"  resultados de empresas: {len(out)}")
    return out


# (nombre, símbolo Yahoo, decimales, grupo)  grupo: fut=futuros EE.UU., asia, eu, riesgo, mat=materias primas/cripto
MARKETS = [
    ("US100 · Futuro", "NQ=F", 1, "fut"), ("US100 · Índice", "^NDX", 1, "fut"),
    ("S&P 500 · Futuro", "ES=F", 1, "fut"), ("Dow · Futuro", "YM=F", 0, "fut"),
    ("Oro", "GC=F", 1, "mat"), ("Bitcoin", "BTC-USD", 0, "mat"), ("Petróleo WTI", "CL=F", 2, "mat"),
    ("Cobre", "HG=F", 2, "mat"), ("VIX", "^VIX", 2, "riesgo"), ("Bono 10 años EE.UU.", "^TNX", 3, "riesgo"),
    ("Índice dólar", "DX-Y.NYB", 2, "riesgo"), ("Dólar/CLP", "USDCLP=X", 1, "riesgo"),
    ("Nikkei 225", "^N225", 0, "asia"), ("Hang Seng", "^HSI", 0, "asia"), ("Shanghái", "000001.SS", 0, "asia"),
    ("FTSE 100", "^FTSE", 0, "eu"), ("DAX", "^GDAXI", 0, "eu"),
]


def _quote_chart(m):
    """Respaldo si Yahoo no entrega la cotización completa: usa el gráfico diario."""
    name, sym, dec, grp = m
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                         params={"interval": "1d", "range": "5d"}, headers=H, timeout=15)
        res = r.json()["chart"]["result"][0]
        price = res["meta"]["regularMarketPrice"]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        prev = closes[-2] if len(closes) >= 2 else res["meta"].get("chartPreviousClose")
        pct = (price - prev) / prev * 100 if prev else 0.0
        return {"name": name, "symbol": sym, "price": price, "pct": pct, "dec": dec, "grp": grp, "state": ""}
    except Exception as ex:
        print(f"  ! {sym}: {ex}", file=sys.stderr)
        return None


def markets():
    qs = yq.quotes([m[1] for m in MARKETS])
    out = []
    for m in MARKETS:
        name, sym, dec, grp = m
        x = qs.get(sym)
        if x and x.get("regularMarketPrice") is not None:
            out.append({"name": name, "symbol": sym, "price": x["regularMarketPrice"],
                        "pct": x.get("regularMarketChangePercent") or 0.0, "dec": dec, "grp": grp,
                        "state": x.get("marketState", "")})
        else:
            q = _quote_chart(m)
            if q:
                out.append(q)
    print(f"  indicadores: {len(out)}/{len(MARKETS)}")
    return out


def enrich_earnings(earn, days=5):
    """Hora referencial (Yahoo), pre/post-market y movimiento esperado por opciones para los reportes cercanos."""
    today = datetime.now(timezone.utc).date()
    targets = [r for r in earn if 0 <= (datetime.fromisoformat(r["date"]).date() - today).days <= days]
    targets = sorted(targets, key=lambda r: -r["cap"])[:16]
    if not targets:
        return
    qs = yq.quotes([r["symbol"] for r in targets])
    for r in targets:
        x = qs.get(r["symbol"]) or {}
        ts = x.get("earningsTimestamp")
        if ts and not x.get("isEarningsDateEstimate"):
            d = datetime.fromtimestamp(ts, timezone.utc).astimezone(NY).date().isoformat() if NY else None
            if d == r["date"]:
                r["ts"] = ts
                r["hora"] = datetime.fromtimestamp(ts, TZ).strftime("%H:%M")
        for k_src, k_dst in (("preMarketChangePercent", "pre"), ("postMarketChangePercent", "post")):
            if x.get(k_src) is not None:
                r[k_dst] = round(x[k_src], 2)
        if x.get("regularMarketPrice") is not None:
            r["price"] = x["regularMarketPrice"]

    def imp(r):
        day_ts = datetime.fromisoformat(r["date"]).replace(tzinfo=timezone.utc).timestamp()
        r["implied"] = yq.implied_move(r["symbol"], day_ts)
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(imp, targets))
    print(f"  resultados enriquecidos: {len(targets)} (hora {sum(1 for r in targets if 'hora' in r)}, "
          f"opciones {sum(1 for r in targets if r.get('implied'))})")


def build(translate_batch):
    earn = earnings()
    try:
        enrich_earnings(earn)
    except Exception as ex:
        print("  ! enriquecer resultados:", ex, file=sys.stderr)
    return {"events": macro_events(translate_batch), "earnings": earn, "markets": markets()}


def notify(agenda, already):
    """Aviso push (ntfy.sh) 60 min antes de eventos de alto impacto. Devuelve claves ya avisadas."""
    topic = os.environ.get("NTFY_TOPIC")
    sent = list(already)
    if not topic:
        return sent
    now = datetime.now(timezone.utc).timestamp()
    for e in agenda["events"]:
        key = f'{e["ts"]}-{e["title"]}-{e["country"]}'
        mins = (e["ts"] - now) / 60
        if e["impact"] == "High" and 0 < mins <= 60 and key not in sent:
            hora = datetime.fromtimestamp(e["ts"], TZ).strftime("%H:%M")
            body = f'{e["flag"]} {e["title_es"]} a las {hora} (Chile). Previsto: {e["forecast"] or "-"} · Anterior: {e["previous"] or "-"}'
            try:
                requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), timeout=15,
                              headers={"Title": "Evento económico en menos de 1 h".encode("utf-8"), "Priority": "high"})
                sent.append(key)
            except Exception as ex:
                print("  ! ntfy:", ex, file=sys.stderr)
    return sent[-300:]
