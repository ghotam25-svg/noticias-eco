#!/usr/bin/env python3
"""Noticias económicas (Chile + EE.UU. + mundo + resultados Nasdaq).

Descarga RSS, filtra, traduce al español lo que viene en inglés y genera una
página web liviana (docs/index.html + docs/news.json) pensada para el celular.

Uso:
    python noticias.py            # una pasada (ideal para programador/GitHub Actions)
    python noticias.py --loop     # repite cada 10 min en tu PC
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse as up
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests

import agenda
import traders
from deep_translator import GoogleTranslator, MyMemoryTranslator

OUT = Path(__file__).parent / "docs"
UA = {"User-Agent": "Mozilla/5.0 (compatible; NoticiasEco/1.0)"}
MAX_AGE = timedelta(hours=30)
PER_SECTION = 40
TZ_CL = agenda.TZ  # hora de Chile


def gnews(q, lang="es"):
    """Google News RSS: sirve para fuentes que bloquean el RSS directo."""
    if lang == "es":
        p = "hl=es-419&gl=CL&ceid=CL:es-419"
    else:
        p = "hl=en-US&gl=US&ceid=US:en"
    return "https://news.google.com/rss/search?q=" + up.quote(q) + "&" + p


# (sección, nombre mostrado, url, idioma, fuente_google_news)
SOURCES = [
    # --- Chile ---
    ("chile", "Diario Financiero", gnews("site:df.cl when:1d"), "es", True),
    ("chile", "Emol", gnews("site:emol.com economía when:1d"), "es", True),
    ("chile", "Meganoticias", gnews("site:meganoticias.cl economía when:1d"), "es", True),
    ("chile", "La Tercera", gnews("site:latercera.com pulso economía when:1d"), "es", True),
    ("chile", "BioBioChile", gnews("site:biobiochile.cl economía when:1d"), "es", True),
    ("chile", "Cooperativa", "https://www.cooperativa.cl/noticias/site/tax/port/all/rss_3___1.xml", "es", False),
    ("chile", "Chile: dólar, IPC, Banco Central",
     gnews("(dólar OR IPC OR \"Banco Central\" OR IPSA OR cobre) Chile when:1d"), "es", True),
    # --- EE.UU. / mundo ---
    ("mundo", "Bloomberg", "https://feeds.bloomberg.com/markets/news.rss", "en", False),
    ("mundo", "Bloomberg Economía", "https://feeds.bloomberg.com/economics/news.rss", "en", False),
    ("mundo", "CNBC", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "en", False),
    ("mundo", "MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "en", False),
    ("mundo", "Nasdaq.com", "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "en", False),
    ("mundo", "Financial Times", "https://www.ft.com/markets?format=rss", "en", False),
    ("mundo", "BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "en", False),
    ("mundo", "Investing.com", "https://www.investing.com/rss/news_25.rss", "en", False),
    ("mundo", "Reuters", gnews("site:reuters.com (economy OR markets OR Fed) when:1d", "en"), "en", True),
    ("mundo", "Wall Street Journal", gnews("site:wsj.com (economy OR markets OR Fed) when:1d", "en"), "en", True),
    ("mundo", "Fed / inflación / empleo EE.UU.",
     gnews("(Fed OR \"Federal Reserve\" OR CPI OR \"jobs report\" OR GDP OR tariffs) when:1d", "en"), "en", True),
    # --- Inteligencia artificial ---
    ("ia", "TechCrunch IA", "https://techcrunch.com/category/artificial-intelligence/feed/", "en", False),
    ("ia", "The Verge IA", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "en", False),
    ("ia", "MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed", "en", False),
    ("ia", "Ars Technica IA", "https://arstechnica.com/ai/feed/", "en", False),
    ("ia", "OpenAI", "https://openai.com/news/rss.xml", "en", False),
    ("ia", "Google IA", "https://blog.google/technology/ai/rss/", "en", False),
    ("ia", "IA: OpenAI, Anthropic, Google, Nvidia",
     gnews("(OpenAI OR Anthropic OR Gemini OR \"Claude\" OR Nvidia OR \"artificial intelligence\") when:1d", "en"), "en", True),
    # --- Opiniones de analistas y traders ---
    ("traders", "FXStreet", "https://www.fxstreet.com/rss/analysis", "en", False),
    ("traders", "Analistas: mejoras y rebajas",
     gnews("(upgrade OR downgrade OR \"price target\" OR \"initiates coverage\") "
           "(Nasdaq OR Nvidia OR Apple OR Microsoft OR Tesla OR Amazon OR Alphabet OR Meta OR Broadcom) when:2d", "en"), "en", True),
    # --- Resultados de empresas Nasdaq ---
    ("resultados", "Nasdaq.com", "https://www.nasdaq.com/feed/rssoutbound?category=Earnings", "en", False),
    ("resultados", "CNBC Earnings", "https://www.cnbc.com/id/15839135/device/rss/rss.html", "en", False),
    ("resultados", "Resultados trimestrales",
     gnews("(\"earnings\" OR \"quarterly results\" OR \"beats estimates\" OR \"misses estimates\") "
           "(Nasdaq OR Apple OR Microsoft OR Nvidia OR Amazon OR Alphabet OR Meta OR Tesla) when:1d", "en"), "en", True),
]

# Titulares que no son noticias (páginas de sección, formularios, calendarios...)
JUNK = re.compile(
    r"formulario|suscripci|calendar|stock price, news, quote|portada|^\d{2}-\d{2}-\d{4}|"
    r"stock price|precio de acciones|cotizaci[óo]n e historial|price today|newsletter|horóscopo|horoscopo|sorteo|loto|cartelera|\bquote and history\b",
    re.I,
)
# Palabras que suben la relevancia
HOT = re.compile(
    r"fed\b|reserva federal|banco central|tasa|inflaci|ipc|dólar|dolar|cobre|ipsa|pib|gdp|aranceles|tariff|"
    r"recesi|desempleo|jobs|payroll|cpi|bolsa|wall street|nasdaq|s&p|dow|petróleo|oil|opec|bitcoin|"
    r"earnings|resultados|utilidades|ganancias|guidance|nvidia|apple|microsoft|amazon|alphabet|meta\b|tesla|"
    r"fusión|adquisi|merger|acquisition|quiebra|bankruptcy|ecb|bce|china|trump|powell|codelco|sqm|imacec",
    re.I,
)
ECON = re.compile(
    r"\b(?:econom|mercado|bolsa|d[óo]lar|inflaci|ipc\b|tasas?\b|banco|\bfed\b|empresa|inversi[óo]n|inversionista|"
    r"precios?\b|cobre\b|pib\b|empleo|desempleo|impuesto|reforma tributaria|presupuesto|deuda|fiscal|aranc|comercio|"
    r"exportaci|importaci|petr[óo]leo|litio|bitcoin|utilidades|ganancias|quiebra|fusi[óo]n|minera|retail|afp\b|"
    r"pensiones|sueldo|salario|imacec|ipsa|codelco|sqm|"
    r"market|stocks?\b|shares|inflation|rate cut|rate hike|interest rate|bank|earnings|trade\b|tariff|oil\b|jobs|"
    r"gdp|bonds?\b|treasur|yield|dollar|invest(?:or|ors|ment|ments)\b|merger|acquisition|profit|revenue|ecb\b|budget|"
    r"debt|recession|wall street|nasdaq|s&p|dow\b|crypto|ipo\b|layoffs|forecast|guidance)", re.I)
GOOD_SRC = re.compile(
    r"reuters|bloomberg|wall street journal|wsj|cnbc|financial times|marketwatch|barron|forbes|business insider|"
    r"nasdaq|la tercera|diario financiero|emol|ex-ante|america economia|américa economía|el mercurio|biobio|"
    r"cooperativa|meganoticias|the economist|associated press|\bap news|bbc|ft\.com|axios|fortune|"
    r"el dínamo|el economista|expansión|infobae|el país|cnn|t13|24horas|pauta|elmostrador|ciper|"
    r"investopedia|the motley fool|stockstory|financialcontent|globe newswire|business wire|pr newswire", re.I)
BAD_SRC = re.compile(r"tradingview|moomoo|opening bell|stocktwits|marketbeat|stockanalysis|yahoo finance uk|"
                     r"investing\.com|seeking alpha|zacks|benzinga", re.I)
EARN = re.compile(r"earnings|quarterly|results|resultados|profit|revenue|eps|beats|misses|guidance|utilidad|ganancia", re.I)


def clean(txt):
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt or ""))
    return re.sub(r"\s+", " ", txt).strip()


def parse_date(e):
    for k in ("published", "updated"):
        v = e.get(k)
        if v:
            try:
                d = parsedate_to_datetime(v)
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def fetch_source(section, name, url, lang, via_gnews):
    items = []
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except Exception as ex:
        print(f"  ! {name}: {ex}", file=sys.stderr)
        return items
    now = datetime.now(timezone.utc)
    for e in feed.entries:
        title = clean(e.get("title"))
        pub = None
        if via_gnews:
            src = e.get("source", {}).get("title") if isinstance(e.get("source"), dict) else None
            pub = src
            suffix = f" - {src}" if src else ""
            if suffix and title.endswith(suffix):
                title = title[: -len(suffix)]
            # En consultas por tema, la fuente real es la que informa Google.
            shown = src or name
            if name.startswith(("Chile:", "Fed /", "Resultados")):
                pass
            else:
                # consultas site:… → forzamos el nombre de la fuente pedida
                shown = name
        else:
            shown = name
        d = parse_date(e)
        if not d or now - d > (timedelta(hours=60) if section in ("ia", "traders") else MAX_AGE) or d - now > timedelta(hours=2):
            continue
        if len(title) < 30 or JUNK.search(title):
            continue
        if (via_gnews and section not in ("ia", "traders") or name == "Cooperativa") and not ECON.search(title):
            continue
        if via_gnews and (BAD_SRC.search(shown) or not GOOD_SRC.search(shown)):
            continue
        summary = "" if via_gnews else clean(e.get("summary"))
        if summary.lower().startswith(title.lower()[:40]):
            summary = ""
        items.append({
            "section": section, "source": shown, "lang": lang,
            "title": title, "summary": summary[:220],
            "link": e.get("link"), "ts": d.timestamp(),
        })
    print(f"  {name}: {len(items)}")
    return items


def load_cache():
    """Reutiliza traducciones previas (archivo local o el sitio ya publicado)."""
    cache = {}
    paths = [OUT / "news.json"]
    for p in paths:
        try:
            for it in json.loads(p.read_text(encoding="utf-8"))["items"]:
                if it.get("title_es") and not it.get("failed"):
                    cache[it["title"]] = (it["title_es"], it.get("summary_es", ""))
        except Exception:
            pass
    url = os.environ.get("PUBLISHED_JSON_URL")
    if url and not cache:
        try:
            for it in requests.get(url, timeout=15).json()["items"]:
                if it.get("title_es") and not it.get("failed"):
                    cache[it["title"]] = (it["title_es"], it.get("summary_es", ""))
        except Exception:
            pass
    return cache


SEP = chr(10) + "§§" + chr(10)


def _gtx(text):
    """Endpoint público de Google Translate (distinto al que usa deep_translator)."""
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": "es", "dt": "t", "q": text},
        headers=UA, timeout=25)
    r.raise_for_status()
    return "".join(seg[0] for seg in r.json()[0] if seg[0])


def _single(text):
    """Un texto: prueba varios motores; devuelve None si todos fallan."""
    for fn in (
        _gtx,
        lambda t: GoogleTranslator(source="auto", target="es").translate(t),
        lambda t: MyMemoryTranslator(source="en-US", target="es-ES").translate(t),
    ):
        try:
            out = fn(text)
            if out and out.strip():
                return out
        except Exception as ex:
            print("  ! traducción:", type(ex).__name__, str(ex)[:80], file=sys.stderr)
        time.sleep(0.5)
    return None


def _batch(texts):
    """Traduce una lista en una sola llamada; si algo no cuadra, uno por uno."""
    try:
        out = _gtx(SEP.join(texts)).split("§§")
        out = [o.strip() for o in out]
        if len(out) == len(texts) and all(out):
            return out
    except Exception as ex:
        print("  ! lote:", type(ex).__name__, str(ex)[:80], file=sys.stderr)
    return [_single(t) for t in texts]


def translate(items):
    cache = load_cache()
    todo = []
    for it in items:
        if it["lang"] != "en":
            it["title_es"], it["summary_es"] = it["title"], it["summary"]
        elif it["title"] in cache and cache[it["title"]][0] != it["title"]:
            it["title_es"], it["summary_es"] = cache[it["title"]]
        else:
            todo.append(it)
    ok = 0
    for i in range(0, len(todo), 12):
        chunk = todo[i:i + 12]
        titles = _batch([c["title"] for c in chunk])
        sums = _batch([c["summary"] or "-" for c in chunk])
        for c, t, sm in zip(chunk, titles, sums):
            c["title_es"] = t or c["title"]
            c["summary_es"] = "" if not c["summary"] else (sm or "")
            c["failed"] = t is None
            ok += t is not None
    print(f"  traducidas nuevas: {ok}/{len(todo)}")


def previous_notified():
    """Avisos push ya enviados (se leen del sitio publicado o del archivo local)."""
    try:
        return json.loads((OUT / "news.json").read_text(encoding="utf-8"))["agenda"]["notified"]
    except Exception:
        pass
    url = os.environ.get("PUBLISHED_JSON_URL")
    if url:
        try:
            return requests.get(url, timeout=15).json()["agenda"]["notified"]
        except Exception:
            pass
    return []


def score(it):
    txt = it["title"] + " " + it["summary"]
    s = 2 if HOT.search(txt) else 0
    if it["source"] in ("Bloomberg", "Bloomberg Economía", "Diario Financiero", "Reuters", "Wall Street Journal"):
        s += 1
    return s


def collect():
    all_items = []
    with ThreadPoolExecutor(8) as ex:
        for res in ex.map(lambda a: fetch_source(*a), SOURCES):
            all_items += res
    # dedupe por título normalizado
    seen, out = set(), []
    for it in sorted(all_items, key=lambda x: -x["ts"]):
        key = re.sub(r"\W+", "", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    # En "resultados" solo lo que realmente habla de resultados
    out = [i for i in out if i["section"] != "resultados" or EARN.search(i["title"] + " " + i["summary"])]
    final = []
    for sec in ("chile", "mundo", "resultados", "ia", "traders"):
        sec_items = [i for i in out if i["section"] == sec]
        sec_items.sort(key=lambda i: (-score(i), -i["ts"]))
        top = sec_items[:PER_SECTION]
        top.sort(key=lambda i: -i["ts"])
        for i in top:
            i["hot"] = score(i) >= 2
            i["stance"] = traders.stance(i["title"] + " " + i["summary"]) if sec == "traders" else ""
        final += top
    return final


PAGE = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<meta name="theme-color" content="#0b1220">
<link rel="manifest" href="manifest.json">
<link rel="icon" href="favicon.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Trading News">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Trading News</title>
<style>
:root{--bg:#f4f6fa;--card:#fff;--tx:#111827;--mut:#6b7280;--ac:#0b5fff;--hot:#e11d48;--bd:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--card:#131c2e;--tx:#e8edf7;--mut:#8b97ad;--ac:#6ea0ff;--hot:#fb7185;--bd:#22304a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;background:var(--bg);padding:12px 16px 0;border-bottom:1px solid var(--bd);z-index:2}
h1{font-size:18px;margin:0 0 2px}.top{display:flex;justify-content:space-between;align-items:center;gap:8px}h1 img{vertical-align:-6px;border-radius:6px}
#inst{border:0;background:var(--ac);color:#fff;border-radius:999px;padding:6px 12px;font:inherit;font-size:13px;font-weight:600}
.tip{max-width:720px;margin:10px auto 0;padding:0 16px;font-size:13px}.tip div{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:10px 14px}
.up{color:var(--mut);font-size:12px;margin-bottom:8px}
nav{display:flex;gap:6px;overflow-x:auto;padding-bottom:10px}
nav button{flex:1;white-space:nowrap;border:1px solid var(--bd);background:var(--card);color:var(--tx);padding:8px 12px;border-radius:999px;font:inherit;font-size:14px}
nav button.on{background:var(--ac);color:#fff;border-color:var(--ac)}
main{padding:12px 16px 40px;max-width:720px;margin:auto}
.sec{display:none}.sec.on{display:block}
a.n{display:block;background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;margin-bottom:10px;text-decoration:none;color:inherit}
a.n.hot{border-left:4px solid var(--hot)}
.t{font-weight:600}.s{color:var(--mut);font-size:14px;margin-top:4px}
.m{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;font-size:12px;color:var(--mut)}
.src{color:var(--ac);font-weight:600}.tag{border:1px solid var(--bd);border-radius:6px;padding:0 6px}
.empty{color:var(--mut);text-align:center;padding:30px 0}
.alert{max-width:720px;margin:12px auto 0;padding:0 16px}
.alert div{background:#fef3c7;color:#78350f;border:1px solid #f59e0b;border-radius:12px;padding:10px 14px;margin-bottom:6px;font-size:14px}
.alert b{color:#b45309}
h2{font-size:14px;color:var(--mut);margin:18px 0 8px;text-transform:uppercase;letter-spacing:.04em}
.ev{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:10px 14px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start}
.ev.hi{border-left:4px solid var(--hot)}.ev.md{border-left:4px solid #f59e0b}
.ev .h{min-width:48px;font-weight:700;font-variant-numeric:tabular-nums}
.ev .x{font-size:12px;color:var(--mut);margin-top:2px}
.tag.bu{color:#16a34a;border-color:#16a34a}.tag.be{color:#dc2626;border-color:#dc2626}
.warn{font-size:12px;color:var(--mut);border:1px dashed var(--bd);border-radius:10px;padding:8px 10px;margin-bottom:10px}
.fg{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;margin-bottom:10px}
.bar{height:10px;border-radius:6px;background:linear-gradient(90deg,#dc2626,#f59e0b,#16a34a);position:relative;margin:8px 0}
.bar i{position:absolute;top:-4px;width:4px;height:18px;background:var(--tx);border-radius:2px;transform:translateX(-2px)}
.st{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:10px 14px;margin-bottom:8px}
.sb{display:flex;height:8px;border-radius:5px;overflow:hidden;margin:6px 0;background:var(--bd)}.sb u{background:#16a34a}.sb s{background:#dc2626}
.q{font-size:13px;color:var(--mut);margin-top:4px}
.tk{overflow:hidden;white-space:nowrap;margin:0 -16px;border-top:1px solid var(--bd);background:var(--card);touch-action:pan-y}
.tk-in{display:inline-flex;gap:26px;padding:7px 13px;animation:tk 45s linear infinite;will-change:transform}
.tk:hover .tk-in,.tk:active .tk-in{animation-play-state:paused}
.tk span.i{font-size:13px;font-variant-numeric:tabular-nums}.tk small{color:var(--mut);margin-right:5px}
.tk b{margin-right:4px}.up2{color:#16a34a}.dn{color:#dc2626}
@keyframes tk{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@media(prefers-reduced-motion:reduce){.tk{overflow-x:auto}.tk-in{animation:none}}
.hrs{max-width:720px;margin:8px auto 0;padding:0 16px;display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px}
.hrs div{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:8px 10px}
.hrs small{color:var(--mut);display:block;font-size:11px}
.on-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;background:#16a34a}.off-dot{background:#9ca3af}
</style></head><body>
<header><div class="top"><h1><img src="favicon.png" alt="" width="26" height="26"> Trading News</h1><button id="inst" hidden>📲 Instalar</button></div>
<div class="up">Actualizado __UPDATED__ (hora Chile) · se refresca sola cada 10 min</div>
<nav><button data-s="agenda" class="on">📅 Agenda</button><button data-s="chile">🇨🇱 Chile (__NC__)</button><button data-s="mundo">🌎 EE.UU. y mundo (__NM__)</button><button data-s="resultados">📊 Resultados (__NR__)</button><button data-s="traders">🧠 Traders (__NT__)</button><button data-s="ia">🤖 IA (__NI__)</button></nav>__MKT__</header>
<div class="tip" id="tip" hidden><div>📲 Para instalar en iPhone: toca <b>Compartir</b> ⬆️ y luego <b>Agregar a pantalla de inicio</b>.</div></div>
<div class="hrs" id="hrs"></div>
__ALERT__
<main>__BODY__</main>
<script>
const b=document.querySelectorAll('nav button'),s=document.querySelectorAll('.sec');
function show(k){b.forEach(x=>x.classList.toggle('on',x.dataset.s==k));s.forEach(x=>x.classList.toggle('on',x.id==k));try{localStorage.tab=k}catch(e){}}
b.forEach(x=>x.onclick=()=>{show(x.dataset.s);scrollTo(0,0)});
try{if(localStorage.tab)show(localStorage.tab)}catch(e){}
/* Horarios de bolsa en vivo (calculados en tu celular, con zonas horarias reales) */
const MK=[{n:'Nueva York (NYSE/Nasdaq)',tz:'America/New_York',o:[9,30],c:[16,0],f:'🇺🇸'},{n:'Londres (LSE)',tz:'Europe/London',o:[8,0],c:[16,30],f:'🇬🇧'}];
function parts(tz,d){const p={};new Intl.DateTimeFormat('en-US',{timeZone:tz,hour12:false,weekday:'short',hour:'2-digit',minute:'2-digit',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d).forEach(x=>p[x.type]=x.value);p.h=(+p.hour)%24;p.m=+p.minute;return p}
function fmtCL(d){return new Intl.DateTimeFormat('es-CL',{timeZone:'America/Santiago',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)}
function atLocal(tz,y,mo,da,h,mi){/* instante UTC para una hora local de la plaza */let g=new Date(Date.UTC(y,mo-1,da,h,mi));for(let i=0;i<2;i++){const p=parts(tz,g);const dif=(Date.UTC(y,mo-1,da,h,mi)-Date.UTC(+p.year,+p.month-1,+p.day,p.h,p.m));g=new Date(g.getTime()+dif)}return g}
function hrs(){const now=new Date();let out='';MK.forEach(m=>{const p=parts(m.tz,now),wd=!['Sat','Sun'].includes(p.weekday),mins=p.h*60+p.m,o=m.o[0]*60+m.o[1],c=m.c[0]*60+m.c[1],open=wd&&mins>=o&&mins<c;
const op=atLocal(m.tz,+p.year,+p.month,+p.day,m.o[0],m.o[1]),cl=atLocal(m.tz,+p.year,+p.month,+p.day,m.c[0],m.c[1]);
let est;if(open){const r=Math.round((cl-now)/60000);est='cierra en '+Math.floor(r/60)+' h '+r%60+' min'}else if(wd&&mins<o){const r=Math.round((op-now)/60000);est='abre en '+Math.floor(r/60)+' h '+r%60+' min'}else est='abre el próximo día hábil';
out+='<div><small>'+m.f+' '+m.n+'</small><span class="on-dot'+(open?'':' off-dot')+'"></span><b>'+(open?'ABIERTO':'CERRADO')+'</b> · '+est+'<small>Allá son las '+String(p.h).padStart(2,'0')+':'+String(p.m).padStart(2,'0')+' · Horario en Chile: '+fmtCL(op)+' a '+fmtCL(cl)+'</small></div>'});
document.getElementById('hrs').innerHTML=out}
hrs();setInterval(hrs,30000);
/* Instalación como app */
let dp=null;const inst=document.getElementById('inst'),tip=document.getElementById('tip');
const standalone=matchMedia('(display-mode: standalone)').matches||navigator.standalone;
addEventListener('beforeinstallprompt',e=>{e.preventDefault();dp=e;if(!standalone)inst.hidden=false});
inst.onclick=async()=>{if(dp){dp.prompt();await dp.userChoice;dp=null;inst.hidden=true}};
addEventListener('appinstalled',()=>{inst.hidden=true;tip.hidden=true});
if(!standalone&&/iphone|ipad|ipod/i.test(navigator.userAgent))tip.hidden=false;
if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js').catch(()=>{});
</script></body></html>"""


def ago(ts):
    mins = int((time.time() - ts) / 60)
    if mins < 60:
        return f"hace {max(mins,1)} min"
    if mins < 1440:
        return f"hace {mins//60} h"
    return f"hace {mins//1440} d"


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_es(d):
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]}"


def render_markets(mk):
    if not mk:
        return ""
    chips = []
    for q in mk:
        up = q["pct"] >= 0
        price = f'{q["price"]:,.{q["dec"]}f}'.replace(",", "X").replace(".", ",").replace("X", ".")
        chips.append(f'<span class="i"><small>{html.escape(q["name"])}</small><b>{price}</b>'
                     f'<span class="{"up2" if up else "dn"}">{"▲" if up else "▼"} {abs(q["pct"]):.2f}%</span></span>')
    row = "".join(chips)
    return f'<div class="tk" aria-label="Indicadores de mercado"><div class="tk-in">{row}{row}</div></div>'


def render_sentiment(sn):
    e = html.escape
    out = ['<div class="warn">⚠️ Son opiniones de terceros (analistas y usuarios de StockTwits), no recomendaciones de inversión. '
           'Pueden estar equivocadas; decide con tu propio análisis.</div>']
    f = sn.get("fng")
    if f:
        out.append(f'<div class="fg"><div class="t">Índice Miedo y Codicia (CNN): <b>{f["score"]}/100 · {e(f["rating"])}</b></div>'
                   f'<div class="bar"><i style="left:{f["score"]}%"></i></div>'
                   f'<div class="x">Ayer: {f["prev"]} · Hace 1 semana: {f["week"]} · 0 = miedo extremo · 100 = codicia extrema</div></div>')
    if sn.get("stocktwits"):
        out.append("<h2>💬 Qué dicen los traders en StockTwits</h2>")
        for x in sn["stocktwits"]:
            tot = x["bull"] + x["bear"]
            if tot:
                pb = round(x["bull"] / tot * 100)
                verdict = "mayoría alcista 🟢" if pb >= 60 else ("mayoría bajista 🔴" if pb <= 40 else "dividido ⚪")
                bar = f'<div class="sb"><u style="width:{pb}%"></u><s style="width:{100 - pb}%"></s></div>'
                line = f'{pb}% alcista · {100 - pb}% bajista ({tot} opinan de {x["n"]} mensajes) — {verdict}'
            else:
                bar, line = "", "Sin opiniones etiquetadas en la muestra"
            msgs = "".join(f'<div class="q">{"🟢" if m["side"] == "alcista" else "🔴"} “{e(m.get("text_es", m["text"]))[:220]}” — @{e(m["user"])}</div>'
                           for m in x["msgs"])
            out.append(f'<div class="st"><div class="t">{e(x["name"])} <small style="color:var(--mut)">({e(x["symbol"])})</small></div>{bar}'
                       f'<div class="x">{line}</div>{msgs}</div>')
        out.append('<div class="x" style="margin-bottom:8px">Muestra pequeña: últimos ~30 mensajes por activo; sirve como termómetro, no como señal.</div>')
    out.append("<h2>📰 Análisis y calificaciones de analistas</h2>")
    return "".join(out)


def render_agenda(ag):
    e = html.escape
    now = datetime.now(TZ_CL)
    today = now.date()
    alerts, parts = [], []
    # --- eventos macro, agrupados por día (hora Chile) ---
    days = {}
    for ev in ag.get("events", []):
        d = datetime.fromtimestamp(ev["ts"], TZ_CL)
        days.setdefault(d.date(), []).append((d, ev))
        mins = (ev["ts"] - time.time()) / 60
        if ev["impact"] == "High" and 0 < mins <= 24 * 60:
            alerts.append(f'🔴 <b>{e(ev["flag"])} {e(ev["title_es"])}</b> · {"hoy" if d.date() == today else "mañana"} {d:%H:%M}')
    parts.append("<h2>📅 Calendario económico (hora de Chile)</h2>")
    for day in sorted(days):
        parts.append(f"<h2>{fecha_es(day)}</h2>")
        for d, ev in days[day]:
            cls = "hi" if ev["impact"] == "High" else "md"
            extra = " · ".join(x for x in (f'Previsto: {ev["forecast"]}' if ev["forecast"] else "",
                                           f'Anterior: {ev["previous"]}' if ev["previous"] else "") if x)
            parts.append(f'<div class="ev {cls}"><div class="h">{d:%H:%M}</div><div><div class="t">{e(ev["flag"])} '
                         f'{e(ev["title_es"])}</div><div class="x">{"Impacto alto" if cls == "hi" else "Impacto medio"} · '
                         f'{e(ev["country"])}{(" · " + e(extra)) if extra else ""}</div></div></div>')
    if not days:
        parts.append('<div class="empty">Sin eventos próximos.</div>')
    # --- resultados de grandes empresas ---
    parts.append("<h2>📊 Entrega de resultados · grandes empresas</h2>"
                 '<div class="x" style="margin:-4px 0 8px;color:var(--mut)">La hora es la ventana típica según si reportan antes de la apertura '
                 'o después del cierre; la empresa confirma la hora exacta. Índices según su composición conocida.</div>')
    by = {}
    for q in ag.get("earnings", []):
        by.setdefault(q["date"], []).append(q)
    for ds in sorted(by):
        day = datetime.fromisoformat(ds).date()
        parts.append(f"<h2>{fecha_es(day)}</h2>")
        for q in by[ds][:14]:
            cap = f'US$ {q["cap"] / 1e9:,.0f} mil millones'.replace(",", ".") if q["cap"] else ""
            eps = f' · BPA esperado {e(q["eps"])}' if q.get("eps") else ""
            star = "⭐ " if q.get("watch") else ""
            hora = f' · 🕒 ~{q["window"]} hora Chile' if q.get("window") else ""
            idx = f'<div class="x">📈 Podría mover: <b>{e(" · ".join(q["indices"]))}</b></div>' if q.get("indices") else ""
            parts.append(f'<div class="ev md"><div class="h">{e(q["symbol"])}</div><div><div class="t">{star}{e(q["name"])}</div>'
                         f'<div class="x">{e(q["session"])}{hora}{eps} · {cap}</div>{idx}</div></div>')
        if day - today <= timedelta(days=1):
            names = ", ".join(q["symbol"] for q in by[ds] if q.get("watch"))[:80]
            if names:
                alerts.append(f'📊 <b>Resultados {"hoy" if day == today else "mañana"}:</b> {e(names)}')
    if not by:
        parts.append('<div class="empty">Sin resultados programados.</div>')
    alert_html = ('<div class="alert">' + "".join(f"<div>{a}</div>" for a in alerts[:6]) + "</div>") if alerts else ""
    return '<section class="sec on" id="agenda">' + "".join(parts) + "</section>", alert_html


def render(items, agenda):
    body = []
    counts = {}
    ag_html, alert_html = render_agenda(agenda)
    body.append(ag_html)
    for sec in ("chile", "mundo", "resultados", "ia", "traders"):
        its = [i for i in items if i["section"] == sec]
        counts[sec] = len(its)
        cards = []
        for i in its:
            e = html.escape
            summ = f'<div class="s">{e(i["summary_es"])}</div>' if i.get("summary_es") else ""
            tag = '<span class="tag">traducido del inglés</span>' if i["lang"] == "en" else ""
            tag += {"alcista": '<span class="tag bu">🟢 Tono alcista</span>', "bajista": '<span class="tag be">🔴 Tono bajista</span>',
                    "neutral": '<span class="tag">⚪ Neutral</span>'}.get(i.get("stance", ""), "")
            cards.append(
                f'<a class="n{" hot" if i.get("hot") else ""}" href="{e(i["link"])}" target="_blank" rel="noopener">'
                f'<div class="t">{e(i["title_es"])}</div>{summ}'
                f'<div class="m"><span class="src">{e(i["source"])}</span><span>{ago(i["ts"])}</span>{tag}</div></a>'
            )
        body.append(f'<section class="sec" id="{sec}">' + (render_sentiment(agenda.get("sentiment", {})) if sec == "traders" else "")
                    + ("".join(cards) or '<div class="empty">Sin noticias nuevas por ahora.</div>') + "</section>")
    now = datetime.now(TZ_CL).strftime("%d-%m %H:%M")
    return (PAGE.replace("__UPDATED__", now).replace("__BODY__", "\n".join(body))
            .replace("__NC__", str(counts["chile"])).replace("__NM__", str(counts["mundo"]))
            .replace("__NR__", str(counts["resultados"])).replace("__NI__", str(counts["ia"])).replace("__NT__", str(counts["traders"]))
            .replace("__ALERT__", alert_html).replace("__MKT__", render_markets(agenda.get("markets", []))))


def run_once():
    print(datetime.now().strftime("[%H:%M:%S] actualizando..."))
    items = collect()
    translate(items)
    ag = agenda.build(lambda ts: _batch(ts))
    ag["sentiment"] = traders.sentiment(lambda ts: _batch(ts))
    ag["notified"] = agenda.notify(ag, previous_notified())
    OUT.mkdir(exist_ok=True)
    (OUT / "news.json").write_text(
        json.dumps({"generated": time.time(), "items": items, "agenda": ag}, ensure_ascii=False), encoding="utf-8")
    (OUT / "index.html").write_text(render(items, ag), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps({
        "id": "./", "name": "Trading News", "short_name": "Trading News",
        "description": "Noticias económicas, agenda de resultados e indicadores en tiempo real",
        "lang": "es", "start_url": "./", "scope": "./", "display": "standalone", "orientation": "portrait",
        "background_color": "#0b1220", "theme_color": "#0b1220",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "icon-maskable-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
        ensure_ascii=False), encoding="utf-8")
    for f in (Path(__file__).parent / "static").glob("*"):
        shutil.copy(f, OUT / f.name)
    print(f"  listo: {len(items)} noticias en {OUT / 'index.html'}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="repetir cada 10 minutos")
    ap.add_argument("--minutos", type=int, default=10)
    a = ap.parse_args()
    if not a.loop:
        run_once()
    else:
        while True:
            try:
                run_once()
            except Exception as ex:
                print("error:", ex, file=sys.stderr)
            time.sleep(a.minutos * 60)
