"""Genera los iconos de Trading News (PNG) en ../static. Ejecutar solo si se cambia el diseño."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent.parent / "static"
S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def artwork(safe=1.0):
    """Dibuja el icono sobre fondo con degradado. safe<1 reduce el dibujo (para icono 'maskable')."""
    top, bot = (24, 44, 96), (6, 12, 30)
    bg = Image.new("RGB", (S, S))
    px = bg.load()
    for y in range(S):
        for x in range(S):
            t = min(1, (x * 0.35 + y * 0.65) / S)
            px[x, y] = lerp(top, bot, t)
    img = bg.convert("RGBA")
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((S * .15, S * .35, S * .95, S * 1.1), fill=(16, 185, 129, 70))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(110)))

    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    k = safe
    def P(x, y):  # coordenadas normalizadas 0-1 -> píxeles con margen de seguridad
        return (S / 2 + (x - .5) * S * k, S / 2 + (y - .5) * S * k)
    # velas
    candles = [(.24, .62, .74, .52, .70, "dn"), (.40, .52, .66, .44, .60, "up"),
               (.56, .40, .58, .32, .50, "up"), (.72, .26, .48, .18, .40, "up")]
    for cx, hi, lo, op, cl, kind in candles:
        col = (16, 185, 129, 255) if kind == "up" else (244, 63, 94, 255)
        w = .085
        d.line([P(cx, hi - .06), P(cx, lo + .06)], fill=col, width=int(S * .02 * k))
        d.rounded_rectangle([*P(cx - w / 2, min(op, cl) - .02), *P(cx + w / 2, max(op, cl) + .02)],
                            radius=int(S * .02 * k), fill=col)
    # línea de tendencia con brillo
    pts = [P(.14, .78), P(.34, .62), P(.50, .66), P(.70, .38), P(.86, .22)]
    line = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line)
    ld.line(pts, fill=(255, 255, 255, 255), width=int(S * .045 * k), joint="curve")
    for p in (pts[0], pts[-1]):
        r = S * .03 * k
        ld.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=(255, 255, 255, 255))
    # punta de flecha
    ax, ay = pts[-1]
    ld.polygon([(ax + S * .07 * k, ay - S * .07 * k), (ax - S * .055 * k, ay - S * .035 * k),
                (ax + S * .035 * k, ay + S * .055 * k)], fill=(255, 255, 255, 255))
    halo = line.filter(ImageFilter.GaussianBlur(18))
    halo = Image.merge("RGBA", (halo.split()[0].point(lambda v: 60), halo.split()[1].point(lambda v: 255),
                                 halo.split()[2].point(lambda v: 170), halo.split()[3]))
    img = Image.alpha_composite(img, halo)
    img = Image.alpha_composite(img, layer)
    img = Image.alpha_composite(img, line)
    return img


def rounded(img, radius):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, *img.size), radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), m)
    return out


any_icon = rounded(artwork(1.0), int(S * .22))
maskable = artwork(.78)  # a sangre; el sistema aplica su propia máscara
for size in (512, 192):
    any_icon.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png")
    maskable.resize((size, size), Image.LANCZOS).save(OUT / f"icon-maskable-{size}.png")
artwork(1.0).convert("RGB").resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png")
any_icon.resize((64, 64), Image.LANCZOS).save(OUT / "favicon.png")
print("iconos generados en", OUT)
