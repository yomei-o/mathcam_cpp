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
# Rel は関係式（= < <= > >=）で、演算子は name に入れる（C++ の Kind::Rel と同じ）。
# Sys は連立（関係式の列、書かれた順のまま）。
NUM, SYM, ADD, MUL, POW, FN, REL, SYS = range(8)


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
    # **同じ次数の根はまとめる**（sqrt(2)*sqrt(3) = sqrt(6)）。教科書はそう書くし、
    # まとめないと sqrt(3)/sqrt(2) が有理化されない（1/sqrt(2) は sqrt(2)/2 になるのに、
    # 根どうしの割り算だけ残ってしまう）。
    rads = []                                        # (次数 q, 中身の積) を現れた順に
    keep = []
    merged = False
    for f in out:
        r = num_radical(f)
        if r is not None:
            q, inside = r
            hit = False
            for i, pr in enumerate(rads):
                if pr[0] == q:
                    rads[i] = (q, pr[1] * inside)
                    hit = merged = True
                    break
            if not hit:
                rads.append((q, inside))
            continue
        keep.append(f)
    if merged:
        xs = ([] if coef.is_one() else [num(coef)]) + keep
        xs += [pow_e(num(inside), num(Rat(1, q))) for q, inside in rads]
        return mul_n(xs)
    if not out:
        return num(coef)
    if not coef.is_one():
        out.insert(0, num(coef))
    if len(out) == 1:
        return out[0]
    out.sort(key=_Key)
    return raw(MUL, out)


def mul_safe(a, b):
    """掛け算のあふれ検査（根の中身 n^p' * d^(q-p') を作るときに使う）。

    Python は多倍長なので溢れないが、**C++ 側と同じところで諦めないと答えが変わる**ので
    同じ上限で切る。
    """
    if a == 0 or b == 0:
        return 0
    if a > 4000000000000000 // abs(b):
        return None
    return a * b


def num_radical(f):
    """「数の 1/q 乗」か（sqrt(2) や 6^(1/3)）。そうなら (q, 中身)、違えば None。"""
    if f.k != POW or not is_num(f.kids[0]) or not is_num(f.kids[1]):
        return None
    if f.kids[1].num.n != 1 or f.kids[1].num.d <= 1:
        return None
    return (f.kids[1].num.d, f.kids[0].num)


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
        # **数の根は「有理化して、中身から完全冪を外に出す」形に正規化する**:
        #   sqrt(8) -> 2 sqrt(2)   sqrt(4) -> 2      sqrt(9/4) -> 3/2
        #   sqrt(1/2) -> sqrt(2)/2   2^(-1/2) -> sqrt(2)/2   sqrt(2/3) -> sqrt(6)/3
        # 教科書の答えは**分母に根号を残さない**ので、正規形の側で一度に片づける
        # （表示のときに直すやり方だと、同じ数が別の木のまま残って差が 0 にならない）。
        #
        # やり方: 指数 p/q を「整数部 k」と「0 < p'/q < 1」に分け、
        #   a^(p'/q) = (n/d)^(p'/q) = (n^p' * d^(q-p'))^(1/q) / d
        # と書き直す（分母が根の外に出る）。あとは中身から q 乗の因数を外に出すだけ。
        if is_num(b) and not p.num.is_int() and not b.num.neg():
            if b.num.is_zero():
                if p.num.n > 0:
                    return num(0)
            else:
                q = p.num.d
                if 1 < q <= 8:
                    pp = p.num.n
                    k = pp // q if pp >= 0 else -((-pp + q - 1) // q)   # 負のときは下へ切る
                    pf = pp - k * q                                     # 0 < pf < q
                    M = 1
                    for _ in range(pf):
                        M = mul_safe(M, b.num.n)
                        if M is None:
                            break
                    if M is not None:
                        for _ in range(q - pf):
                            M = mul_safe(M, b.num.d)
                            if M is None:
                                break
                    if M is not None:
                        s_out, m = 1, M      # M = s^q * m（m は q 乗の因数を持たない）
                        f = 2
                        while f * f <= m and f < 4096:
                            pw = 1
                            ovf = False
                            for _ in range(q):
                                pw *= f
                                if pw > m:
                                    ovf = True
                                    break
                            if ovf:
                                break        # これより大きい f では q 乗が中身を超える
                            while m % pw == 0:
                                m //= pw
                                s_out *= f
                            f += 1
                        coef = rpow(b.num, k) * Rat(s_out, b.num.d)
                        if m == 1:
                            return num(coef)
                        rest = raw(POW, [num(Rat(m)), num(Rat(1, q))])
                        if coef.is_one():
                            return rest
                        return mul_n([num(coef), rest])
    # **a^(log_a M) = M**（指数と対数は逆の操作）。log(2, x) = log(2, 5) を解くと
    # x = 2^(log_2 5) が出るので、ここで畳まないと答えが 5 にならない。
    if is_num(b) and b.num.n > 0:
        k, core = Rat(1), p
        if core.k == MUL and len(core.kids) == 2 and is_num(core.kids[0]):
            k, core = core.kids[0].num, core.kids[1]
        if (core.k == FN and core.name == "log" and len(core.kids) == 2
                and is_num(core.kids[0]) and core.kids[0].num == b.num):
            return pow_e(core.kids[1], num(k))
    if b.k == POW:                                            # (a^m)^n = a^(mn)
        inner = b.kids[1]
        # **内側が整数でないなら畳んでよい**（内側が根なら底は 0 以上でしか定義されない）。
        # 内側が整数で外側が分数のときは畳めない（sqrt(x^2) は |x|）。C++ の pow_e と同じ。
        # これが無いと `sqrt(y)/y` と `1/sqrt(y)` が別の木のまま同じ印字になる。
        if is_num(inner) and is_num(p) and (
                (inner.num.is_int() and p.num.is_int()) or not inner.num.is_int()):
            return pow_e(b.kids[0], num(inner.num * p.num))
    if b.k == MUL and is_num(p) and p.num.is_int():            # (ab)^n = a^n b^n
        return mul_n([pow_e(f, p) for f in b.kids])
    return raw(POW, [b, p])


def llgcd(a, b):
    """最大公約数（負も受ける）。"""
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def divisors(v):
    """約数を**小さい順**に並べる（有理根定理で根を探す順を決めるのに使う）。"""
    v = abs(v)
    if v == 0:
        return [1]
    out = []
    d = 1
    while d * d <= v:
        if v % d == 0:
            out.append(d)
            if d != v // d:
                out.append(v // d)
        d += 1
    out.sort()
    return out


def iroot(v, k):
    """v の k 乗根が整数なら返す（対数の底を見つけるのに使う）。C++ の iroot と同じ。"""
    if v < 0 or k <= 0:
        return None
    if v == 0:
        return 0
    r = round(v ** (1.0 / k))
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


def prim_pow(v):
    """v = base^e と書けるうち **e が最大**のものを返す（4 は 2^2 であって 4^1 ではない）。

    これで log の底が一致するかを判定できる: log_4(8) は 4=2^2, 8=2^3 なので 3/2。
    """
    if v.n <= 0:
        return (v, 1)
    for k in range(32, 1, -1):
        rn, rd = iroot(v.n, k), iroot(v.d, k)
        if rn is not None and rd is not None and rn > 0:
            return (Rat(rn, rd), k)
    return (v, 1)


def log_exact(a, x):
    """log_a(x) が有理数になるか（log_2(8)=3、log_4(8)=3/2、log_2(1/8)=-3）。"""
    if a.n <= 0 or x.n <= 0 or a.is_one():
        return None
    if x.is_one():
        return Rat(0)
    ra, ia = prim_pow(a)
    rx, ix = prim_pow(x)
    if ra == rx:
        return Rat(ix, ia)
    if ra == Rat(1) / rx:
        return Rat(-ix, ia)
    return None


def is_pi(e):
    return e.k == FN and e.name == "pi" and not e.kids


def pi_coeff(a):
    """角が c·π の形か（c は有理数）。0 も c = 0 として受ける。"""
    if is_num(a) and a.num.is_zero():
        return Rat(0)
    if is_pi(a):
        return Rat(1)
    if a.k == MUL and len(a.kids) == 2 and is_num(a.kids[0]) and is_pi(a.kids[1]):
        return a.kids[0].num
    return None


def sin12(t):
    """sin(t·π/12) の厳密値（t は 0..23）。15°(t が 12 と互いに素) は返さない。"""
    sign = 1 if t < 12 else -1
    u = t % 12
    if u > 6:
        u = 12 - u                                   # sin は 90° をはさんで対称
    if u == 0:
        v = num(0)
    elif u == 2:
        v = num(Rat(1, 2))                           # 30°
    elif u == 3:
        v = mul_n([num(Rat(1, 2)), pow_e(num(2), num(Rat(1, 2)))])      # 45°
    elif u == 4:
        v = mul_n([num(Rat(1, 2)), pow_e(num(3), num(Rat(1, 2)))])      # 60°
    elif u == 6:
        v = num(1)                                   # 90°
    else:
        return None                                  # 15° 刻みの半端な角は畳まない
    return mul_n([num(-1), v]) if sign < 0 else v


def trig_exact(name, c):
    """c·π の sin / cos / tan を厳密に返す（教科書の値の表）。"""
    d = c.d
    nn = c.n % (2 * d)                               # c を [0, 2) に落とす
    if nn < 0:
        nn += 2 * d
    t12 = Rat(nn, d) * Rat(12)
    if not t12.is_int():
        return None
    t = t12.n                                        # 0..23（15° 単位）
    if t % 12 in (1, 5, 7, 11):
        return None
    if name == "sin":
        return sin12(t)
    if name == "cos":
        return sin12((t + 6) % 24)
    if name == "tan":
        if t in (6, 18):
            return None                              # 90°・270° は定義されない
        sn, cs = sin12(t), sin12((t + 6) % 24)
        if sn is None or cs is None:
            return None
        return mul_n([sn, pow_e(cs, num(-1))])
    return None


def fn_e(name, args):
    args = [simp(a) for a in args]
    if name == "sqrt" and len(args) == 1:
        return pow_e(args[0], num(Rat(1, 2)))
    # 小学校の書き方を「1 つのテキスト」で表すための記法。値としては割り算と足し算に畳む
    # （絵のほうは typeset.present_arith が書かれたとおりに描く）
    if name == "frac" and len(args) == 2:
        return mul_n([args[0], pow_e(args[1], num(-1))])
    if name == "mixed" and len(args) == 3:
        return add_n([args[0], mul_n([args[1], pow_e(args[2], num(-1))])])
    # **常用対数は底 10 を明示した形に直す**（log(x) と log(10, x) を別の木にしない）
    if name == "log" and len(args) == 1:
        return fn_e("log", [num(10), args[0]])
    if name == "log" and len(args) == 2 and is_num(args[0]) and is_num(args[1]):
        v = log_exact(args[0].num, args[1].num)
        if v is not None:
            return num(v)
    # 特別角（30°・45°・60° とその仲間）の三角関数は厳密な値にする
    if len(args) == 1 and name in ("sin", "cos", "tan"):
        c = pi_coeff(args[0])
        if c is not None:
            v = trig_exact(name, c)
            if v is not None:
                return v
    # 階乗・順列・組合せ（数学 A）。**値が決まるものだけ畳む**（n! は n が 0..20 の整数のとき。
    # 21! は int64 に入らないので、そこは畳まずに残す。Python は多倍長だが C++ に合わせる）
    if (name == "fact" and len(args) == 1 and is_num(args[0]) and args[0].num.is_int()
            and 0 <= args[0].num.n <= 20):
        v = Rat(1)
        for i in range(2, args[0].num.n + 1):
            v = v * Rat(i)
        return num(v)
    if (name in ("P", "C") and len(args) == 2 and is_num(args[0]) and is_num(args[1])
            and args[0].num.is_int() and args[1].num.is_int() and args[0].num.n >= 0
            and 0 <= args[1].num.n <= args[0].num.n <= 62):
        n_, k_ = args[0].num.n, args[1].num.n
        v = Rat(1)
        for i in range(k_):
            v = v * Rat(n_ - i)                      # nPr = n(n-1)...(n-k+1)
        if name == "C":
            for i in range(2, k_ + 1):
                v = v / Rat(i)                       # nCr = nPr / k!
        return num(v)
    # exp と ln も逆の操作（exp(ln M) = M、ln(exp M) = M、log(a, a^M) = M）
    if name == "exp" and len(args) == 1:
        k, core = Rat(1), args[0]
        if core.k == MUL and len(core.kids) == 2 and is_num(core.kids[0]):
            k, core = core.kids[0].num, core.kids[1]
        if core.k == FN and core.name == "ln" and len(core.kids) == 1:
            return pow_e(core.kids[0], num(k))
    if (name == "ln" and len(args) == 1 and args[0].k == FN and args[0].name == "exp"
            and len(args[0].kids) == 1):
        return args[0].kids[0]
    if (name == "log" and len(args) == 2 and is_num(args[0]) and args[1].k == POW
            and is_num(args[1].kids[0]) and args[1].kids[0].num == args[0].num):
        return args[1].kids[1]
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
    if e.k == REL:
        return raw(REL, [simp(e.kids[0]), simp(e.kids[1])], e.name)
    if e.k == SYS:
        return raw(SYS, [simp(c) for c in e.kids])
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


def rel(op, a, b):
    """関係式。op は "=" "<" "<=" ">" ">=" のどれか。"""
    return raw(REL, [simp(a), simp(b)], op)


def eq(a, b):
    return rel("=", a, b)


def is_rel(e):
    return e.k == REL


def is_eq(e):
    return e.k == REL and e.name == "="


def flip_op(op):
    """不等号の向きを裏返す。負の数を両辺にかける／割るときに必ず要る。"""
    return {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(op, op)


def sys_of(rels):
    """連立。1 本だけなら包まない（包むと印字が変わる）。"""
    if len(rels) == 1:
        return simp(rels[0])
    return raw(SYS, [simp(c) for c in rels])


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
    if e.k == REL:
        return raw(REL, [expand(e.kids[0]), expand(e.kids[1])], e.name)
    if e.k == SYS:
        return raw(SYS, [expand(c) for c in e.kids])
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


def term_degs(e, out=None):
    """項の中の「変数 -> 次数」（表示の並び替え用）。"""
    if out is None:
        out = {}
    if e.k == SYM:
        out[e.name] = out.get(e.name, 0) + 1
        return out
    if e.k == POW and is_sym(e.kids[0]) and is_num(e.kids[1]) and e.kids[1].num.is_int():
        out[e.kids[0].name] = out.get(e.kids[0].name, 0) + e.kids[1].num.n
        return out
    for c in e.kids:
        term_degs(c, out)
    return out


def _disp_cmp(a, b):
    """表示順の比較（C++ の disp_terms の比較関数と同じ）。

    1. 次数の降順（人は x^2 - 5x + 6 の順で書く）
    2. 同じ次数なら、変数ごとの次数を変数名の順に見て、次数の大きい方を先に
       （教科書は x^2 + 12xy + 36y^2 の順。正規順序だけだと `2x - y` が `-y + 2*x` と出る）
    3. それでも決まらなければ正規順序
    """
    da, db = disp_degree(a), disp_degree(b)
    if da != db:
        return -1 if da > db else 1
    va, vb = term_degs(a), term_degs(b)
    for n in sorted(set(va) | set(vb)):
        ea, eb = va.get(n, 0), vb.get(n, 0)
        if ea != eb:
            return -1 if ea > eb else 1
    return cmp(a, b)


def disp_terms(e):
    import functools
    return sorted(e.kids, key=functools.cmp_to_key(_disp_cmp))


def split_num_den(e):
    """積を「分子の因子」と「分母の因子」に分ける。**印字のためだけ**で、意味の木は変えない。
    組版側（tools/typeset.py の split_frac）と同じ考え方。これをやらないと 2/(3x) が
    "2/3*1/x" と出る（読めない）。"""
    up, down = [], []
    fs = list(e.kids) if e.k == MUL else [e]
    for f in fs:
        if f.k == POW and is_num(f.kids[1]) and f.kids[1].num.neg():
            q = f.kids[1].num
            down.append(f.kids[0] if (q.n == -1 and q.d == 1) else pow_e(f.kids[0], num(-q)))
        elif is_num(f) and not f.num.is_int():
            if f.num.n != 1:
                up.append(num(Rat(f.num.n)))
            down.append(num(Rat(f.num.d)))
        else:
            up.append(f)
    return up, down


def prec(e):
    return {SYS: -1, REL: 0, ADD: 1, MUL: 2, POW: 3}.get(e.k, 4)


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
            # **中身が和なら括弧が要る**。a - (2x + 1) を "a - 2*x + 1" と書くと符号が変わる
            # （展開すると和の項に割れるので、--no-expand の道でだけ出ていた）
            s += _wrap(body, 2)
        return s
    if e.k == MUL:
        up, down = split_num_den(e)
        if down:
            nu = num(1) if not up else (up[0] if len(up) == 1 else mul_n(up))
            de = down[0] if len(down) == 1 else mul_n(down)
            return _wrap(nu, 2) + "/" + _wrap(de, 3)
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
        # 負の指数は分数で書く（LaTeX 側と組版側に合わせる）
        if is_num(p) and p.num.neg():
            den = _wrap(b, 3) if (p.num.n == -1 and p.num.d == 1) else _wrap(pow_e(b, num(-p.num)), 3)
            return "1/" + den
        # 分数・負の指数は括弧が必須。"2^1/2" は自分のパーサで (2^1)/2 に読めてしまう
        need = (not is_num(p)) or (not p.num.is_int()) or p.num.neg()
        ps = "(" + to_infix(p) + ")" if need else to_infix(p)
        # **底が負の数や分数のときも括弧が要る**。(1/2)^n を "1/2^(n)" と書くと 1/(2^n) に、
        # (-2)^n を "-2^(n)" と書くと -(2^n) に読み戻ってしまう（等比数列の公比でよく出る）。
        bneed = is_num(b) and (b.num.neg() or not b.num.is_int())
        return ("(" + to_infix(b) + ")" if bneed else _wrap(b, 4)) + "^" + ps
    if e.k == FN:
        if not e.kids:
            return e.name                            # 定数（pi）は括弧を付けない
        return e.name + "(" + ", ".join(to_infix(c) for c in e.kids) + ")"
    if e.k == REL:
        return to_infix(e.kids[0]) + " " + e.name + " " + to_infix(e.kids[1])
    if e.k == SYS:
        # 連立は ", " で並べる（この形をパーサが読み戻せる = 往復不変が Sys でも成り立つ）
        return ", ".join(to_infix(c) for c in e.kids)
    return "?"


def to_latex(e):
    if e.k == NUM:
        if e.num.is_int():
            return str(e.num)
        # **負の分数はマイナスを前に出す**（-1/2 は \frac{-1}{2} ではなく -\frac{1}{2}）
        f = "\\frac{%d}{%d}" % (abs(e.num.n), e.num.d)
        return "-" + f if e.num.neg() else f
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
            s += "(" + to_latex(body) + ")" if body.k == ADD else to_latex(body)
        return s
    if e.k == MUL:
        up, down = split_num_den(e)
        if down:
            nu = num(1) if not up else (up[0] if len(up) == 1 else mul_n(up))
            de = down[0] if len(down) == 1 else mul_n(down)
            return "\\frac{" + to_latex(nu) + "}{" + to_latex(de) + "}"
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
        # 負の指数は分数で書く（-1 だけでなく -1/2 なども。往復で表示が変わらないように）
        if is_num(p) and p.num.neg():
            inner = b if (p.num.n == -1 and p.num.d == 1) else pow_e(b, num(-p.num))
            return "\\frac{1}{" + to_latex(inner) + "}"
        bs = to_latex(b)
        if b.k in (ADD, MUL, POW) or (is_num(b) and (b.num.neg() or not b.num.is_int())):
            bs = "(" + bs + ")"                        # (-2)^n を -2^n と書かない
        return bs + "^{" + to_latex(p) + "}"
    if e.k == FN:
        if not e.kids:
            return "\\" + e.name                     # \pi
        if e.name == "fact" and len(e.kids) == 1:
            return to_latex(e.kids[0]) + "!"
        if e.name in ("P", "C") and len(e.kids) == 2:
            return "{}_{" + to_latex(e.kids[0]) + "}" + e.name + "_{" + to_latex(e.kids[1]) + "}"
        # log は底を下付きで書く（log(a, x) -> \log_{a} x）
        if e.name == "log" and len(e.kids) == 2:
            return "\\log_{" + to_latex(e.kids[0]) + "} " + to_latex(e.kids[1])
        # Σ は sum(k, 1, n, 中身) の 4 引数で持ち、印字だけ数学の形にする
        if e.name == "sum" and len(e.kids) == 4:
            return ("\\sum_{" + to_latex(e.kids[0]) + "=" + to_latex(e.kids[1]) + "}^{" +
                    to_latex(e.kids[2]) + "} " + to_latex(e.kids[3]))
        return "\\" + e.name + "(" + ", ".join(to_latex(c) for c in e.kids) + ")"
    if e.k == REL:
        op = {"<=": "\\le", ">=": "\\ge"}.get(e.name, e.name)
        return to_latex(e.kids[0]) + " " + op + " " + to_latex(e.kids[1])
    if e.k == SYS:
        return "\\begin{cases} " + " \\\\ ".join(to_latex(c) for c in e.kids) + " \\end{cases}"
    return "?"


# ---------------------------------------------------------------- 構文解析


FN_NAMES = ("sqrt", "frac", "mixed", "sin", "cos", "tan", "ln", "exp", "abs", "sum",
            "log", "fact", "P", "C")


def is_fn_name(n):
    """関数として扱う名前（これ以外の名前 + 括弧は掛け算）。"""
    return n in FN_NAMES


class Parser:
    """C++ 側の Parser と同じ文法。暗黙の掛け算（5x, 2(x+1)）を受けるのは、
    写真から読んだ式がそう書かれているから。

    **raw のときは畳まない**（小学校の手順を出すため。tools/arith.py 参照）。
    """

    def __init__(self, src):
        self.s = src
        self.i = 0
        self.err = ""
        self.raw = False

    def bin(self, op, a, b):
        """演算 1 つを作る。**raw と通常で道を分けない**（分けると片方だけ直す事故が起きる）。"""
        if self.raw:
            return raw(FN, [a, b], op)
        if op == "op_add":
            return add_n([a, b])
        if op == "op_sub":
            return add_n([a, mul_n([num(-1), b])])
        if op == "op_mul":
            return mul_n([a, b])
        if op == "op_div":
            return mul_n([a, pow_e(b, num(-1))])
        if op == "op_pow":
            return pow_e(a, b)
        return a

    def un(self, op, a):
        if self.raw:
            return raw(FN, [a], op)
        return mul_n([num(-1), a])                    # op_neg

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
        rels = [self.parse_rel()]
        while True:
            self.ws()
            if self.peek(",") or self.peek(";"):        # 連立は "," か ";" で区切る
                if not self.eat(","):
                    self.eat(";")
                rels.append(self.parse_rel())
                continue
            break
        self.ws()
        if self.i < len(self.s) and not self.err:
            self.err = "余分な文字: " + self.s[self.i:]
        if len(rels) == 1:
            return rels[0]
        return raw(SYS, rels)

    def parse_rel(self):
        """関係演算子は 1 段だけ（a < b < c の連鎖は受けない。中学の書き方に無い）。"""
        l = self.parse_add()
        self.ws()
        if self.i + 1 < len(self.s) and self.s[self.i] in "<>" and self.s[self.i + 1] == "=":
            op = self.s[self.i] + "="
            self.i += 2
            return raw(REL, [l, self.parse_add()], op)
        for op in ("<", ">", "="):
            if self.eat(op):
                return raw(REL, [l, self.parse_add()], op)
        return l

    def parse_add(self):
        l = self.parse_mul()
        while True:
            self.ws()
            if self.eat("+"):
                l = self.bin("op_add", l, self.parse_mul())
            elif self.eat("-"):
                l = self.bin("op_sub", l, self.parse_mul())
            else:
                return l

    def eat_str(self, seq):
        """小学校の計算では × と ÷ が字として書かれる。読めるようにしておく。"""
        self.ws()
        if self.s.startswith(seq, self.i):
            self.i += len(seq)
            return True
        return False

    def parse_mul(self):
        l = self.parse_unary()
        while True:
            self.ws()
            if self.eat("*") or self.eat_str("×"):          # * ×
                l = self.bin("op_mul", l, self.parse_unary())
            elif self.eat("/") or self.eat_str("÷"):        # / ÷
                l = self.bin("op_div", l, self.parse_unary())
            elif self.i < len(self.s) and (self.s[self.i].isalpha() or self.s[self.i] == "("
                                          or self.s[self.i] == "{"
                                          or self.s[self.i].isdigit()):
                if self.s[self.i].isdigit() and is_num(l):
                    self.err = "数が続いています"
                    return l
                l = self.bin("op_mul", l, self.parse_unary())
            else:
                return l

    def parse_unary(self):
        self.ws()
        if self.eat("-"):
            return self.un("op_neg", self.parse_unary())
        if self.eat("+"):
            return self.parse_unary()
        return self.parse_pow()

    def parse_pow(self):
        b = self.parse_atom()
        self.ws()
        # **後置の階乗**（5! と書く）。^ より先に付く（3!^2 は (3!)^2）
        while self.peek("!"):
            self.eat("!")
            b = self.un("op_fact", b) if self.raw else fn_e("fact", [b])
            self.ws()
        if self.eat("^"):
            return self.bin("op_pow", b, self.parse_unary())        # 右結合
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
        if self.eat("{"):                                # 小学校の計算は { } も使う
            e = self.parse_add()
            if not self.eat("}"):
                self.err = "閉じ中括弧がありません"
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
        # **|x - 1| の書き方**（教科書はこう書く）。abs(...) と同じ木にする
        if self.peek("|"):
            self.eat("|")
            a = self.parse_add()
            if not self.eat("|"):
                self.err = "絶対値の | が閉じていません"
            return self.un("op_abs", a) if self.raw else fn_e("abs", [a])
        if self.s[self.i].isalpha():
            # 名前は**英字の連なりだけ**（数字は含めない。`x2` は x*2 と読む）
            name = ""
            while self.i < len(self.s) and self.s[self.i].isalpha():
                name += self.s[self.i]
                self.i += 1
            # **円周率は定数**（p*i と読ませない）。2pi や pi/6 は掛け算・割り算として続く
            if name == "pi":
                return fn_e("pi", [])
            # **関数呼び出しは名前が関数のときだけ**。そうしないと `2x(x - 1)` の `x(...)` が
            # 「関数 x の呼び出し」になる（実写の写真でこの形が出て、答えが出せなかった）。
            if self.peek("(") and is_fn_name(name):
                self.eat("(")
                args = [self.parse_add()]
                while self.eat(","):
                    args.append(self.parse_add())
                if not self.eat(")"):
                    self.err = "関数の閉じ括弧がありません"
                # raw のとき: frac(a,b) は 1 つの数として畳む（縦の分数は「割り算をする所」
                # ではない）。mixed(w,a,b) は op_mixed のまま残す（手順に出したい）
                if self.raw and name == "frac" and len(args) == 2:
                    if is_num(args[0]) and is_num(args[1]) and not args[1].num.is_zero():
                        return num(args[0].num / args[1].num)
                    return self.bin("op_div", args[0], args[1])
                if self.raw and name == "mixed" and len(args) == 3:
                    return raw(FN, list(args), "op_mixed")
                return fn_e(name, args)
            # **英字が続いたら 1 文字ずつの変数の積**（`12xy` は 12*x*y。教科書はそう書く）
            if len(name) > 1:
                fs = [sym(c) for c in name[:-1]]
                # **指数は最後の 1 文字にだけ付く**。`xy^2` は x·y^2 であって (xy)^2 ではない
                # （教科書の書き方。ここを間違えると 9xy^2 が 9x^2y^2 になる）
                last = sym(name[-1])
                self.ws()
                if self.peek("^"):
                    self.eat("^")
                    last = self.bin("op_pow", last, self.parse_unary())
                fs.append(last)
                return mul_n(fs)
            return sym(name)
        self.err = "読めない文字: " + self.s[self.i]
        self.i += 1
        return num(0)


def parse_raw(src):
    """**畳まないで読む**（小学校の計算の手順を出すため。arith.eval_steps に渡す）。"""
    p = Parser(src)
    p.raw = True
    e = p.parse_all()
    return e, p.err


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


def to_decimal(r):
    """有理数を小数で書く（**割り切れるときだけ**）。割り切れなければ空文字。

    小学校の計算は答えを小数で書くので `261/10` ではなく `26.1` も見せたい。
    循環小数を勝手に丸めると嘘になるので、10 の冪で割り切れる場合に限る。
    """
    d, digits = r.d, 0
    while d % 2 == 0 and digits < 12:
        d //= 2
        digits += 1
    while d % 5 == 0 and digits < 12:
        d //= 5
        digits += 1
    if d != 1:
        return ""                                   # 3 や 7 が残る = 割り切れない
    den, k = 1, 0
    while den % r.d != 0 and k < 12:
        den *= 10
        k += 1
    if den % r.d != 0:
        return ""
    scaled = r.n * (den // r.d)
    neg = scaled < 0
    t = str(-scaled if neg else scaled)
    if k > 0:
        t = t.rjust(k + 1, "0")
        t = t[:-k] + "." + t[-k:]
        t = t.rstrip("0").rstrip(".")
    return ("-" if neg else "") + t


def subst(e, var, val):
    """変数を式で置き換える（代入法・連立の後半・将来の微分の合成に使う）。"""
    if e.k == SYM:
        return val if e.name == var else e
    if not e.kids:
        return e
    return simp(raw(e.k, [subst(c, var, val) for c in e.kids], e.name))


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
        if e.name == "pi":
            return 3.14159265358979323846
        if e.name == "log" and len(e.kids) == 2:
            return math.log(approx(e.kids[1])) / math.log(approx(e.kids[0]))
        a = approx(e.kids[0]) if e.kids else 0.0
        return {"sin": math.sin, "cos": math.cos, "tan": math.tan, "ln": math.log,
                "exp": math.exp, "abs": abs}.get(e.name, lambda x: x)(a)
    if e.k == REL:
        return approx(e.kids[0]) - approx(e.kids[1])
    return 0.0                                     # 連立に数値はない（呼ぶ側で弾く）


def cli_argv(flags, argv=None):
    """argparse に渡す前に「値を取る旗」と次の語を = でつなぐ。

    argparse は空白を含まない `-x^2+4<0` を**旗**と読んでしまい、エラーで止まる
    （空白があると値として通るので、テストの式にたまたま空白があると気づけない）。
    C++ 側の arg_of は次の語をそのまま値にするので、直さないと同じ入力で結果が変わる。
    """
    import sys as _sys
    argv = list(_sys.argv[1:] if argv is None else argv)
    out = []
    i = 0
    while i < len(argv):
        if argv[i] in flags and i + 1 < len(argv):
            out.append(argv[i] + "=" + argv[i + 1])
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--latex", action="store_true")
    ap.add_argument("--approx", action="store_true")
    ap.add_argument("--no-expand", dest="no_expand", action="store_true")
    a = ap.parse_args(cli_argv(("--expr",)))
    e, err = parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    if not a.no_expand:
        e = expand(e)
    print(to_infix(e))
    # 割り切れる分数は小数でも見せる（小学校の計算は小数で答える）。C++ 側と同じ順序で出す
    if is_num(e) and not e.num.is_int():
        dec = to_decimal(e.num)
        if dec:
            print("小数: %s" % dec)
    if a.latex:
        print("latex: %s" % to_latex(e))
    if a.approx and e.k != NUM:
        print("approx: %.10g" % approx(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
