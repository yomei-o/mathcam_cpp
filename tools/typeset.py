"""数式の組版（Python 側）— pure/typeset.hpp の鏡。

**レイアウト（記号ごとの枠）は C++ と厳密に一致させる。** そこが学習データの正解であり、
認識側との契約だから。実寸は fontTools で TTF の hmtx / glyf をそのまま読むので、C++ 側
（stb_truetype が同じテーブルを読む）と同じ整数になる。計算は全部フォント単位の整数で行い、
画素に落とすのは最後だけ。

**ラスタ（絵の画素）は一致させない。** C++ は stb_truetype、Python は PIL（FreeType）で
輪郭の塗り方が違う。ここを一致させるには片方のラスタライザを移植することになり、得られる
ものは「同じ絵」だけで、認識器の学習には要らない。だからパリティは枠に対して取る。

  python tools/typeset.py --expr "1/2 x + sqrt(2) = 3/4" --out out.png --labels out.txt
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# em の千分率（C++ の enum と同じ値。片方だけ変えたらパリティが落ちる）
K_SUP_SHIFT = 450
K_SUP_NUM, K_SUP_DEN = 7, 10
K_AXIS = 280
K_BAR = 50
K_FRAC_GAP = 120
K_FRAC_PAD = 80
K_OP_SPACE = 180
K_SQRT_PAD = 60
K_MARGIN = 250

GLYPH, ROW, SUP, FRAC, SQRT, PAREN = range(6)


class PNode:
    __slots__ = ("k", "cp", "cls", "kids")

    def __init__(self, k, cp=0, cls="", kids=()):
        self.k = k
        self.cp = cp
        self.cls = cls
        self.kids = list(kids)


def pg(cp, cls):
    return PNode(GLYPH, cp=cp, cls=cls)


def pn(k, kids):
    return PNode(k, kids=kids)


def push_digits(out, v):
    if v < 0:
        out.append(pg(ord("-"), "-"))
        v = -v
    for c in str(v):
        out.append(pg(ord(c), c))


def split_frac(e):
    """積を「分子の因子」と「分母の因子」に分ける（指数が負のものが分母）。"""
    up, down = [], []
    fs = list(e.kids) if e.k == X.MUL else [e]
    for f in fs:
        if f.k == X.POW and X.is_num(f.kids[1]) and f.kids[1].num.neg():
            p = f.kids[1].num
            down.append(f.kids[0] if (p.n == -1 and p.d == 1)
                        else X.raw(X.POW, [f.kids[0], X.num(-p)]))
        elif X.is_num(f) and not f.num.is_int():
            up.append(X.num(X.Rat(f.num.n)))
            down.append(X.num(X.Rat(f.num.d)))
        else:
            up.append(f)
    return up, down


def present(e, paren=False):
    row = []
    if e.k == X.NUM:
        if e.num.is_int():
            push_digits(row, e.num.n)
        else:
            nu, de = [], []
            push_digits(nu, e.num.n)
            push_digits(de, e.num.d)
            return pn(FRAC, [pn(ROW, nu), pn(ROW, de)])
    elif e.k == X.SYM:
        for c in e.name:
            row.append(pg(ord(c), c))
    elif e.k == X.ADD:
        ts = X.disp_terms(e)
        for i, t in enumerate(ts):
            c, rest = X.split_coeff(t)
            minus = c.neg()
            if i == 0:
                if minus:
                    row.append(pg(ord("-"), "-"))
            else:
                row.append(pg(ord("-") if minus else ord("+"), "-" if minus else "+"))
            ac = -c if minus else c
            if ac.is_one() and not X.is_num(rest):
                body = rest
            elif X.is_num(rest) and rest.num.is_one():
                body = X.num(ac)
            else:
                body = X.mul_n([X.num(ac), rest])
            row.append(present(body, body.k == X.ADD))
    elif e.k == X.MUL:
        up, down = split_frac(e)
        if down:
            # 分子の 1 は書かない（1/2 x は "1x/2" ではなく "x/2"）
            if len(up) > 1:
                keep = [u for u in up if not (X.is_num(u) and u.num.is_one())]
                if keep:
                    up = keep
            nu = X.num(1) if not up else (up[0] if len(up) == 1 else X.raw(X.MUL, up))
            de = down[0] if len(down) == 1 else X.raw(X.MUL, down)
            return pn(FRAC, [present(nu), present(de)])
        for f in e.kids:
            row.append(present(f, f.k == X.ADD))
    elif e.k == X.POW:
        b, p = e.kids
        if X.is_num(p) and p.num == X.Rat(1, 2):
            return pn(SQRT, [present(b)])
        # 負の指数は分数で描く（人は y^-1 ではなく 1/y と書く）。上付きで描くと解析側が
        # 指数の "-" を二項の引き算と取り違える
        if X.is_num(p) and p.num.neg():
            inv = b if (p.num.n == -1 and p.num.d == 1) else X.raw(X.POW, [b, X.num(-p.num)])
            return pn(FRAC, [present(X.num(1)), present(inv)])
        return pn(SUP, [present(b, b.k in (X.ADD, X.MUL)), present(p)])
    elif e.k == X.FN:
        for c in e.name:
            row.append(pg(ord(c), c))
        row.append(pn(PAREN, [present(e.kids[0] if e.kids else X.num(0))]))
    elif e.k == X.EQ:
        row.append(present(e.kids[0]))
        row.append(pg(ord("="), "="))
        row.append(present(e.kids[1]))
    r = pn(ROW, row)
    return pn(PAREN, [r]) if paren else r


# ---------------------------------------------------------------- フォント


class Font:
    """TTF の実寸を読むだけの入れ物。stb_truetype が読むのと同じテーブルを読む。"""

    CANDIDATES = [
        "fonts/math.ttf",
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/georgia.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    ]

    def __init__(self, path=""):
        from fontTools.ttLib import TTFont
        tries = ([path] if path else []) + self.CANDIDATES
        self.path = None
        for p in tries:
            if os.path.exists(p):
                self.path = p
                break
        if self.path is None:
            raise SystemExit("フォントが見つかりません（--font で TTF を渡してください）")
        self.tt = TTFont(self.path, fontNumber=0) if self.path.endswith(".ttc") else TTFont(self.path)
        self.upem = self.tt["head"].unitsPerEm
        self.cmap = self.tt.getBestCmap()
        self.hmtx = self.tt["hmtx"]
        self.glyf = self.tt["glyf"] if "glyf" in self.tt else None
        self._cache = {}

    def _name(self, cp):
        return self.cmap.get(cp)

    def advance(self, cp):
        n = self._name(cp)
        return self.hmtx[n][0] if n else 0

    def bbox(self, cp):
        """(x0, y0, x1, y1)。空グリフは 0。stbtt_GetCodepointBox と同じ値になる。"""
        if cp in self._cache:
            return self._cache[cp]
        n = self._name(cp)
        r = (0, 0, 0, 0)
        if n and self.glyf is not None:
            g = self.glyf[n]
            if g.numberOfContours != 0:
                r = (g.xMin, g.yMin, g.xMax, g.yMax)
        self._cache[cp] = r
        return r


def emk(f, k):
    return f.upem * k // 1000


def mulr(v, sn, sd):
    """C++ の整数除算に合わせて **0 方向に切り捨てる**。

    Python の // は床関数なので、負の座標（下付きの descender など）で C++ と 1 ずれる。
    実測: sqrt(y)*y = y^(3/2) の指数の中の数字の枠が y0 77 対 78 になった。
    枠が 1px 違うだけでも、学習データの正解としては「両言語で違うもの」になる。
    """
    q = abs(v) * sn // sd
    return -q if v < 0 else q


# ---------------------------------------------------------------- レイアウト


class Item:
    __slots__ = ("cls", "cp", "x", "y", "sn", "sd", "w", "h", "x0", "y0", "x1", "y1")

    def __init__(self, cls, cp, x, y, sn, sd, w, h, x0, y0, x1, y1):
        self.cls, self.cp = cls, cp
        self.x, self.y = x, y
        self.sn, self.sd = sn, sd
        self.w, self.h = w, h
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1


class Layout:
    __slots__ = ("w", "asc", "desc", "items")

    def __init__(self):
        self.w = self.asc = self.desc = 0
        self.items = []


def shift(L, dx, dy):
    for it in L.items:
        it.x += dx
        it.y += dy
        it.x0 += dx
        it.x1 += dx
        it.y0 += dy
        it.y1 += dy


def lay(f, p, sn=1, sd=1):
    out = Layout()
    if p.k == GLYPH:
        adv = mulr(f.advance(p.cp), sn, sd)
        x0, y0, x1, y1 = f.bbox(p.cp)
        it = Item(p.cls, p.cp, 0, 0, sn, sd, 0, 0,
                  mulr(x0, sn, sd), mulr(y0, sn, sd), mulr(x1, sn, sd), mulr(y1, sn, sd))
        out.items.append(it)
        out.w = adv
        out.asc = it.y1 if it.y1 > 0 else 0
        out.desc = -it.y0 if it.y0 < 0 else 0
        return out

    if p.k == ROW:
        x = asc = desc = 0
        for c in p.kids:
            L = lay(f, c, sn, sd)
            op = c.k == GLYPH and c.cls in ("+", "-", "=")
            if op:
                x += mulr(emk(f, K_OP_SPACE), sn, sd)
            shift(L, x, 0)
            x += L.w
            if op:
                x += mulr(emk(f, K_OP_SPACE), sn, sd)
            asc = max(asc, L.asc)
            desc = max(desc, L.desc)
            out.items.extend(L.items)
        out.w, out.asc, out.desc = x, asc, desc
        return out

    if p.k == SUP:
        b = lay(f, p.kids[0], sn, sd)
        e = lay(f, p.kids[1], sn * K_SUP_NUM, sd * K_SUP_DEN)
        rise = mulr(emk(f, K_SUP_SHIFT), sn, sd)
        shift(e, b.w, rise)
        out.items = b.items + e.items
        out.w = b.w + e.w
        out.asc = max(b.asc, rise + e.asc)
        out.desc = max(b.desc, e.desc - rise if e.desc - rise > 0 else 0)
        return out

    if p.k == FRAC:
        nu = lay(f, p.kids[0], sn, sd)
        de = lay(f, p.kids[1], sn, sd)
        pad = mulr(emk(f, K_FRAC_PAD), sn, sd)
        bar = mulr(emk(f, K_BAR), sn, sd)
        gap = mulr(emk(f, K_FRAC_GAP), sn, sd)
        axis = mulr(emk(f, K_AXIS), sn, sd)
        inner = max(nu.w, de.w)
        w = inner + 2 * pad
        shift(nu, pad + (inner - nu.w) // 2, axis + bar + gap + nu.desc)
        shift(de, pad + (inner - de.w) // 2, axis - gap - de.asc)
        out.items.append(Item("frac", 0, 0, axis, sn, sd, w, bar, 0, axis, w, axis + bar))
        out.items.extend(nu.items)
        out.items.extend(de.items)
        out.w = w
        out.asc = axis + bar + gap + nu.desc + nu.asc
        out.desc = max(0, -(axis - gap - de.asc - de.desc))
        return out

    if p.k == SQRT:
        inner = lay(f, p.kids[0], sn, sd)
        pad = mulr(emk(f, K_SQRT_PAD), sn, sd)
        radv = mulr(f.advance(0x221A), sn, sd)
        bar = mulr(emk(f, K_BAR), sn, sd)
        rad = lay(f, pg(0x221A, "sqrt"), sn, sd)
        shift(inner, radv + pad, 0)
        top = max(inner.asc + pad, rad.asc)
        out.items = list(rad.items)
        out.items.append(Item("sqrt", 0, radv, top, sn, sd, inner.w + 2 * pad, bar,
                              radv, top, radv + inner.w + 2 * pad, top + bar))
        out.items.extend(inner.items)
        out.w = radv + inner.w + 2 * pad
        out.asc = top + bar
        out.desc = max(rad.desc, inner.desc)
        return out

    if p.k == PAREN:
        inner = lay(f, p.kids[0], sn, sd)
        l = lay(f, pg(ord("("), "("), sn, sd)
        r = lay(f, pg(ord(")"), ")"), sn, sd)
        shift(inner, l.w, 0)
        shift(r, l.w + inner.w, 0)
        out.items = l.items + inner.items + r.items
        out.w = l.w + inner.w + r.w
        out.asc = max(l.asc, r.asc, inner.asc)
        out.desc = max(l.desc, r.desc, inner.desc)
        return out
    return out


def to_px(v, px, upem):
    """フォント単位 -> 画素。C++ の to_px と同じ丸め（負でも同じになるように書く）。"""
    num = v * px * 2
    den = upem * 2
    return (num + den // 2) // den if num >= 0 else -((-num + den // 2) // den)


def layout_boxes(f, e, px):
    """(w, h, [(cls, x0, y0, x1, y1)]) を返す。これが C++ と一致すべきもの。"""
    p = present(e)
    L = lay(f, p)
    minx, maxx = 0, L.w
    miny, maxy = -L.desc, L.asc
    for it in L.items:
        # bbox は shift() で既に絶対座標。it.x を足すと二重加算になる（C++ 側と同じ間違いを
        # していて、両言語で同じ枠を出していたのでパリティは通っていた。組版 -> 解析の
        # 往復テストが捕まえた）
        minx, maxx = min(minx, it.x0), max(maxx, it.x1)
        miny, maxy = min(miny, it.y0), max(maxy, it.y1)
    mg = emk(f, K_MARGIN)
    W = max(1, to_px(maxx - minx + 2 * mg, px, f.upem))
    H = max(1, to_px(maxy - miny + 2 * mg, px, f.upem))
    ox = -minx + mg
    oy = maxy + mg
    boxes = []
    draw = []
    for it in L.items:
        if it.cp == 0:
            x0 = to_px(it.x0 + ox, px, f.upem)
            x1 = to_px(it.x1 + ox, px, f.upem)
            y0 = to_px(oy - it.y1, px, f.upem)
            y1 = to_px(oy - it.y0, px, f.upem)
            boxes.append((it.cls, x0, y0, x1, max(y1, y0 + 1)))
            draw.append(("line", x0, y0, x1, max(y1, y0 + 1), 0, 0, 0))
            continue
        bx0 = to_px(it.x0 + ox, px, f.upem)
        bx1 = to_px(it.x1 + ox, px, f.upem)
        by0 = to_px(oy - it.y1, px, f.upem)
        by1 = to_px(oy - it.y0, px, f.upem)
        boxes.append((it.cls, bx0, by0, max(bx1, bx0 + 1), max(by1, by0 + 1)))
        draw.append(("glyph", to_px(it.x + ox, px, f.upem), to_px(oy - it.y, px, f.upem),
                     it.cp, it.sn, it.sd, 0, 0))
    return W, H, boxes, draw


def render(f, e, px):
    """絵を描いて (PIL.Image, boxes) を返す。ラスタは C++ と一致しない（意図的、冒頭参照）。"""
    from PIL import Image, ImageDraw, ImageFont
    W, H, boxes, draw = layout_boxes(f, e, px)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    fonts = {}
    for kind, a, b, c, sn, sd, _g, _h in draw:
        if kind == "line":
            d.rectangle([a, b, c - 1, sn - 1], fill=0)
            continue
        size = max(1, round(px * sn / sd))
        if size not in fonts:
            fonts[size] = ImageFont.truetype(f.path, size)
        d.text((a, b), chr(c), font=fonts[size], fill=0, anchor="ls")
    return img, boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--labels", default="")
    ap.add_argument("--px", type=int, default=48)
    ap.add_argument("--font", default="")
    a = ap.parse_args()
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    f = Font(a.font)
    img, boxes = render(f, e, a.px)
    if a.out:
        img.save(a.out)
        print("wrote %s (%dx%d, %d 記号, upem %d)" % (a.out, img.width, img.height, len(boxes),
                                                     f.upem))
    if a.labels:
        with open(a.labels, "w", encoding="utf-8") as fp:
            fp.write("# %s\n# image %d %d\n" % (a.expr, img.width, img.height))
            for cls, x0, y0, x1, y1 in boxes:
                fp.write("%s %d %d %d %d\n" % (cls, x0, y0, x1, y1))
        print("wrote %s" % a.labels)
    return 0


if __name__ == "__main__":
    sys.exit(main())
