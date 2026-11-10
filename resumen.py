"""Resumen del día: lo que conviene mirar para anticipar movimientos (reglas simples, sin recomendaciones)."""
import html
from datetime import datetime, timedelta

import agenda

e = html.escape


def _pct(p):
    s = f"{abs(p):.2f}".replace(".", ",")
    return f'<span class="{"up2" if p >= 0 else "dn"}">{"▲" if p >= 0 else "▼"} {s}%</span>'


def _num(v, dec):
    return f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _chip(m):
    return (f'<span class="rc" data-sym="{e(m["symbol"])}" data-dec="{m["dec"]}"><small>{e(m["name"])}</small> '
            f'<b>{_num(m["price"], m["dec"])}</b> {_pct(m["pct"])}</span>')


def _row(title, items):
    if not items:
        return ""
    return f'<div class="rr"><div class="rt">{title}</div><div class="rcs">{"".join(_chip(m) for m in items)}</div></div>'


def render(ag):
    mk = {m["symbol"]: m for m in ag.get("markets", [])}
    if not mk:
        return ""
    now = datetime.now(agenda.TZ)
    today = now.date()
    tomorrow = today + timedelta(days=1)

    def g(*syms):
        return [mk[s] for s in syms if s in mk]

    rows = "".join([
        _row("🇺🇸 Futuros y Nasdaq", g("NQ=F", "^NDX", "ES=F", "YM=F")),
        _row("🌏 Asia", g("^N225", "^HSI", "000001.SS")),
        _row("🌍 Europa", g("^FTSE", "^GDAXI")),
        _row("⚠️ Riesgo", g("^VIX", "^TNX", "DX-Y.NYB", "USDCLP=X")),
        _row("🪙 Oro, petróleo y cripto", g("GC=F", "CL=F", "HG=F", "BTC-USD")),
    ])

    # ---- lo clave de hoy / mañana
    clave = []
    evs = [x for x in ag.get("events", []) if x["impact"] == "High"]
    for label, day in (("Hoy", today), ("Mañana", tomorrow)):
        todays = [x for x in evs if datetime.fromtimestamp(x["ts"], agenda.TZ).date() == day
                  and (day != today or x["ts"] > now.timestamp() - 1800)]
        for x in todays[:6]:
            t = datetime.fromtimestamp(x["ts"], agenda.TZ).strftime("%H:%M")
            extra = []
            if x.get("forecast"):
                extra.append(f'previsto {e(x["forecast"])}')
            if x.get("previous"):
                extra.append(f'anterior {e(x["previous"])}')
            clave.append(f'<li><b>{label} {t}</b> · {e(x["flag"])} {e(x["title_es"])}'
                         f'{" <span class=x>(" + ", ".join(extra) + ")</span>" if extra else ""}</li>')
    for r in ag.get("earnings", []):
        d = datetime.fromisoformat(r["date"]).date()
        if d not in (today, tomorrow) or not (r.get("watch") or r["cap"] >= 200e9):
            continue
        label = "Hoy" if d == today else "Mañana"
        hora = r.get("hora") or r.get("window", "").split("–")[0] or ""
        bits = [e(r["session"])]
        if r.get("implied"):
            bits.append(f'opciones esperan ~±{str(r["implied"]).replace(".", ",")}%')
        if r.get("post") is not None:
            bits.append(f'post-market {r["post"]:+.1f}%'.replace(".", ","))
        elif r.get("pre") is not None:
            bits.append(f'pre-market {r["pre"]:+.1f}%'.replace(".", ","))
        clave.append(f'<li><b>{label} {("~" + hora) if hora else ""}</b> · 📊 {e(r["name"])} ({e(r["symbol"])}) '
                     f'<span class=x>({", ".join(bits)})</span></li>')

    # ---- lectura rápida (reglas simples y explícitas)
    lec = []
    futs = [mk[s]["pct"] for s in ("NQ=F", "ES=F", "YM=F") if s in mk]
    if futs:
        avg = sum(futs) / len(futs)
        if avg >= 0.4:
            lec.append(f"Futuros de EE.UU. con sesgo <b>alcista</b> ({str(round(avg, 2)).replace('.', ',')}% promedio).")
        elif avg <= -0.4:
            lec.append(f"Futuros de EE.UU. con sesgo <b>bajista</b> ({str(round(avg, 2)).replace('.', ',')}% promedio).")
        else:
            lec.append("Futuros de EE.UU. <b>sin dirección clara</b> (variación menor a 0,4%).")
    v = mk.get("^VIX")
    if v:
        if v["price"] >= 25:
            lec.append(f"VIX en {_num(v['price'], 1)}: <b>volatilidad alta</b>, esperan movimientos amplios.")
        elif v["price"] <= 14:
            lec.append(f"VIX en {_num(v['price'], 1)}: <b>volatilidad baja</b>; ojo con la complacencia.")
        if v["pct"] >= 8:
            lec.append("El VIX sube con fuerza (+8% o más): los operadores están comprando protección.")
    t = mk.get("^TNX")
    if t and abs(t["pct"]) >= 1.5:
        lec.append(f"Rendimiento del bono a 10 años {'subiendo' if t['pct'] > 0 else 'bajando'} "
                   f"({'+' if t['pct'] > 0 else ''}{str(round(t['pct'], 1)).replace('.', ',')}%): "
                   f"{'suele presionar a las tecnológicas' if t['pct'] > 0 else 'suele favorecer a las tecnológicas'}.")
    d = mk.get("DX-Y.NYB")
    if d and abs(d["pct"]) >= 0.5:
        lec.append(f"Dólar global {'fuerte' if d['pct'] > 0 else 'débil'} ({'+' if d['pct'] > 0 else ''}"
                   f"{str(round(d['pct'], 2)).replace('.', ',')}%): "
                   f"{'suele presionar al oro, cobre y mercados emergentes' if d['pct'] > 0 else 'suele apoyar al oro, cobre y mercados emergentes'}.")
    asia = [mk[s]["pct"] for s in ("^N225", "^HSI", "000001.SS") if s in mk]
    if asia and (max(asia) - min(asia)) >= 2.5:
        lec.append("Asia <b>muy dispersa</b> (más de 2,5 puntos entre sus bolsas): no hay un tono común.")
    fg = (ag.get("sentiment") or {}).get("fng")
    if fg:
        if fg["score"] <= 25:
            lec.append(f"Miedo y Codicia en {fg['score']} (miedo extremo): históricamente zona de rebotes, pero con alta volatilidad.")
        elif fg["score"] >= 75:
            lec.append(f"Miedo y Codicia en {fg['score']} (codicia extrema): mayor riesgo de correcciones.")
    n_hoy = sum(1 for x in evs if datetime.fromtimestamp(x["ts"], agenda.TZ).date() == today and x["ts"] > now.timestamp())
    if n_hoy:
        lec.append(f"Quedan <b>{n_hoy}</b> evento(s) de alto impacto hoy: picos de volatilidad probables alrededor de esas horas.")
    big = [r for r in ag.get("earnings", []) if r.get("implied") and r["implied"] >= 7
           and datetime.fromisoformat(r["date"]).date() in (today, tomorrow)]
    for r in big[:3]:
        lec.append(f"{e(r['symbol'])}: las opciones anticipan un movimiento aprox. de ±{str(r['implied']).replace('.', ',')}% tras resultados.")

    out = ['<div class="rsm"><div class="t">🧭 Resumen del día</div><div class="x" style="margin-top:2px">Cifras al generarse la página; la cinta de arriba se actualiza sola si el servicio en vivo está activo.</div>',
           rows]
    if clave:
        out.append('<div class="rt" style="margin-top:12px">🎯 Lo clave (hora de Chile)</div><ul class="rl">' + "".join(clave) + "</ul>")
    if lec:
        out.append('<div class="rt" style="margin-top:12px">🔎 Lectura rápida <span class="x">(reglas simples; no es una recomendación)</span></div>'
                   '<ul class="rl">' + "".join(f"<li>{x}</li>" for x in lec) + "</ul>")
    out.append("</div>")
    return "".join(out)
