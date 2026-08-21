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
    __slots__ = ("cls", "x0", "y0", "x1", "y1", "base_y", "atom", "from_frac", "score", "e")

    def __init__(self, cls="", x0=0, y0=0, x1=0, y1=0, base_y=None, atom=False, e=None):
        self.cls = cls
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.base_y = y1 if base_y is None else base_y
        self.atom = atom
        # その原子が縦の分数だったか（帯分数 2 5/8 = 2 + 5/8 の判定に要る）
        self.from_frac = False
        # 検出器の確からしさ（0..1）。式の読み方には使わない（表示と実験のため）
        self.score = 0.0
        self.e = e

    def cx(self):
        return (self.x0 + self.x1) // 2

    def cy(self):
        return (self.y0 + self.y1) // 2

    def w(self):
        return self.x1 - self.x0

    def h(self):
        return self.y1 - self.y0

    def copy(self):
        """**解析は入力を書き換えない**（C++ は値渡しなので自然にそうなっている）。

        merge_digits が cls を書き換えるので、同じ枠の列を 2 回解析すると
        `0.5` が `0.5.5` になった（畳む版と畳まない版の 2 回通したときに踏んだ）。
        """
        s = Sym(self.cls, self.x0, self.y0, self.x1, self.y1, self.base_y, self.atom, self.e)
        s.from_frac = self.from_frac
        s.score = self.score
        return s


class Fail(Exception):
    """解析できない（C++ の why に相当）。"""


# **畳まないで読むか**（小学校の手順を出すため。C++ の pl::raw_mode と同じ役目）。
# 畳んで読むと `1.8 × 3.5 - (10.2 - 6.8)` は `2.9` になり、どこを先に計算したかが消える。
_RAW = [False]


def mk_add(a, b):
    return X.raw(X.FN, [a, b], "op_add") if _RAW[0] else X.add(a, b)


def mk_sub(a, b):
    return X.raw(X.FN, [a, b], "op_sub") if _RAW[0] else X.sub(a, b)


def mk_mul(a, b):
    return X.raw(X.FN, [a, b], "op_mul") if _RAW[0] else X.mul(a, b)


def mk_div(a, b):
    # 縦の分数は 1 つの数として畳む（割り算をする所ではない）。÷ の記号だけ演算に残す
    if _RAW[0] and X.is_num(a) and X.is_num(b) and not b.num.is_zero():
        return X.num(a.num / b.num)
    return X.raw(X.FN, [a, b], "op_div") if _RAW[0] else X.div(a, b)


def mk_neg(a):
    return X.raw(X.FN, [a], "op_neg") if _RAW[0] else X.neg(a)


def median_h(v):
    """基準の高さ。**畳んだ原子は数えない**（縦に長いので閾値が壊れる）。"""
    hs = [s.h() for s in v if not s.atom and s.cls not in ("-", "frac", "=")]
    if not hs:
        # 全部が原子のとき（`(1/3)^(1/4)`）は**いちばん小さい原子**を基準にする。
        # 先頭の原子にすると土台が大きいほど上付きの閾値も大きくなり、指数を拾えない。
        return max(1, min(s.h() for s in v)) if v else 1
    hs.sort()
    return max(1, hs[len(hs) // 2])


# ---------------------------------------------------------------- 横棒を直す
#
# 検出器から見ると、**マイナス（U+2212）・分数線・根号の上線・= の 2 本**はどれも
# 「細長い横棒」で、字の形だけでは区別できない（実測: 実写で `=` が sqrt 2 個、
# マイナスが sqrt や frac になった）。見分けるのは**構造**の仕事。C++ の fix_bars と同じ規則。


def bar_like(s):
    return ((not s.atom) and s.cls in ("-", "frac", "sqrt", "=") and s.w() >= s.h() * 3)


def fix_bars(v, h_ref):
    # 1) 同じ棒が 2 つに割れて検出されたものをつなぐ（縦の位置がほぼ同じで、横が重なる）
    i = 0
    while i < len(v):
        if not bar_like(v[i]):
            i += 1
            continue
        j = i + 1
        while j < len(v):
            if not bar_like(v[j]):
                j += 1
                continue
            dy = abs(v[i].cy() - v[j].cy())
            ov = min(v[i].x1, v[j].x1) - max(v[i].x0, v[j].x0)
            shorter = min(v[i].w(), v[j].w())
            if dy * 100 <= max(4, h_ref * 12) and ov * 100 > shorter * 40:
                v[i].x0 = min(v[i].x0, v[j].x0)
                v[i].x1 = max(v[i].x1, v[j].x1)
                v[i].y0 = min(v[i].y0, v[j].y0)
                v[i].y1 = max(v[i].y1, v[j].y1)
                del v[j]
                continue
            j += 1
        i += 1
    # 2) 同じ x に上下 2 本あって、**間に何も無く、長さもほぼ同じ**なら `=`
    for i in range(len(v)):
        if not bar_like(v[i]):
            continue
        done = False
        for j in range(i + 1, len(v)):
            if not bar_like(v[j]):
                continue
            ov = min(v[i].x1, v[j].x1) - max(v[i].x0, v[j].x0)
            shorter = min(v[i].w(), v[j].w())
            longer = max(v[i].w(), v[j].w())
            dy = abs(v[i].cy() - v[j].cy())
            lo, hi = max(v[i].x0, v[j].x0), min(v[i].x1, v[j].x1)
            top, bot = min(v[i].cy(), v[j].cy()), max(v[i].cy(), v[j].cy())
            between = any(lo <= v[k].cx() <= hi and top < v[k].cy() < bot
                          for k in range(len(v)) if k not in (i, j))
            if (ov * 100 > shorter * 60 and shorter * 100 >= longer * 70 and not between
                    and dy > 0 and dy * 100 <= max(8, h_ref * 45)):
                v[i].cls = "="
                v[i].x0 = min(v[i].x0, v[j].x0)
                v[i].x1 = max(v[i].x1, v[j].x1)
                v[i].y0 = min(v[i].y0, v[j].y0)
                v[i].y1 = max(v[i].y1, v[j].y1)
                v[i].base_y = v[i].y1
                del v[j]
                done = True
                break
        if done:
            continue
    return v


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
            # **上か下に何も無い横棒はマイナス**（検出器には分数線と区別できない）
            v[fi].cls = "-"
            return True, v
        nu = parse_flat(up)
        de = parse_flat(down)
        fr = make_atom(mk_div(nu, de), ux0, uy0, ux1, uy1, bar.cy())
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
            # 根号の上線も細長い横棒なので、マイナスと取り違えられる
            v[bi_c].cls = "-"
            return True, v
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
    # 大きさは**土台と比べる**（本文の字と比べると、分数の指数が「大きすぎる」で落ちる）。
    if s.h() * 100 <= base.h() * 85:
        return True
    if s.h() * 100 > h_ref * 130:
        return False
    # 持ち上がりが微妙なとき（基準の 30..60%）は、**基準より明らかに小さい**か、
    # **ベースラインが基準の縦中央より上**にあることを要求する（C++ の is_sup と同じ）。
    #   * 実写は紙が傾くので隣の括弧の塊が持ち上がって見える（`(x+1)(x-2)=0` が
    #     `(x+1)^(x-2)=0` になった）。塊は基準と同じ大きさなので大きさの条件で落ちる。
    #   * 分数の指数（(1/3)^(1/4) の 1/4）は持ち上がりが小さいが基準より小さい。
    return s.base_y < base.cy()


# ---------------------------------------------------------------- 括弧と数字を直す
#
# 検出器から見ると `(` `)` と `6` `0` `1` は似ている（実測: 実写で `(x + 1)(x - 2) = 0` の
# `)` が `2` に、`3.7 × (2 - 0.4)` の `(` が `6` になった）。字の形では迷うが、**大きさの比**
# では迷わない: 括弧は背が高くて細い（実測 括弧 h≈48..51 / w/h≈0.31..0.36、
# 数字 h≈38..40 / w/h≈0.45..0.63）。C++ の fix_parens と同じ規則。


def fix_parens(v):
    hs = sorted(s.h() for s in v if (not s.atom) and len(s.cls) == 1 and s.cls.isdigit())
    if len(hs) < 2:
        return v
    med = max(1, hs[len(hs) // 2])
    ops = ("+", "-", "=", "times", "div", "dot")
    open_n = 0
    for i, s in enumerate(v):
        if s.atom:
            continue
        if s.cls == "(":
            open_n += 1
            continue
        if s.cls == ")":
            open_n -= 1
            continue
        if not (len(s.cls) == 1 and s.cls.isdigit()):
            continue
        # 実測値で決めた（括弧 h/med≈1.2..1.3 & w/h≈0.31..0.36、数字 1.0 & 0.45..0.63）
        if s.h() * 100 < med * 115:              # 背が高くなければ数字のまま
            continue
        if s.w() * 100 > s.h() * 40:             # 細くなければ数字のまま（`1` は 0.45）
            continue
        first, last = i == 0, i + 1 >= len(v)
        prev = "" if first else v[i - 1].cls
        nxt = "" if last else v[i + 1].cls
        if first or prev in ops or prev == "(":
            opening = True
        elif last or nxt in ops:
            opening = False
        else:
            opening = open_n <= 0
        s.cls = "(" if opening else ")"
        open_n += 1 if opening else -1
    return v


def strip_dangling(v):
    """**相手のいない演算子は落とす**（C++ の strip_dangling と同じ規則）。

    プリントの答え欄（四角）が `÷` や `+` として検出され、`… = □` の右辺に 1 個だけ残って
    解析が落ちた（実測: 「解釈できない記号: div」）。先頭の `-` は単項なので残す。
    """
    binary_only = ("+", "times", "div", "dot")
    while v and (not v[-1].atom) and (v[-1].cls in binary_only or v[-1].cls == "-"):
        v.pop()
    while v and (not v[0].atom) and v[0].cls in binary_only:
        v.pop(0)
    return v


def parse_flat(v_in):
    v = sorted((s.copy() for s in v_in), key=lambda s: s.x0)
    if not v:
        raise Fail("記号がありません")

    # 0) 横棒を直す（= が 2 本の棒に、マイナスが分数線や根号の上線に化けるのを構造で戻す）
    v = fix_bars(v, median_h(v))
    v.sort(key=lambda s: s.x0)
    # 0.5) 背が高くて細い数字は括弧（形では迷うが、大きさの比では迷わない）
    v = fix_parens(v)
    # 0.6) 相手のいない演算子を落とす（答え欄の四角が演算子として出ることがある）
    v = strip_dangling(v)
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
            l, r = strip_dangling(v[:i]), strip_dangling(v[i + 1:])
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
        return mk_add(a, b) if s.cls == "+" else mk_sub(a, b)
    if not v[0].atom and v[0].cls in ("+", "-") and len(v) > 1:
        a = parse_flat(v[1:])
        return mk_neg(a) if v[0].cls == "-" else a

    # 5) × と ÷ で割る（右から。左結合にするため）。± より内側で、並置より外側
    for i in range(len(v) - 1, 0, -1):
        s = v[i]
        if s.atom or s.cls not in ("times", "div"):
            continue
        l, r = v[:i], v[i + 1:]
        if not l or not r:
            raise Fail("演算子の両側が空です")
        a, b = parse_flat(l), parse_flat(r)
        # ÷ は「割り算をする所」なので raw では演算に残す（縦の分数と扱いが違う）
        if s.cls == "div" and _RAW[0]:
            return X.raw(X.FN, [a, b], "op_div")
        return mk_mul(a, b) if s.cls == "times" else X.div(a, b)

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
        r = mk_add(r, factors[j]) if add_it[j] else mk_mul(r, factors[j])
    return r


def parse(syms, raw=False):
    """(ok, e, text, why) を返す（C++ の pl::Result に相当）。

    raw=True で畳まないで読む（小学校の手順を出すため。C++ の pl::parse_raw と同じ）。
    """
    _RAW[0] = raw
    try:
        e = parse_flat(syms)
    except Fail as ex:
        _RAW[0] = False
        return False, None, "", str(ex)
    _RAW[0] = False
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
