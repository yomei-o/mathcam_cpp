"""数式そのもの（Python 側）— pure/expr.hpp の鏡。

規則は C++ 側と 1 対 1 に揃えてある。揃えないと、認識器の出力を Python で検算する意味が
無くなるし、手順表示が言語によって変わる。**同じ式を入れたら同じ正規形・同じ LaTeX が出る**
ことを tools/parity/expr.py が縛る。

C++ と意図的に違う点は 1 つだけ:

  * 数の桁。C++ は int64 の分子・分母で、Python は多倍長整数。つまり巨大な数では
    C++ が先に溢れる。パリティのテストは溢れない範囲で比べる（溢れる入力を渡したときの
    挙動を「同じ」にする意味がないので、そこは合わせない）。

  python tools/expr.py --expr "2/3 + 1/6"
"""
import argparse
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 種類の順序は C++ の enum Kind と同じ。cmp がこの並びに依存する
NUM, SYM, ADD, MUL, POW, FN, EQ = range(7)


class Rat:
    """厳密有理数（既約・分母は正）。1/3 を 0.333 にしたら手順表示が嘘になるので double は使わない。"""

    __slots__ = ("n", "d")

    def __init__(self, n=0, d=1):
        if d == 0:
            n, d = 0, 1                     # 0 除算は 0 に落とす（呼ぶ側で弾く）
        if d < 0:
            n, d = -n, -d
        g = math.gcd(abs(n), d)
        if g > 1:
            n //= g
            d //= g
        if n == 0:
            d = 1
        self.n, self.d = n, d

    def is_int(self):
        return self.d == 1

    def is_zero(self):
        return self.n == 0

    def is_one(self):
        return self.n == 1 and self.d == 1

    def neg(self):
        return self.n < 0

    def f(self):
        return self.n / self.d

    def __add__(self, o):
        return Rat(self.n * o.d + o.n * self.d, self.d * o.d)

    def __sub__(self, o):
        return Rat(self.n * o.d - o.n * self.d, self.d * o.d)

    def __mul__(self, o):
        return Rat(self.n * o.n, self.d * o.d)

    def __truediv__(self, o):
        return Rat(self.n * o.d, self.d * o.n)

    def __neg__(self):
        return Rat(-self.n, self.d)

    def __eq__(self, o):
        return isinstance(o, Rat) and self.n == o.n and self.d == o.d

    def __lt__(self, o):
        return self.n * o.d < o.n * self.d

    def __hash__(self):
        return hash((self.n, self.d))

    def __str__(self):
        return "%d" % self.n if self.d == 1 else "%d/%d" % (self.n, self.d)


def rpow(a, e):
    """整数の冪。指数が負や分数のときは呼ばない（呼ぶ側が Pow のまま残す）。"""
    if e < 0:
        return Rat(1) / rpow(a, -e)
    r = Rat(1)
    for _ in range(e):
        r = r * a
    return r


class Node:
    """式木の節。不変（作ったら書き換えない）。手順表示が各段の木を保持するため。"""

    __slots__ = ("k", "num", "name", "kids")

    def __init__(self, k, num=None, name="", kids=()):
        self.k = k
        self.num = num if num is not None else Rat(0)
        self.name = name
        self.kids = tuple(kids)


def num(v):
    return Node(NUM, num=(v if isinstance(v, Rat) else Rat(v)))


def sym(name):
    return Node(SYM, name=name)


def raw(k, kids, name=""):
    return Node(k, name=name, kids=kids)


def is_num(e):
    return e.k == NUM


def is_sym(e):
    return e.k == SYM


# ---------------------------------------------------------------- 全順序


def cmp(a, b):
    """決定的な順序。正規形のソートに使い、同じ式が構造として一致するようにする。"""
    if a.k != b.k:
        return -1 if a.k < b.k else 1
    if a.k == NUM:
        if a.num == b.num:
            return 0
        return -1 if a.num < b.num else 1
    if a.k == SYM:
        return 0 if a.name == b.name else (-1 if a.name < b.name else 1)
    if a.name != b.name:
        return -1 if a.name < b.name else 1
    if len(a.kids) != len(b.kids):
        return -1 if len(a.kids) < len(b.kids) else 1
    for x, y in zip(a.kids, b.kids):
        c = cmp(x, y)
        if c:
            return c
    return 0


def equal(a, b):
    return cmp(a, b) == 0


class _Key:
    """sort に cmp を使わせるための包み（C++ の std::sort と同じ順序にするため）。"""

    __slots__ = ("e",)

    def __init__(self, e):
        self.e = e

    def __lt__(self, o):
        return cmp(self.e, o.e) < 0


# ---------------------------------------------------------------- 正規形


def flatten(k, e, out):
    if e.k == k:
        for c in e.kids:
            flatten(k, c, out)
    else:
        out.append(e)


def split_coeff(t):
    """項を「係数 × 残り」に割る（同類項をまとめるため）。"""
    if t.k == NUM:
        return t.num, num(1)
    if t.k != MUL:
        return Rat(1), t
    c = Rat(1)
    others = []
    for f in t.kids:
        if f.k == NUM:
            c = c * f.num
        else:
            others.append(f)
    if not others:
        rest = num(1)
    elif len(others) == 1:
        rest = others[0]
    else:
        rest = raw(MUL, others)
    return c, rest


def split_pow(f):
    if f.k == POW:
        return f.kids[0], f.kids[1]
    return f, num(1)


def add_n(xs):
    flat = []
    for x in xs:
        flatten(ADD, simp(x), flat)
    konst = Rat(0)
    terms = []                                  # [(rest, coeff)] 挿入順を保つ
    for t in flat:
        if t.k == NUM:
            konst = konst + t.num
            continue
        c, rest = split_coeff(t)
        for i, (r, cc) in enumerate(terms):
            if equal(r, rest):
                terms[i] = (r, cc + c)
                break
        else:
            terms.append((rest, c))
    out = []
    for rest, c in terms:
        if c.is_zero():
            continue
        if c.is_one():
            out.append(rest)
        else:
            out.append(simp(raw(MUL, [num(c), rest])))
    if not konst.is_zero():
        out.append(num(konst))
    if not out:
        return num(0)
    if len(out) == 1:
        return out[0]
    out.sort(key=_Key)
    return raw(ADD, out)


def mul_n(xs):
    flat = []
    for x in xs:
        flatten(MUL, simp(x), flat)
    coef = Rat(1)
    bases = []                                  # [(base, [exponents])] 挿入順を保つ
    for f in flat:
        if f.k == NUM:
            coef = coef * f.num
            if coef.is_zero():
                return num(0)
            continue
        b, p = split_pow(f)
        for i, (bb, ps) in enumerate(bases):
            if equal(bb, b):
                ps.append(p)
                break
        else:
            bases.append((b, [p]))
    out = []
    for b, ps in bases:
        e = ps[0] if len(ps) == 1 else add_n(ps)
        if is_num(e) and e.num.is_zero():       # x^0 = 1
            continue
        if is_num(e) and e.num.is_one():
            out.append(b)
            continue
        out.append(raw(POW, [b, e]))
    if not out:
        return num(coef)
    if not coef.is_one():
        out.insert(0, num(coef))
    if len(out) == 1:
        return out[0]
    out.sort(key=_Key)
    return raw(MUL, out)


def _iroot(v, k):
    """v の k 乗根が整数なら返す。C++ 側と同じ「試して確かめる」やり方。"""
    if v < 0:
        return None
    r = round(v ** (1.0 / k)) if v else 0
    for c in range(max(0, r - 2), r + 3):
        q = 1
        ovf = False
        for _ in range(k):
            q *= c
            if q > (1 << 40):
                ovf = True
                break
        if not ovf and q == v:
            return c
    return None


def pow_e(b_in, e_in):
    b, p = simp(b_in), simp(e_in)
    if is_num(p):
        if p.num.is_zero():
            return num(1)
        if p.num.is_one():
            return b
        if is_num(b) and p.num.is_int():
            e = p.num.n
            if -32 < e < 32 and not (b.num.is_zero() and e < 0):
                return num(rpow(b.num, e))
        # まず根号の中の完全冪を外に出す（sqrt(8) -> 2*sqrt(2)）。これをやらないと
        # x^2 = 2 の答えが 1/2*sqrt(8) と出て、厳密に計算している意味が薄れる
        if is_num(b) and not p.num.is_int() and not b.num.neg() and p.num.n > 0:
            q = p.num.d
            if 1 < q <= 8:
                def pull(v):
                    outside, inside = 1, v
                    f = 2
                    while f * f <= inside and f < 4096:
                        pw = f ** q
                        if pw > 1:
                            while inside % pw == 0:
                                inside //= pw
                                outside *= f
                        f += 1
                    return outside, inside
                on, in_n = pull(b.num.n)
                od, in_d = pull(b.num.d)
                if on != 1 or od != 1:
                    coef = rpow(Rat(on, od), p.num.n)
                    if in_n == 1 and in_d == 1:
                        return num(coef)
                    return mul_n([num(coef), raw(POW, [num(Rat(in_n, in_d)), p])])
        # 厳密に閉じるなら畳む（sqrt(4)=2）。閉じないもの（sqrt(2)）は残す
        if is_num(b) and not p.num.is_int() and not b.num.neg():
            root, up = p.num.d, p.num.n
            if 1 < root <= 8 and -32 < up < 32:
                rn = _iroot(b.num.n, root)
                rd = _iroot(b.num.d, root)
                if rn is not None and rd is not None:
                    return num(rpow(Rat(rn, rd), up))
    if b.k == POW:                                            # (a^m)^n = a^(mn)
        inner = b.kids[1]
        if is_num(inner) and is_num(p) and inner.num.is_int() and p.num.is_int():
            return pow_e(b.kids[0], num(inner.num * p.num))
    if b.k == MUL and is_num(p) and p.num.is_int():            # (ab)^n = a^n b^n
        return mul_n([pow_e(f, p) for f in b.kids])
    return raw(POW, [b, p])


def fn_e(name, args):
    args = [simp(a) for a in args]
    if name == "sqrt" and len(args) == 1:
        return pow_e(args[0], num(Rat(1, 2)))
    if len(args) == 1 and is_num(args[0]):
        r = args[0].num
        if name == "abs":
            return num(-r if r.neg() else r)
        if name == "ln" and r.is_one():
            return num(0)
        if name in ("sin", "tan") and r.is_zero():
            return num(0)
        if name == "cos" and r.is_zero():
            return num(1)
        if name == "exp" and r.is_zero():
            return num(1)
    return raw(FN, args, name)


def simp(e):
    if e.k in (NUM, SYM):
        return e
    if e.k == ADD:
        return add_n(list(e.kids))
    if e.k == MUL:
        return mul_n(list(e.kids))
    if e.k == POW:
        return pow_e(e.kids[0], e.kids[1])
    if e.k == FN:
        return fn_e(e.name, list(e.kids))
    if e.k == EQ:
        return raw(EQ, [simp(e.kids[0]), simp(e.kids[1])])
    return e


def add(a, b):
    return add_n([a, b])


def sub(a, b):
    return add_n([a, mul_n([num(-1), b])])


def mul(a, b):
    return mul_n([a, b])


def div(a, b):
    return mul_n([a, pow_e(b, num(-1))])


def neg(a):
    return mul_n([num(-1), a])


def eq(a, b):
    return raw(EQ, [simp(a), simp(b)])


# ---------------------------------------------------------------- 展開


def expand_mul(fs):
    total = [num(1)]
    for f in fs:
        terms = list(f.kids) if f.k == ADD else [f]
        total = [mul_n([a, b]) for a in total for b in terms]
    return add_n(total)


def expand(e):
    """分配法則。simp に入れない理由は C++ 側のコメントと同じ（爆発と、くくった形の保持）。"""
    if e.k in (NUM, SYM):
        return e
    if e.k == ADD:
        return add_n([expand(c) for c in e.kids])
    if e.k == MUL:
        return expand_mul([expand(c) for c in e.kids])
    if e.k == POW:
        b, p = expand(e.kids[0]), expand(e.kids[1])
        if b.k == ADD and is_num(p) and p.num.is_int() and 1 < p.num.n <= 8:
            return expand_mul([b] * p.num.n)
        return pow_e(b, p)
    if e.k == FN:
        return fn_e(e.name, [expand(c) for c in e.kids])
    if e.k == EQ:
        return raw(EQ, [expand(e.kids[0]), expand(e.kids[1])])
    return e


# ---------------------------------------------------------------- 印字


def disp_degree(e):
    """表示のための次数。内部の正規順序とは別物（人は x^2 - 5x + 6 の順で書く）。"""
    if e.k == NUM:
        return 0
    if e.k == SYM:
        return 1
    if e.k == POW:
        p = e.kids[1]
        if is_num(p) and p.num.is_int():
            return disp_degree(e.kids[0]) * p.num.n
        return 1
    if e.k == MUL:
        return sum(disp_degree(c) for c in e.kids)
    if e.k == ADD:
        return max([0] + [disp_degree(c) for c in e.kids])
    return 1


def disp_terms(e):
    ts = list(e.kids)
    # 次数の降順、同じ次数なら正規順序。C++ の stable_sort と同じ結果になるように安定ソート
    ts.sort(key=lambda t: _Key(t))
    ts.sort(key=lambda t: -disp_degree(t))
    return ts


def prec(e):
    return {EQ: 0, ADD: 1, MUL: 2, POW: 3}.get(e.k, 4)


def _wrap(e, p):
    s = to_infix(e)
    return "(" + s + ")" if prec(e) < p else s


def _add_body(t):
    """和の 1 項を「符号」と「本体」に分ける（"+ -3" ではなく "- 3" と書くため）。"""
    c, rest = split_coeff(t)
    minus = c.neg()
    ac = -c if minus else c
    if ac.is_one() and not is_num(rest):
        body = rest
    elif is_num(rest) and rest.num.is_one():
        body = num(ac)
    else:
        body = mul_n([num(ac), rest])
    return minus, body


def to_infix(e):
    if e.k == NUM:
        return str(e.num)
    if e.k == SYM:
        return e.name
    if e.k == ADD:
        s = ""
        for i, t in enumerate(disp_terms(e)):
            minus, body = _add_body(t)
            if i == 0:
                if minus:
                    s += "-"
            else:
                s += " - " if minus else " + "
            s += _wrap(body, 1)
        return s
    if e.k == MUL:
        # 係数 -1 は "-1*x" ではなく "-x" と書く（人はそう書く）
        kids = list(e.kids)
        pre = ""
        if len(kids) > 1 and is_num(kids[0]) and kids[0].num.n == -1 and kids[0].num.d == 1:
            pre, kids = "-", kids[1:]
        return pre + "*".join(_wrap(c, 2) for c in kids)
    if e.k == POW:
        b, p = e.kids
        if is_num(p) and p.num == Rat(1, 2):
            return "sqrt(" + to_infix(b) + ")"
        # 分数・負の指数は括弧が必須。"2^1/2" は自分のパーサで (2^1)/2 に読めてしまう
        need = (not is_num(p)) or (not p.num.is_int()) or p.num.neg()
        ps = "(" + to_infix(p) + ")" if need else to_infix(p)
        return _wrap(b, 4) + "^" + ps
    if e.k == FN:
        return e.name + "(" + ", ".join(to_infix(c) for c in e.kids) + ")"
    if e.k == EQ:
        return to_infix(e.kids[0]) + " = " + to_infix(e.kids[1])
    return "?"


def to_latex(e):
    if e.k == NUM:
        if e.num.is_int():
            return str(e.num)
        return "\\frac{%d}{%d}" % (e.num.n, e.num.d)
    if e.k == SYM:
        return e.name
    if e.k == ADD:
        s = ""
        for i, t in enumerate(disp_terms(e)):
            minus, body = _add_body(t)
            if i == 0:
                if minus:
                    s += "-"
            else:
                s += " - " if minus else " + "
            s += to_latex(body)
        return s
    if e.k == MUL:
        kids = list(e.kids)
        pre = ""
        if len(kids) > 1 and is_num(kids[0]) and kids[0].num.n == -1 and kids[0].num.d == 1:
            pre, kids = "-", kids[1:]
        parts = []
        for f in kids:
            t = to_latex(f)
            if f.k == ADD:
                t = "(" + t + ")"
            parts.append(t)
        return pre + " ".join(parts)
    if e.k == POW:
        b, p = e.kids
        if is_num(p) and p.num == Rat(1, 2):
            return "\\sqrt{" + to_latex(b) + "}"
        if is_num(p) and p.num.n == -1 and p.num.d == 1:
            return "\\frac{1}{" + to_latex(b) + "}"
        bs = to_latex(b)
        if b.k in (ADD, MUL, POW):
            bs = "(" + bs + ")"
        return bs + "^{" + to_latex(p) + "}"
    if e.k == FN:
        return "\\" + e.name + "(" + ", ".join(to_latex(c) for c in e.kids) + ")"
    if e.k == EQ:
        return to_latex(e.kids[0]) + " = " + to_latex(e.kids[1])
    return "?"


# ---------------------------------------------------------------- 構文解析


class Parser:
    """C++ 側の Parser と同じ文法。暗黙の掛け算（5x, 2(x+1)）を受けるのは、
    写真から読んだ式がそう書かれているから。"""

    def __init__(self, src):
        self.s = src
        self.i = 0
        self.err = ""

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def eat(self, c):
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == c:
            self.i += 1
            return True
        return False

    def peek(self, c):
        self.ws()
        return self.i < len(self.s) and self.s[self.i] == c

    def parse_all(self):
        e = self.parse_eq()
        self.ws()
        if self.i < len(self.s) and not self.err:
            self.err = "余分な文字: " + self.s[self.i:]
        return e

    def parse_eq(self):
        l = self.parse_add()
        if self.eat("="):
            return raw(EQ, [l, self.parse_add()])
        return l

    def parse_add(self):
        l = self.parse_mul()
        while True:
            self.ws()
            if self.eat("+"):
                l = add_n([l, self.parse_mul()])
            elif self.eat("-"):
                l = add_n([l, mul_n([num(-1), self.parse_mul()])])
            else:
                return l

    def parse_mul(self):
        l = self.parse_unary()
        while True:
            self.ws()
            if self.eat("*"):
                l = mul_n([l, self.parse_unary()])
            elif self.eat("/"):
                l = mul_n([l, pow_e(self.parse_unary(), num(-1))])
            elif self.i < len(self.s) and (self.s[self.i].isalpha() or self.s[self.i] == "("
                                          or self.s[self.i].isdigit()):
                if self.s[self.i].isdigit() and is_num(l):
                    self.err = "数が続いています"
                    return l
                l = mul_n([l, self.parse_unary()])
            else:
                return l

    def parse_unary(self):
        self.ws()
        if self.eat("-"):
            return mul_n([num(-1), self.parse_unary()])
        if self.eat("+"):
            return self.parse_unary()
        return self.parse_pow()

    def parse_pow(self):
        b = self.parse_atom()
        self.ws()
        if self.eat("^"):
            return pow_e(b, self.parse_unary())        # 右結合
        return b

    def parse_atom(self):
        self.ws()
        if self.i >= len(self.s):
            self.err = "式が途中で終わっています"
            return num(0)
        if self.eat("("):
            e = self.parse_add()
            if not self.eat(")"):
                self.err = "閉じ括弧がありません"
            return e
        if self.s[self.i].isdigit():
            v = 0
            while self.i < len(self.s) and self.s[self.i].isdigit():
                v = v * 10 + int(self.s[self.i])
                self.i += 1
            if self.i < len(self.s) and self.s[self.i] == ".":
                self.i += 1
                f, den = 0, 1
                while self.i < len(self.s) and self.s[self.i].isdigit():
                    f = f * 10 + int(self.s[self.i])
                    den *= 10
                    self.i += 1
                return num(Rat(v * den + f, den))
            return num(v)
        if self.s[self.i].isalpha():
            name = ""
            while self.i < len(self.s) and self.s[self.i].isalnum():
                name += self.s[self.i]
                self.i += 1
            if self.peek("("):
                self.eat("(")
                args = [self.parse_add()]
                while self.eat(","):
                    args.append(self.parse_add())
                if not self.eat(")"):
                    self.err = "関数の閉じ括弧がありません"
                return fn_e(name, args)
            return sym(name)
        self.err = "読めない文字: " + self.s[self.i]
        self.i += 1
        return num(0)


def parse(src):
    """(式, エラー文) を返す。エラー文が空でなければ式は信用しない。"""
    p = Parser(src)
    e = p.parse_all()
    return simp(e), p.err


# ---------------------------------------------------------------- 補助


def collect_syms(e, out=None):
    if out is None:
        out = []
    if e.k == SYM and e.name not in out:
        out.append(e.name)
    for c in e.kids:
        collect_syms(c, out)
    return out


def approx(e):
    """数値評価。表示の最後だけで使う（厳密に閉じない sqrt など）。"""
    if e.k == NUM:
        return e.num.f()
    if e.k == SYM:
        return 0.0
    if e.k == ADD:
        return sum(approx(c) for c in e.kids)
    if e.k == MUL:
        r = 1.0
        for c in e.kids:
            r *= approx(c)
        return r
    if e.k == POW:
        return approx(e.kids[0]) ** approx(e.kids[1])
    if e.k == FN:
        a = approx(e.kids[0]) if e.kids else 0.0
        return {"sin": math.sin, "cos": math.cos, "tan": math.tan, "ln": math.log,
                "exp": math.exp, "abs": abs}.get(e.name, lambda x: x)(a)
    if e.k == EQ:
        return approx(e.kids[0]) - approx(e.kids[1])
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--latex", action="store_true")
    ap.add_argument("--approx", action="store_true")
    ap.add_argument("--no-expand", dest="no_expand", action="store_true")
    a = ap.parse_args()
    e, err = parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    if not a.no_expand:
        e = expand(e)
    print(to_infix(e))
    if a.latex:
        print("latex: %s" % to_latex(e))
    if a.approx and e.k != NUM:
        print("approx: %.10g" % approx(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
