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
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse as up
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests
from deep_translator import GoogleTranslator

OUT = Path(__file__).parent / "docs"
UA = {"User-Agent": "Mozilla/5.0 (compatible; NoticiasEco/1.0)"}
MAX_AGE = timedelta(hours=30)
PER_SECTION = 40
TZ_CL = timezone(timedelta(hours=-3))  # hora de Chile (aprox.; solo para mostrar)


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
    r"econom|mercado|bolsa|d[óo]lar|inflaci|ipc|tasa|banco|fed|empres|inversi|precio|cobre|pib|empleo|"
    r"desempleo|impuesto|reforma|presupuesto|deuda|fiscal|aranc|comercio|exporta|import|petr[óo]leo|litio|bitcoin|"
    r"utilidad|ganancia|quiebra|fusi|compra de|minera|retail|afp|pensi|sueldo|salario|"
    r"econom|market|stock|shares|inflation|rate cut|rate hike|interest rate|bank|earnings|trade|tariff|oil|jobs|"
    r"gdp|bond|treasur|yield|dollar|invest|merger|acquisition|profit|revenue|ecb|budget|debt|recession|"
    r"wall street|nasdaq|s&p|dow|crypto|ipo|layoffs|forecast|sales|ceo|guidance", re.I)
GOOD_SRC = re.compile(
    r"reuters|bloomberg|wall street journal|wsj|cnbc|financial times|marketwatch|barron|forbes|business insider|"
    r"nasdaq|la tercera|diario financiero|emol|ex-ante|america economia|américa economía|el mercurio|biobio|"
    r"cooperativa|meganoticias|the economist|associated press|ap news|bbc|ft\.com|axios|fortune|"
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
        if not d or now - d > MAX_AGE or d - now > timedelta(hours=2):
            continue
        if len(title) < 30 or JUNK.search(title):
            continue
        if (via_gnews or name == "Cooperativa") and not ECON.search(title):
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
                if it.get("title_es"):
                    cache[it["title"]] = (it["title_es"], it.get("summary_es", ""))
        except Exception:
            pass
    url = os.environ.get("PUBLISHED_JSON_URL")
    if url and not cache:
        try:
            for it in requests.get(url, timeout=15).json()["items"]:
                if it.get("title_es"):
                    cache[it["title"]] = (it["title_es"], it.get("summary_es", ""))
        except Exception:
            pass
    return cache


def translate(items):
    cache = load_cache()

    def do(text):
        for _ in range(3):
            try:
                return GoogleTranslator(source="auto", target="es").translate(text)
            except Exception:
                time.sleep(1.5)
        return text  # si falla, se deja en inglés antes que perder la noticia

    todo = []
    for it in items:
        if it["lang"] != "en":
            it["title_es"], it["summary_es"] = it["title"], it["summary"]
        elif it["title"] in cache:
            it["title_es"], it["summary_es"] = cache[it["title"]]
        else:
            todo.append(it)

    def work(it):
        it["title_es"] = do(it["title"])
        it["summary_es"] = do(it["summary"]) if it["summary"] else ""

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(work, todo))
    n = len(todo)
    print(f"  traducidas nuevas: {n}")


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
    for sec in ("chile", "mundo", "resultados"):
        sec_items = [i for i in out if i["section"] == sec]
        sec_items.sort(key=lambda i: (-score(i), -i["ts"]))
        top = sec_items[:PER_SECTION]
        top.sort(key=lambda i: -i["ts"])
        for i in top:
            i["hot"] = score(i) >= 2
        final += top
    return final


PAGE = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<meta name="theme-color" content="#0b1220">
<link rel="manifest" href="manifest.json">
<title>Noticias Económicas</title>
<style>
:root{--bg:#f4f6fa;--card:#fff;--tx:#111827;--mut:#6b7280;--ac:#0b5fff;--hot:#e11d48;--bd:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--card:#131c2e;--tx:#e8edf7;--mut:#8b97ad;--ac:#6ea0ff;--hot:#fb7185;--bd:#22304a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;background:var(--bg);padding:12px 16px 0;border-bottom:1px solid var(--bd);z-index:2}
h1{font-size:18px;margin:0 0 2px}.up{color:var(--mut);font-size:12px;margin-bottom:8px}
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
</style></head><body>
<header><h1>📰 Noticias Económicas</h1>
<div class="up">Actualizado __UPDATED__ (hora Chile) · se refresca sola cada 10 min</div>
<nav><button data-s="chile" class="on">🇨🇱 Chile (__NC__)</button><button data-s="mundo">🌎 EE.UU. y mundo (__NM__)</button><button data-s="resultados">📊 Resultados Nasdaq (__NR__)</button></nav></header>
<main>__BODY__</main>
<script>
const b=document.querySelectorAll('nav button'),s=document.querySelectorAll('.sec');
function show(k){b.forEach(x=>x.classList.toggle('on',x.dataset.s==k));s.forEach(x=>x.classList.toggle('on',x.id==k));try{localStorage.tab=k}catch(e){}}
b.forEach(x=>x.onclick=()=>{show(x.dataset.s);scrollTo(0,0)});
try{if(localStorage.tab)show(localStorage.tab)}catch(e){}
</script></body></html>"""


def ago(ts):
    mins = int((time.time() - ts) / 60)
    if mins < 60:
        return f"hace {max(mins,1)} min"
    if mins < 1440:
        return f"hace {mins//60} h"
    return f"hace {mins//1440} d"


def render(items):
    body = []
    counts = {}
    for sec in ("chile", "mundo", "resultados"):
        its = [i for i in items if i["section"] == sec]
        counts[sec] = len(its)
        cards = []
        for i in its:
            e = html.escape
            summ = f'<div class="s">{e(i["summary_es"])}</div>' if i.get("summary_es") else ""
            tag = '<span class="tag">traducido del inglés</span>' if i["lang"] == "en" else ""
            cards.append(
                f'<a class="n{" hot" if i.get("hot") else ""}" href="{e(i["link"])}" target="_blank" rel="noopener">'
                f'<div class="t">{e(i["title_es"])}</div>{summ}'
                f'<div class="m"><span class="src">{e(i["source"])}</span><span>{ago(i["ts"])}</span>{tag}</div></a>'
            )
        body.append(f'<section class="sec{" on" if sec == "chile" else ""}" id="{sec}">'
                    + ("".join(cards) or '<div class="empty">Sin noticias nuevas por ahora.</div>') + "</section>")
    now = datetime.now(TZ_CL).strftime("%d-%m %H:%M")
    return (PAGE.replace("__UPDATED__", now).replace("__BODY__", "\n".join(body))
            .replace("__NC__", str(counts["chile"])).replace("__NM__", str(counts["mundo"]))
            .replace("__NR__", str(counts["resultados"])))


def run_once():
    print(datetime.now().strftime("[%H:%M:%S] actualizando..."))
    items = collect()
    translate(items)
    OUT.mkdir(exist_ok=True)
    (OUT / "news.json").write_text(
        json.dumps({"generated": time.time(), "items": items}, ensure_ascii=False), encoding="utf-8")
    (OUT / "index.html").write_text(render(items), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps({
        "name": "Noticias Económicas", "short_name": "Noticias", "start_url": "./",
        "display": "standalone", "background_color": "#0b1220", "theme_color": "#0b1220",
        "icons": []}), encoding="utf-8")
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
