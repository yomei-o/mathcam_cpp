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


class Style:
    """描き方の指定（C++ の ts::Style の鏡）。既定は今までと同じ絵。

    教科書は変数がイタリックで、マイナスが U+2212（長い横棒）。実測ではこの 2 つが
    学習データに無いだけで、端から端までの正解率が 95.0% -> 33.3% に落ちた。
    """

    __slots__ = ("italic_vars", "minus_cp", "ink", "paper", "blur", "plain_one")

    def __init__(self, italic_vars=False, minus_cp=ord("-"), ink=0, paper=255, blur=0,
                 plain_one=False):
        # **数字の 1 を「縦棒だけ」の字で描く**（C++ の ts::Style::plain_one と同じ）。
        # 実写の教科書の 1 は旗も台も無い縦棒で、手元の書体はどれも旗つき。学習データに
        # この字形が無いと、モデルは縦棒を l と読むしかない。ラベルは "1" のまま。
        self.plain_one = plain_one
        self.italic_vars = italic_vars
        self.minus_cp = minus_cp
        # 写真は真っ黒と真っ白ではない（実測: 教科書の写真は紙 225 前後、字 60 前後）
        self.ink = ink
        self.paper = paper
        self.blur = blur


class PNode:
    __slots__ = ("k", "cp", "cls", "ital", "kids")

    def __init__(self, k, cp=0, cls="", kids=(), ital=False):
        self.k = k
        self.cp = cp
        self.cls = cls
        self.ital = ital
        self.kids = list(kids)


def pg(cp, cls, ital=False):
    return PNode(GLYPH, cp=cp, cls=cls, ital=ital)


def pn(k, kids):
    return PNode(k, kids=kids)


def push_digits(out, v, st=None):
    st = st or Style()
    if v < 0:
        out.append(pg(st.minus_cp, "-"))
        v = -v
    for c in str(v):
        out.append(pg(ord("l") if (st.plain_one and c == "1") else ord(c), c))


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


def starts_with_digit(f):
    """その因子は数字から描き始まるか（掛け算の記号を省いてよいかの判定。C++ と同じ規則）。"""
    if X.is_num(f):
        return f.num.is_int()
    if f.k == X.POW:
        p = f.kids[1]
        if X.is_num(p) and (p.num == X.Rat(1, 2) or p.num.neg()):
            return False                       # 根号・分数で描かれる
        return starts_with_digit(f.kids[0])
    if f.k == X.MUL and f.kids:
        return starts_with_digit(f.kids[0])
    return False


def present(e, paren=False, st=None):
    st = st or Style()
    row = []
    if e.k == X.NUM:
        if e.num.is_int():
            push_digits(row, e.num.n, st)
        else:
            nu, de = [], []
            push_digits(nu, e.num.n, st)
            push_digits(de, e.num.d, st)
            return pn(FRAC, [pn(ROW, nu), pn(ROW, de)])
    elif e.k == X.SYM:
        for c in e.name:                                 # 変数だけイタリック（教科書の組み方）
            row.append(pg(ord(c), c, st.italic_vars))
    elif e.k == X.ADD:
        ts = X.disp_terms(e)
        for i, t in enumerate(ts):
            c, rest = X.split_coeff(t)
            minus = c.neg()
            if i == 0:
                if minus:
                    row.append(pg(st.minus_cp, "-"))
            else:
                row.append(pg(st.minus_cp if minus else ord("+"), "-" if minus else "+"))
            ac = -c if minus else c
            if ac.is_one() and not X.is_num(rest):
                body = rest
            elif X.is_num(rest) and rest.num.is_one():
                body = X.num(ac)
            else:
                body = X.mul_n([X.num(ac), rest])
            row.append(present(body, body.k == X.ADD, st))
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
            return pn(FRAC, [present(nu, False, st), present(de, False, st)])
        # 掛け算は記号を書かずに並べる。**ただし数のあとに数が来るときは × を書く**
        # （並べると桁として読める。実測: `8 * 6^(3/2)` が `86^(3/2)` に読み戻された）
        for i, f in enumerate(e.kids):
            if i and X.is_num(e.kids[i - 1]) and starts_with_digit(f):
                row.append(pg(0x00D7, "times"))
            row.append(present(f, f.k == X.ADD, st))
    elif e.k == X.POW:
        b, p = e.kids
        if X.is_num(p) and p.num == X.Rat(1, 2):
            return pn(SQRT, [present(b, False, st)])
        # 負の指数は分数で描く（人は y^-1 ではなく 1/y と書く）。上付きで描くと解析側が
        # 指数の "-" を二項の引き算と取り違える
        if X.is_num(p) and p.num.neg():
            inv = b if (p.num.n == -1 and p.num.d == 1) else X.raw(X.POW, [b, X.num(-p.num)])
            return pn(FRAC, [present(X.num(1), False, st), present(inv, False, st)])
        return pn(SUP, [present(b, b.k in (X.ADD, X.MUL), st), present(p, False, st)])
    elif e.k == X.FN:
        for c in e.name:
            row.append(pg(ord(c), c))
        row.append(pn(PAREN, [present(e.kids[0] if e.kids else X.num(0), False, st)]))
    elif e.k == X.REL:
        # 演算子は name の 1 文字ずつを字として置く（"=" のときは以前と同じ絵）。
        # "<=" は暫定で '<' '=' の 2 字（本物の ≤ の字とクラス追加は認識側の仕事）
        row.append(present(e.kids[0], False, st))
        for c in e.name:
            row.append(pg(st.minus_cp if c == "-" else ord(c), c))
        row.append(present(e.kids[1], False, st))
    elif e.k == X.SYS:
        # 連立は暫定で 1 行に "," 区切り（本来は中括弧つきの複数行）
        for i, c in enumerate(e.kids):
            if i:
                row.append(pg(ord(","), ","))
            row.append(present(c, False, st))
    r = pn(ROW, row)
    return pn(PAREN, [r]) if paren else r


# ---------------------------------------------------------------- 小学校の計算を描く
#
# **CAS の木からは描けない**（0.96 ÷ 1.2 は正規形で 4/5 に、2 5/8 は 21/8 に畳まれる）。
# 書かれたとおりの絵が欲しいので、テキストから直に見た目の木を作る。値は同じテキストを
# X.parse に通せば出る（frac / mixed も読める）。C++ の ts::present_arith と同じ規則。


def _arith_atom(s, i, st):
    row = []
    while i < len(s) and s[i] in " 	":
        i += 1
    if i >= len(s):
        return pn(ROW, row), i
    if s.startswith("frac(", i):
        i += 5
        a, i = _present_arith(s, i, st, ",")
        if i < len(s) and s[i] == ",":
            i += 1
        b, i = _present_arith(s, i, st, ")")
        if i < len(s) and s[i] == ")":
            i += 1
        return pn(FRAC, [a, b]), i
    if s.startswith("mixed(", i):
        i += 6
        w, i = _present_arith(s, i, st, ",")
        if i < len(s) and s[i] == ",":
            i += 1
        a, i = _present_arith(s, i, st, ",")
        if i < len(s) and s[i] == ",":
            i += 1
        b, i = _present_arith(s, i, st, ")")
        if i < len(s) and s[i] == ")":
            i += 1
        return pn(ROW, [w, pn(FRAC, [a, b])]), i      # 帯分数は整数と分数を並べるだけ
    if s[i] == "(":
        i += 1
        inner, i = _present_arith(s, i, st, ")")
        if i < len(s) and s[i] == ")":
            i += 1
        return pn(PAREN, [inner]), i
    if s[i] == "{":                                   # 中括弧は伸ばさない（教科書もそう）
        i += 1
        inner, i = _present_arith(s, i, st, "}")
        if i < len(s) and s[i] == "}":
            i += 1
        return pn(ROW, [pg(ord("{"), "brace_l"), inner, pg(ord("}"), "brace_r")]), i
    if s[i].isdigit() or s[i] == ".":
        while i < len(s) and (s[i].isdigit() or s[i] == "."):
            c = s[i]
            i += 1
            row.append(pg(ord("."), "dot") if c == "." else pg(ord(c), c))
        return pn(ROW, row), i
    if s[i].isalpha():
        row.append(pg(ord(s[i]), s[i], st.italic_vars))
        return pn(ROW, row), i + 1
    return pn(ROW, row), i + 1                        # 読めない字は捨てる


def _present_arith(s, i, st, stop=""):
    row = []
    while True:
        while i < len(s) and s[i] in " 	":
            i += 1
        if i >= len(s):
            break
        if stop and s[i] == stop:
            break
        if s[i] in ")},":
            break
        if s[i] == "+":
            row.append(pg(ord("+"), "+"))
            i += 1
            continue
        if s[i] == "-":
            row.append(pg(st.minus_cp, "-"))
            i += 1
            continue
        if s[i] == "=":
            row.append(pg(ord("="), "="))
            i += 1
            continue
        if s[i] == "×":
            row.append(pg(0x00D7, "times"))
            i += 1
            continue
        if s[i] == "÷":
            row.append(pg(0x00F7, "div"))
            i += 1
            continue
        node, i = _arith_atom(s, i, st)
        row.append(node)
    return pn(ROW, row), i


def present_arith(src, st=None):
    node, _i = _present_arith(src, 0, st or Style(), "")
    return node


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
    # 数式のイタリック体（教科書の変数はこれで組まれている）。C++ 側の kItalic と同じ並び
    CANDIDATES_ITALIC = [
        "fonts/math-italic.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/cambriai.ttf",
        "C:/Windows/Fonts/georgiai.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    ]

    def __init__(self, path="", italic=False):
        from fontTools.ttLib import TTFont
        tries = ([path] if path else []) + (self.CANDIDATES_ITALIC if italic
                                            else self.CANDIDATES)
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
        # **OTF（CFF 輪郭）は glyf を持たない。** ここを見ていなかったので、CFF の書体では
        # 枠が全部 0 になり、C++ と 67/78 も食い違っていた（数式書体を入れて初めて出た）。
        # stb_truetype は CFF でも**制御点の範囲**で枠を出すので、こちらもそれに合わせる。
        self.gset = None if self.glyf is not None else self.tt.getGlyphSet()
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
        elif n and self.gset is not None:
            from fontTools.pens.boundsPen import ControlBoundsPen
            pen = ControlBoundsPen(self.gset)
            self.gset[n].draw(pen)
            if pen.bounds is not None:
                x0, y0, x1, y1 = pen.bounds
                r = (int(x0), int(y0), int(x1), int(y1))
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
    __slots__ = ("cls", "cp", "x", "y", "sn", "sd", "w", "h", "x0", "y0", "x1", "y1", "ital")

    def __init__(self, cls, cp, x, y, sn, sd, w, h, x0, y0, x1, y1):
        self.ital = False
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


def conv_upem(v, from_upem, to_upem):
    """別の upem を持つ書体を混ぜても崩れないように「ローマン体のフォント単位」に直す。
    C++ の conv_upem と同じ切り捨て（0 方向）にする。"""
    q = v * to_upem
    return q // from_upem if q >= 0 else -((-q) // from_upem)


def lay(f, fi, p, sn=1, sd=1):
    out = Layout()
    if p.k == GLYPH:
        ital = p.ital and fi is not None
        g = fi if ital else f
        adv = g.advance(p.cp)
        x0, y0, x1, y1 = g.bbox(p.cp)
        if ital and g.upem != f.upem:
            adv = conv_upem(adv, g.upem, f.upem)
            x0 = conv_upem(x0, g.upem, f.upem)
            y0 = conv_upem(y0, g.upem, f.upem)
            x1 = conv_upem(x1, g.upem, f.upem)
            y1 = conv_upem(y1, g.upem, f.upem)
        adv = mulr(adv, sn, sd)
        it = Item(p.cls, p.cp, 0, 0, sn, sd, 0, 0,
                  mulr(x0, sn, sd), mulr(y0, sn, sd), mulr(x1, sn, sd), mulr(y1, sn, sd))
        it.ital = ital
        out.items.append(it)
        out.w = adv
        out.asc = it.y1 if it.y1 > 0 else 0
        out.desc = -it.y0 if it.y0 < 0 else 0
        return out

    if p.k == ROW:
        x = asc = desc = 0
        for c in p.kids:
            L = lay(f, fi, c, sn, sd)
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
        b = lay(f, fi, p.kids[0], sn, sd)
        e = lay(f, fi, p.kids[1], sn * K_SUP_NUM, sd * K_SUP_DEN)
        rise = mulr(emk(f, K_SUP_SHIFT), sn, sd)
        shift(e, b.w, rise)
        out.items = b.items + e.items
        out.w = b.w + e.w
        out.asc = max(b.asc, rise + e.asc)
        out.desc = max(b.desc, e.desc - rise if e.desc - rise > 0 else 0)
        return out

    if p.k == FRAC:
        nu = lay(f, fi, p.kids[0], sn, sd)
        de = lay(f, fi, p.kids[1], sn, sd)
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
        inner = lay(f, fi, p.kids[0], sn, sd)
        pad = mulr(emk(f, K_SQRT_PAD), sn, sd)
        radv = mulr(f.advance(0x221A), sn, sd)
        bar = mulr(emk(f, K_BAR), sn, sd)
        rad = lay(f, fi, pg(0x221A, "sqrt"), sn, sd)
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
        inner = lay(f, fi, p.kids[0], sn, sd)
        l = lay(f, fi, pg(ord("("), "("), sn, sd)
        r = lay(f, fi, pg(ord(")"), ")"), sn, sd)
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


def layout_boxes_p(f, p, px, fi=None, st=None):
    """見た目の木から (w, h, boxes, draw) を作る（C++ の render_p と同じ道）。"""
    st = st or Style()
    L = lay(f, fi, p)
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
                     it.cp, it.sn, it.sd, 1 if it.ital else 0, 0))
    return W, H, boxes, draw


def layout_boxes(f, e, px, fi=None, st=None):
    """式木から枠を作る（今までの入口）。"""
    st = st or Style()
    return layout_boxes_p(f, present(e, False, st), px, fi, st)


def layout_boxes_arith(f, src, px, fi=None, st=None):
    """小学校の計算をテキストから（÷ や帯分数が畳まれないように木を経由しない）。"""
    st = st or Style()
    return layout_boxes_p(f, present_arith(src, st), px, fi, st)


def render_p(f, p, px, fi=None, st=None):
    """絵を描いて (PIL.Image, boxes) を返す。ラスタは C++ と一致しない（意図的、冒頭参照）。"""
    from PIL import Image, ImageDraw, ImageFont
    st = st or Style()
    W, H, boxes, draw = layout_boxes_p(f, p, px, fi, st)
    img = Image.new("L", (W, H), st.paper)
    d = ImageDraw.Draw(img)
    fonts = {}
    for kind, a, b, c, sn, sd, ital, _h in draw:
        if kind == "line":
            d.rectangle([a, b, c - 1, sn - 1], fill=st.ink)
            continue
        # イタリックの字はその書体の upem で大きさを決める（em の大きさを合わせる）
        src = fi if (ital and fi is not None) else f
        size = max(1, round(px * sn / sd))
        key = (size, 1 if src is fi else 0)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(src.path, size)
        d.text((a, b), chr(c), font=fonts[key], fill=st.ink, anchor="ls")
    if st.blur:
        from PIL import ImageFilter
        img = img.filter(ImageFilter.BoxBlur(1))       # 3x3 の平均 1 回（C++ 側と同じ狙い）
    return img, boxes


def render(f, e, px, fi=None, st=None):
    """式木から描く（今までの入口）。"""
    st = st or Style()
    return render_p(f, present(e, False, st), px, fi, st)


def render_arith(f, src, px, fi=None, st=None):
    """小学校の計算をテキストから描く。"""
    st = st or Style()
    return render_p(f, present_arith(src, st), px, fi, st)


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
