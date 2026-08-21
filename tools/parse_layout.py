"""レイアウト解析（Python 側）— pure/parse_layout.hpp の鏡。

検出器が出すのは「クラスと枠」の集まりで、そこには**構造が無い**。x^2 と x2、a/b と ab の
違いは位置関係だけで決まる。ここがその位置関係を読む場所。

規則は C++ 側と 1 対 1。閾値も同じ整数比較（%）で書く。float の比較にすると、同じ枠でも
片方だけ判定が変わる境目ができて、パリティが「だいたい一致」になる。

  python tools/parse_layout.py --labels out.txt
  python tools/parity/layout.py            # C++ と突き合わせる

**設計（C++ 側と同じ理由で 1 度目を捨てている）**: 構造を外側から畳んで原子にし、
残った平らな列を優先順位どおりに割る（= -> ± -> 並置・上付き）。
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 閾値（記号の大きさに対する比。C++ の enum と同じ値）
T_SUP_RISE = 30         # 上付きと見なす持ち上がり（基準の高さに対する %）
T_SUP_SMALL = 90        # 上付きは基準より小さい（未使用。C++ と同じく残す）
T_SAME_LINE = 35        # 同じ行と見なす中心のずれ（高さに対する %）
T_DIGIT_GAP = 40        # 桁をつなぐ隙間の上限（高さに対する %）


class Sym:
    __slots__ = ("cls", "x0", "y0", "x1", "y1", "base_y", "atom", "from_frac", "e")

    def __init__(self, cls="", x0=0, y0=0, x1=0, y1=0, base_y=None, atom=False, e=None):
        self.cls = cls
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.base_y = y1 if base_y is None else base_y
        self.atom = atom
        # その原子が縦の分数だったか（帯分数 2 5/8 = 2 + 5/8 の判定に要る）
        self.from_frac = False
        self.e = e

    def cx(self):
        return (self.x0 + self.x1) // 2

    def cy(self):
        return (self.y0 + self.y1) // 2

    def w(self):
        return self.x1 - self.x0

    def h(self):
        return self.y1 - self.y0


class Fail(Exception):
    """解析できない（C++ の why に相当）。"""


def median_h(v):
    """基準の高さ。**畳んだ原子は数えない**（縦に長いので閾値が壊れる）。"""
    hs = [s.h() for s in v if not s.atom and s.cls not in ("-", "frac", "=")]
    if not hs:
        return max(1, v[0].h()) if v else 1
    hs.sort()
    return max(1, hs[len(hs) // 2])


def make_atom(e, x0, y0, x1, y1, base_y):
    return Sym("@", x0, y0, x1, y1, base_y, True, e)


def run_baseline(v):
    """記号列のベースライン（いちばん下）。畳んだ原子に持たせる値。"""
    b, any_ = 0, False
    for s in v:
        if s.cls in ("frac", "sqrt"):
            continue                                  # 線はベースラインを持たない
        if not any_ or s.base_y > b:
            b, any_ = s.base_y, True
    return b if any_ else (v[0].y1 if v else 0)


def is_open(s):
    """括弧の開き（小学校の計算は { } も使う。どちらも同じ扱い）。"""
    return (not s.atom) and s.cls in ("(", "brace_l")


def is_close(s):
    return (not s.atom) and s.cls in (")", "brace_r")


def widest_frac(v):
    best = -1
    for i, s in enumerate(v):
        if not s.atom and s.cls == "frac" and (best < 0 or s.w() > v[best].w()):
            best = i
    return best


def widest_sqrt_bar(v):
    best = -1
    for i, s in enumerate(v):
        if (not s.atom and s.cls == "sqrt" and s.h() * 3 < s.w()
                and (best < 0 or s.w() > v[best].w())):
            best = i
    return best


def first_open_paren(v):
    for i, s in enumerate(v):
        if is_open(s):
            return i
    return -1


def match_close(v, i):
    depth = 0
    for k in range(i, len(v)):
        if v[k].atom:
            continue
        if is_open(v[k]):
            depth += 1
        elif is_close(v[k]):
            depth -= 1
            if depth == 0:
                return k
    return -1


def collapse_one(v):
    """構造を 1 つ畳む。畳んだら (True, 新しい列)。無ければ (False, v)。

    **外側から畳む**（分数線と根号の上線のうち幅の広い方を先に）。内側から畳むと、
    外側の上線が内側の集合に混ざって記号が取り残される。
    """
    fi_c = widest_frac(v)
    bi_c = widest_sqrt_bar(v)
    fw = v[fi_c].w() if fi_c >= 0 else -1
    bw = v[bi_c].w() if bi_c >= 0 else -1

    fi = fi_c if fw >= bw else -1
    if fi >= 0:
        bar = v[fi]
        up, down, rest = [], [], []
        ux0, uy0, ux1, uy1 = bar.x0, bar.y0, bar.x1, bar.y1
        for i, s in enumerate(v):
            if i == fi:
                continue
            if not (bar.x0 - 2 <= s.cx() <= bar.x1 + 2):
                rest.append(s)
                continue
            (up if s.cy() < bar.cy() else down).append(s)
            ux0, uy0 = min(ux0, s.x0), min(uy0, s.y0)
            ux1, uy1 = max(ux1, s.x1), max(uy1, s.y1)
        if not up or not down:
            raise Fail("分数の上か下が空です")
        nu = parse_flat(up)
        de = parse_flat(down)
        fr = make_atom(X.div(nu, de), ux0, uy0, ux1, uy1, bar.cy())
        fr.from_frac = True                          # 帯分数の判定に使う
        rest.append(fr)
        # 原子を末尾に足したので**必ず並べ直す**（忘れると = や ± の分割が位置と無関係になる）
        rest.sort(key=lambda s: s.x0)
        return True, rest

    if bi_c >= 0:
        bar = v[bi_c]
        inside, rest = [], []
        ux0, uy0, ux1, uy1 = bar.x0, bar.y0, bar.x1, bar.y1
        for i, s in enumerate(v):
            if i == bi_c:
                continue
            under = bar.x0 - 2 <= s.cx() <= bar.x1 + 2 and s.cy() > bar.cy()
            if not under:
                rest.append(s)
                continue
            inside.append(s)
            ux0, uy0 = min(ux0, s.x0), min(uy0, s.y0)
            ux1, uy1 = max(ux1, s.x1), max(uy1, s.y1)
        if not inside:
            raise Fail("根号の中身がありません")
        # 上線の**すぐ左にある**根号記号を 1 つだけ消す（2 つ並ぶと左を消してしまう）
        cand = -1
        for i, s in enumerate(rest):
            if s.atom or s.cls != "sqrt":
                continue
            if s.h() * 3 < s.w():
                continue                              # 上線ではなく記号だけを対象にする
            if s.x0 > bar.x0 + 2:
                continue
            if cand < 0 or s.x0 > rest[cand].x0:
                cand = i
        if cand >= 0:
            ux0 = min(ux0, rest[cand].x0)
            uy1 = max(uy1, rest[cand].y1)
            rest.pop(cand)
        e = parse_flat(inside)
        rest.append(make_atom(X.fn_e("sqrt", [e]), ux0, uy0, ux1, uy1, run_baseline(inside)))
        rest.sort(key=lambda s: s.x0)
        return True, rest

    pi = first_open_paren(v)
    if pi >= 0:
        pj = match_close(v, pi)
        if pj < 0:
            raise Fail("括弧が閉じていません")
        inside = v[pi + 1:pj]
        if not inside:
            raise Fail("括弧の中が空です")
        e = parse_flat(inside)
        ux0, uy0 = v[pi].x0, v[pi].y0
        ux1, uy1 = v[pj].x1, v[pj].y1
        for s in inside:
            uy0 = min(uy0, s.y0)
            uy1 = max(uy1, s.y1)
        out = list(v[:pi])
        out.append(make_atom(e, ux0, uy0, ux1, uy1, run_baseline(inside)))
        out.extend(v[pj + 1:])
        return True, out
    return False, v


def is_digit_cls(s):
    return (not s.atom) and len(s.cls) >= 1 and (s.cls[0].isdigit() or s.cls[0] == ".")


def is_dot_cls(s):
    """小数点。クラス名は "dot"（小学校の計算に出る）。"""
    return (not s.atom) and s.cls == "dot"


def to_rat(t):
    """数の文字列（小数もある）を厳密有理数にする。0.25 は 1/4（double は通さない）。"""
    if "." not in t:
        return X.Rat(int(t))
    ip, fp = t.split(".", 1)
    den = 10 ** len(fp)
    return X.Rat(int(ip or "0") * den + int(fp or "0"), den)


def merge_digits(v):
    """隣り合う桁をまとめる（同じ行にあって、隙間が狭いものだけ）。"""
    i = 0
    while i + 1 < len(v):
        # 数 . 数 の並びを 1 つにする（点は小さいので大きさの条件を通らない。先に処理する）
        if (i + 2 < len(v) and is_digit_cls(v[i]) and is_dot_cls(v[i + 1])
                and is_digit_cls(v[i + 2])):
            h = max(v[i].h(), v[i + 2].h())
            g1 = v[i + 1].x0 - v[i].x1
            g2 = v[i + 2].x0 - v[i + 1].x1
            if (g1 * 100 <= h * T_DIGIT_GAP and g2 * 100 <= h * T_DIGIT_GAP
                    and abs(v[i].y1 - v[i + 2].y1) * 100 <= h * T_SAME_LINE):
                v[i].cls += "." + v[i + 2].cls
                v[i].x1 = v[i + 2].x1
                v[i].y0 = min(v[i].y0, v[i + 2].y0)
                v[i].y1 = max(v[i].y1, v[i + 2].y1)
                del v[i + 1:i + 3]
                continue
        if is_digit_cls(v[i]) and is_digit_cls(v[i + 1]):
            h = max(v[i].h(), v[i + 1].h())
            gap = v[i + 1].x0 - v[i].x1
            same_line = abs(v[i].cy() - v[i + 1].cy()) * 100 <= h * T_SAME_LINE
            same_size = abs(v[i].h() - v[i + 1].h()) * 100 <= h * 25
            if same_line and same_size and gap * 100 <= h * T_DIGIT_GAP:
                v[i].cls += v[i + 1].cls
                v[i].x1 = v[i + 1].x1
                v[i].y0 = min(v[i].y0, v[i + 1].y0)
                v[i].y1 = max(v[i].y1, v[i + 1].y1)
                v.pop(i + 1)
                continue
        i += 1
    return v


def leaf(s):
    if s.atom:
        return s.e
    if is_digit_cls(s):
        return X.num(to_rat(s.cls))
    if len(s.cls) == 1 and s.cls.isalpha():
        return X.sym(s.cls)
    raise Fail("解釈できない記号: " + s.cls)


def is_sup(base, s, h_ref):
    """s が base の上付きか。**判定はベースラインの差**（大きさの比では駄目）。

    親が x のような背の低い字だと、0.7 倍に縮めた数字のほうが背が高くなる
    （実測: x の高さ 916、上付きの 2 が 968）。
    """
    lift = base.base_y - s.base_y
    if not s.atom and s.cls in ("+", "="):
        return False
    if not s.atom and s.cls == "-" and lift * 100 < h_ref * 60:
        return False
    if lift * 100 < h_ref * T_SUP_RISE:
        return False
    if lift * 100 >= h_ref * 60:
        return True                                    # 十分に持ち上がっていれば大きさは問わない
    return s.h() * 100 <= h_ref * 130


def parse_flat(v_in):
    v = sorted(v_in, key=lambda s: s.x0)
    if not v:
        raise Fail("記号がありません")

    # 1) 構造を全部畳む（外側から内側へ）
    while True:
        did, v = collapse_one(v)
        if not did:
            break

    # 2) 桁をまとめる
    v = merge_digits(list(v))

    # 3) = で割る。**右が空なら左だけの式として扱う**（プリントの「… = □」の形。
    #    答えを書く四角は読まないので、右辺には何も残らない）
    for i, s in enumerate(v):
        if not s.atom and s.cls == "=":
            l, r = v[:i], v[i + 1:]
            if not r and l:
                return parse_flat(l)
            if not l and r:
                return parse_flat(r)
            return X.eq(parse_flat(l), parse_flat(r))

    # 4) ± で割る（右から。左結合にするため）
    for i in range(len(v) - 1, 0, -1):
        s = v[i]
        if s.atom or s.cls not in ("+", "-"):
            continue
        l, r = v[:i], v[i + 1:]
        if not l or not r:
            raise Fail("演算子の両側が空です")
        a, b = parse_flat(l), parse_flat(r)
        return X.add(a, b) if s.cls == "+" else X.sub(a, b)
    if not v[0].atom and v[0].cls in ("+", "-") and len(v) > 1:
        a = parse_flat(v[1:])
        return X.neg(a) if v[0].cls == "-" else a

    # 5) × と ÷ で割る（右から。左結合にするため）。± より内側で、並置より外側
    for i in range(len(v) - 1, 0, -1):
        s = v[i]
        if s.atom or s.cls not in ("times", "div"):
            continue
        l, r = v[:i], v[i + 1:]
        if not l or not r:
            raise Fail("演算子の両側が空です")
        a, b = parse_flat(l), parse_flat(r)
        return X.mul(a, b) if s.cls == "times" else X.div(a, b)

    # 6) 並置（掛け算）と上付き。**数のすぐ右の分数は帯分数**（2 5/8 = 2 + 5/8）
    h_ref = median_h(v)
    factors = []
    add_it = []
    i = 0
    while i < len(v):
        base = v[i]
        b = leaf(base)
        mixed = i > 0 and base.atom and base.from_frac and is_digit_cls(v[i - 1])
        k = i + 1
        sup = []
        while k < len(v) and is_sup(base, v[k], h_ref):
            sup.append(v[k])
            k += 1
        if sup:
            b = X.pow_e(b, parse_flat(sup))
        factors.append(b)
        add_it.append(mixed)
        i = k
    if not factors:
        raise Fail("式になりません")
    r = factors[0]
    for j in range(1, len(factors)):
        r = X.add(r, factors[j]) if add_it[j] else X.mul(r, factors[j])
    return r


def parse(syms):
    """(ok, e, text, why) を返す（C++ の pl::Result に相当）。"""
    try:
        e = parse_flat(syms)
    except Fail as ex:
        return False, None, "", str(ex)
    return True, e, X.to_infix(e), ""


def read_labels(path):
    """`mathcam render --labels` の形（1 行 = クラス x0 y0 x1 y1）を読む。"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = line.split()
            if len(p) != 5:
                continue
            cls, a, b, c, d = p[0], int(p[1]), int(p[2]), int(p[3]), int(p[4])
            out.append(Sym(cls, a, b, c, d, d))        # 単独の記号はベースライン ≒ 箱の下端
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    a = ap.parse_args()
    ok, _e, text, why = parse(read_labels(a.labels))
    if not ok:
        print("parse failed: %s" % why)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
