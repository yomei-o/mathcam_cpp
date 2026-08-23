"""解く（Python 側）— pure/solve.hpp の鏡。

本体は答えではなく**手順**である。答えだけなら係数を取り出して解の公式に入れれば済む。
読める手順にするために:

  * 変形の 1 手ごとに「規則の名前・変形前・変形後・一言説明」を残す
  * 正規化（同類項をまとめる・約分する）は手順に出さない。人が紙に書かない操作を並べると
    読めなくなる。出すのは移項・分母を払う・両辺を割る・因数分解・解の公式だけ
  * 因数分解できるなら公式より先に試す。人はそう解くし、手順が短くなる

対応範囲: 変数 1 つの一次・二次方程式、一次不等式、2 元 1 次の連立方程式、連立不等式。

  python tools/solve.py --expr "x^2 - 5x + 6 = 0" --steps
  python tools/solve.py --expr "3x - 5 > 1" --steps
  python tools/solve.py --expr "x + y = 5, 2x - y = 1" --steps
"""
import argparse
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class Step:
    __slots__ = ("rule", "note", "before", "after")

    def __init__(self, rule, note, before, after):
        self.rule = rule
        self.note = note
        self.before = before
        self.after = after


class Range:
    """1 本の範囲（境界が無い側は None）。二次不等式の「または」を表すのに使う。"""

    __slots__ = ("lo", "hi", "lo_eq", "hi_eq")

    def __init__(self, lo=None, hi=None, lo_eq=False, hi_eq=False):
        self.lo, self.hi, self.lo_eq, self.hi_eq = lo, hi, lo_eq, hi_eq


class Solution:
    def __init__(self):
        self.ok = False
        self.why = ""
        # 方程式:   "linear" / "quadratic" / "identity" / "contradiction"
        # 連立方程式: "system" / "dependent" / "contradiction"
        # 不等式:   "inequality" / "all" / "empty" / "point"
        self.kind = ""
        self.var = ""
        self.roots = []
        self.steps = []
        self.vars = []          # 連立で解いた変数の並び
        self.vals = []          # vars と同じ長さ
        self.lo = None          # 不等式の解の範囲（境界が無い側は None）
        self.hi = None
        self.lo_eq = False
        self.hi_eq = False
        # **二次不等式は答えが 2 つの範囲になる**（x < 2 または x > 3）。1 本で済むときは
        # 上の lo/hi を使い、2 本以上のときだけこちらに入れる（C++ の Solution::ranges と同じ）
        self.ranges = []
        # **複素数解**（判別式が負のとき）。実部と虚部の組で持つ。
        # 虚数単位を式木の定数にはしない: `i` は Σ の添字にも使う普通の文字で、パーサで
        # 定数にすると sum(i, 1, n, i^2) が読めなくなる。答えの文字列だけで組む。
        self.croots = []


def poly_coeffs(e, var, out):
    """e を var の多項式として係数に落とす。落とせないときは False。"""
    if e.k == X.NUM:
        if not out:
            out.append(X.Rat(0))
        out[0] = out[0] + e.num
        return True
    if e.k == X.SYM:
        if e.name != var:
            return False
        while len(out) < 2:
            out.append(X.Rat(0))
        out[1] = out[1] + X.Rat(1)
        return True
    if e.k == X.ADD:
        return all(poly_coeffs(c, var, out) for c in e.kids)
    if e.k == X.MUL:
        coef = X.Rat(1)
        deg = 0
        for f in e.kids:
            if X.is_num(f):
                coef = coef * f.num
                continue
            if X.is_sym(f):
                if f.name != var:
                    return False
                deg += 1
                continue
            if (f.k == X.POW and X.is_sym(f.kids[0]) and f.kids[0].name == var
                    and X.is_num(f.kids[1]) and f.kids[1].num.is_int()
                    and f.kids[1].num.n >= 0):
                deg += f.kids[1].num.n
                continue
            return False                            # 1/x や sin(x) が混ざる
        if deg > 8:
            return False
        while len(out) < deg + 1:
            out.append(X.Rat(0))
        out[deg] = out[deg] + coef
        return True
    if e.k == X.POW:
        if (X.is_sym(e.kids[0]) and e.kids[0].name == var and X.is_num(e.kids[1])
                and e.kids[1].num.is_int() and e.kids[1].num.n >= 0):
            d = e.kids[1].num.n
            if d > 8:
                return False
            while len(out) < d + 1:
                out.append(X.Rat(0))
            out[d] = out[d] + X.Rat(1)
            return True
        return False
    return False                                    # Fn / Rel / Sys は対応外


def from_coeffs(c, var):
    """係数から式木に戻す（手順表示で「整理した式」を見せるため）。"""
    terms = []
    for i, q in enumerate(c):
        if q.is_zero():
            continue
        if i == 0:
            terms.append(X.num(q))
        else:
            p = X.sym(var) if i == 1 else X.pow_e(X.sym(var), X.num(i))
            terms.append(X.mul_n([X.num(q), p]))
    return X.num(0) if not terms else X.add_n(terms)


def lin_coeffs(e, vars_):
    """多変数の一次式として見る: e = a[0]*vars[0] + ... + c。二次以上が混ざれば None。"""
    a = [X.Rat(0)] * len(vars_)
    c = X.Rat(0)
    terms = list(e.kids) if e.k == X.ADD else [e]
    for t in terms:
        coef = X.Rat(1)
        which = -1
        fs = list(t.kids) if t.k == X.MUL else [t]
        for f in fs:
            if X.is_num(f):
                coef = coef * f.num
                continue
            if X.is_sym(f):
                if which >= 0:
                    return None                     # x*y は一次ではない
                for i, v in enumerate(vars_):
                    if v == f.name:
                        which = i
                if which < 0:
                    return None
                continue
            return None                             # Pow / Fn が混ざる
        if which < 0:
            c = c + coef
        else:
            a[which] = a[which] + coef
    return a, c


def isqrt_exact(v):
    if v < 0:
        return None
    r = round(math.sqrt(v))
    for c in range(max(0, r - 2), r + 3):
        if c * c == v:
            return c
    return None


def _at(v, i):
    return v[i] if i < len(v) else X.Rat(0)


def _lcm(a, b):
    return a * b // math.gcd(a, b)


def move_note(L, R, var):
    """「文字の項を左辺、数を右辺」に集める 1 手の説明。

    **引く量は左辺の定数で決まる**。両辺の差（左 - 右）で書くと、"3x - 5 > 1" に
    「両辺に 6 を足す」と書いてしまう。6 を足すと 3x + 1 > 7 で、3x > 6 にはならない
    （実際に足すのは 5）。この 1 行を間違えると手順が数学として嘘になる。
    """
    bl, ar = _at(L, 0), _at(R, 1)
    if not ar.is_zero() and not bl.is_zero():
        return "移項", "文字の項を左辺に、数を右辺に集める"
    if not ar.is_zero():
        return "移項", "右辺の %s を左辺に移す" % X.to_infix(X.mul_n([X.num(ar), X.sym(var)]))
    if not bl.is_zero():
        if bl.neg():
            return "移項", "両辺に %s を足す" % (-bl)
        return "移項", "両辺から %s を引く" % bl
    return "整理", "左辺の同類項をまとめる"          # 移すものが無い（まとめただけ）


# ---------------------------------------------------------------- 方程式


def rational_roots(c_in):
    """多項式（低次から）の**有理数の解を全部**取り出す。(解の並び, 残りの多項式) か None。

    有理根定理: 解 p/q は p が定数項の約数、q が最高次係数の約数。
    探す順（分母の小さい順 -> 分子の小さい順 -> 符号）を決めてあるので、両言語で同じ答え。
    """
    c = list(c_in)
    while len(c) > 1 and c[-1].is_zero():
        c.pop()
    if len(c) < 2:
        return None
    L = 1                                            # 分母を払って整数係数にする
    for q in c:
        L = L // X.llgcd(L, q.d) * q.d
    a = [q.n * (L // q.d) for q in c]
    out = []
    while True:
        if len(a) <= 2:
            break                                    # 1 次まで落ちたら終わり
        if a[0] == 0:
            out.append(X.Rat(0))
            a = a[1:]
            continue
        qs, ps = X.divisors(a[-1]), X.divisors(a[0])
        found = False
        for q in qs:
            for p0 in ps:
                for sg in (1, -1):
                    p = sg * p0
                    if X.llgcd(p, q) != 1:
                        continue
                    v, pw = X.Rat(0), X.Rat(1)
                    rt = X.Rat(p, q)
                    for i in range(len(a)):
                        v = v + X.Rat(a[i]) * pw
                        pw = pw * rt
                    if not v.is_zero():
                        continue
                    d = len(a) - 1                   # (q x - p) で割る
                    b = [0] * d
                    b[d - 1] = a[d] // q
                    for i in range(d - 1, 0, -1):
                        b[i - 1] = (a[i] + p * b[i]) // q
                    out.append(rt)
                    a = b
                    found = True
                    break
                if found:
                    break
            if found:
                break
        if not found:
            break
    if len(a) == 2:                                  # 1 次が残ったら、それも解
        out.append(X.Rat(-a[0], a[1]))
        a = [1]
    return (out, [X.Rat(v) for v in a])


def has_v(e, var):
    """var を含むか。"""
    if e.k == X.SYM:
        return e.name == var
    return any(has_v(k, var) for k in e.kids)


def lin_gen(e, var):
    """e = p·var + rest（rest は var を含まない式）。(p, rest) か None。"""
    p = X.Rat(0)
    ks = []
    ts = list(e.kids) if e.k == X.ADD else [e]
    for t in ts:
        if not has_v(t, var):
            ks.append(t)
            continue
        if t.k == X.SYM:
            p = p + X.Rat(1)
            continue
        if t.k == X.MUL:
            c, nv = X.Rat(1), 0
            for f in t.kids:
                if X.is_num(f):
                    c = c * f.num
                elif f.k == X.SYM and f.name == var:
                    nv += 1
                else:
                    return None
            if nv != 1:
                return None
            p = p + c
            continue
        return None
    return (p, X.num(0) if not ks else X.add_n(ks))


def solve_eq(e_in, want_var="", depth=0):
    s = Solution()
    syms = X.collect_syms(e_in)
    if not syms:
        d = X.expand(X.sub(e_in.kids[0], e_in.kids[1]))
        s.ok = True
        s.kind = "identity" if (X.is_num(d) and d.num.is_zero()) else "contradiction"
        return s
    s.var = want_var or syms[0]
    if len(syms) > 1:
        s.why = "変数が 2 つ以上あります（連立にするなら , で区切る）"
        return s

    lhs, rhs = e_in.kids
    x = X.sym(s.var)
    diff = X.expand(X.sub(lhs, rhs))

    c = []
    if not poly_coeffs(diff, s.var, c):
        # 多項式ではない: 指数・対数・三角の形なら、そちらの解き方に回す
        if depth < 4 and solve_special(lhs, rhs, s.var, depth, s):
            return s
        if s.why:
            return s                                 # 解き方は分かったが解が無い等
        s.why = "一次・二次の多項式に落とせません"
        return s
    while len(c) > 1 and c[-1].is_zero():
        c.pop()
    deg = 0 if not c else len(c) - 1

    if deg == 0:
        s.ok = True
        s.kind = "identity" if (not c or c[0].is_zero()) else "contradiction"
        return s

    if deg == 1:
        s.kind = "linear"
        # 一次は「= 0 の形」を経由しない。人は 3x - 5 = 1 を 3x = 6 と書く。
        L, R = [], []
        poly_coeffs(X.expand(lhs), s.var, L)
        poly_coeffs(X.expand(rhs), s.var, R)
        a, b = c[1], c[0]

        cur = e_in
        moved = X.eq(X.mul_n([X.num(a), x]), X.num(-b))
        if not X.equal(moved, e_in):                # 既にその形なら手順に出さない
            rule, note = move_note(L, R, s.var)
            s.steps.append(Step(rule, note, e_in, moved))
            cur = moved

        lcm = _lcm(a.d, b.d)
        if lcm > 1:
            a = a * X.Rat(lcm)
            b = b * X.Rat(lcm)
            after = X.eq(X.mul_n([X.num(a), x]), X.num(-b))
            s.steps.append(Step("分母を払う", "両辺に %d をかける" % lcm, cur, after))
            cur = after

        root = X.num(-b / a)
        if not a.is_one():
            s.steps.append(Step("両辺を割る", "両辺を %s で割る" % a, cur, X.eq(x, root)))
        s.roots.append(root)
        s.ok = True
        return s

    # 二次: まず = 0 の形にしてから、因数分解 -> 解の公式
    if not (X.is_num(rhs) and rhs.num.is_zero()):
        s.steps.append(Step("移項", "右辺を左辺に移して = 0 の形にする",
                            e_in, X.eq(diff, X.num(0))))
    lcm = 1
    for q in c:
        lcm = _lcm(lcm, q.d)
    if lcm > 1:
        before = X.eq(from_coeffs(c, s.var), X.num(0))
        c = [q * X.Rat(lcm) for q in c]
        s.steps.append(Step("分母を払う", "両辺に %d をかける" % lcm, before,
                            X.eq(from_coeffs(c, s.var), X.num(0))))

    if deg == 2:
        s.kind = "quadratic"
        a, b, cc = c[2], c[1], c[0]
        norm = X.eq(from_coeffs(c, s.var), X.num(0))
        disc = b * b - X.Rat(4) * a * cc
        sq = isqrt_exact(disc.n) if disc.is_int() else None

        if sq is not None and a.is_int() and b.is_int() and cc.is_int():
            r1 = (-b + X.Rat(sq)) / (X.Rat(2) * a)
            r2 = (-b - X.Rat(sq)) / (X.Rat(2) * a)
            # 因数の書き方は人に合わせる: 根が 1/3 なら (x - 1/3) ではなく (3x - 1)

            def factor_of(root):
                if root.d == 1:
                    return X.add_n([x, X.num(-root)])
                return X.add_n([X.mul_n([X.num(X.Rat(root.d)), x]), X.num(-X.Rat(root.n))])
            f1, f2 = factor_of(r1), factor_of(r2)
            lead = a / (X.Rat(r1.d) * X.Rat(r2.d))
            factored = X.mul_n([f1, f2]) if lead.is_one() else X.mul_n([X.num(lead), f1, f2])
            s.steps.append(Step("因数分解", "左辺を積の形にする", norm,
                                X.eq(factored, X.num(0))))
            s.steps.append(Step("積が 0",
                                "積が 0 になるのは、どちらかの因数が 0 のとき: %s = 0 または %s = 0"
                                % (X.to_infix(f1), X.to_infix(f2)),
                                X.eq(factored, X.num(0)), X.eq(f1, X.num(0))))
            s.roots.append(X.num(r1))
            if not (r1 == r2):
                s.roots.append(X.num(r2))
            s.ok = True
            return s

        if disc.neg():
            s.steps.append(Step("判別式",
                                "D = b^2 - 4ac = %s < 0 なので実数解はない" % disc, norm, norm))
            # 数学 II の範囲では複素数解を答える。sqrt(-D) を虚部にまわす
            im = X.simp(X.mul_n([X.fn_e("sqrt", [X.num(-disc)]),
                                 X.pow_e(X.num(X.Rat(2) * a), X.num(-1))]))
            re = X.simp(X.mul_n([X.num(-b), X.pow_e(X.num(X.Rat(2) * a), X.num(-1))]))
            s.steps.append(Step("複素数の範囲で解く",
                                "sqrt(%s) を i でくくり出して x = (-b ± sqrt(-D) i) / (2a)" % (-disc),
                                norm, norm))
            s.croots.append((re, im))
            s.croots.append((re, X.simp(X.neg(im))))
            s.ok = True
            return s

        sq_e = X.fn_e("sqrt", [X.num(disc)])
        denom = X.num(X.Rat(2) * a)
        r1 = X.simp(X.mul_n([X.add_n([X.num(-b), sq_e]), X.pow_e(denom, X.num(-1))]))
        r2 = X.simp(X.mul_n([X.add_n([X.num(-b), X.neg(sq_e)]), X.pow_e(denom, X.num(-1))]))
        s.steps.append(Step("解の公式",
                            "a = %s, b = %s, c = %s を x = (-b ± sqrt(b^2 - 4ac)) / (2a) に入れる"
                            % (a, b, cc), norm, X.eq(x, r1)))
        s.roots.append(r1)
        if not X.equal(r1, r2):
            s.roots.append(r2)
        s.ok = True
        return s

    # 3 次以上: まず**因数定理**で 1 次因数に分ける（解が多く出るほうを先に試す）
    norm = X.eq(from_coeffs(c, s.var), X.num(0))
    got = rational_roots(c)
    if got is not None and got[0]:
        lin, rest = got
        fs = [X.add_n([x, X.num(-q)]) if q.d == 1 else
              X.add_n([X.mul_n([X.num(q.d), x]), X.num(-X.Rat(q.n))]) for q in lin]
        remain = from_coeffs(rest, s.var)
        allf = list(fs)
        if not (X.is_num(remain) and remain.num.is_one()):
            allf.append(remain)
        factored = allf[0] if len(allf) == 1 else X.mul_n(allf)
        s.steps.append(Step("因数定理", "代入して 0 になる値から 1 次因数を見つける",
                            norm, X.eq(factored, X.num(0))))
        s.steps.append(Step("積が 0", "積が 0 になるのは、どれかの因数が 0 のとき",
                            X.eq(factored, X.num(0)), X.eq(factored, X.num(0))))
        for q in lin:
            if not any(X.is_num(t) and t.num == q for t in s.roots):
                s.roots.append(X.num(q))
        while len(rest) > 1 and rest[-1].is_zero():
            rest.pop()
        if len(rest) == 3:
            s2 = solve_eq(X.eq(from_coeffs(rest, s.var), X.num(0)), s.var, depth + 1)
            if s2.ok:
                s.steps.extend(s2.steps)
                for t in s2.roots:
                    if not any(X.equal(t, u) for u in s.roots):
                        s.roots.append(t)
                s.croots.extend(s2.croots)
        elif len(rest) > 3:
            s.steps.append(Step("残りの因数",
                                "%s = 0 は 3 次以上なのでここまで" % X.to_infix(remain),
                                norm, norm))
        s.ok = True
        s.kind = "polynomial"
        return s

    # 有理数の解が無かったとき: **x^n = k の形**（2 項式）なら n 乗根をとる
    if all(c[i].is_zero() for i in range(1, len(c) - 1)) and not c[deg].is_zero():
        k = -c[0] / c[deg]
        keq = X.eq(X.pow_e(x, X.num(deg)), X.num(k))
        s.steps.append(Step("移項", "x^%d = %s の形にする" % (deg, k), norm, keq))
        s.ok = True
        s.kind = "polynomial"
        odd = deg % 2 == 1
        if k.is_zero():
            s.steps.append(Step("n 乗根をとる", "0 の n 乗根は 0", keq, X.eq(x, X.num(0))))
            s.roots.append(X.num(0))
            return s
        if not odd and k.neg():
            s.steps.append(Step("n 乗根をとる", "偶数乗が負になる実数は無い", keq, keq))
            return s                                 # 実数解なし
        ak = -k if k.neg() else k
        root = X.pow_e(X.num(ak), X.num(X.Rat(1, deg)))
        s.steps.append(Step("n 乗根をとる", "%d 乗して %s になる数を求める" % (deg, k), keq,
                            X.eq(x, X.neg(root) if k.neg() else root)))
        if odd:
            s.roots.append(X.simp(X.neg(root)) if k.neg() else root)
        else:
            s.roots.append(root)
            s.roots.append(X.simp(X.neg(root)))
        return s

    s.why = "3 次以上は未対応"
    return s


# ---------------------------------------------------------------- 一次不等式


def set_range(r, op, bound):
    """範囲を Solution に入れる（op は最終形の向き。x <= 3 なら hi=3, hi_eq=True）。"""
    if op in ("<", "<="):
        r.hi = bound
        r.hi_eq = (op == "<=")
    else:
        r.lo = bound
        r.lo_eq = (op == ">=")
    r.kind = "inequality"


def quad_roots(a, b, cc, var, steps):
    """a x^2 + b x + c = 0 の実数解を**小さい順**に返す（C++ の slv::quad_roots と同じ）。

    戻り値: (実数解の個数, r1, r2)
    """
    x = X.sym(var)
    norm = X.eq(from_coeffs([cc, b, a], var), X.num(0))
    disc = b * b - X.Rat(4) * a * cc
    if disc.neg():
        steps.append(Step("判別式",
                          "D = b^2 - 4ac = %s < 0 なので、= 0 になる x は無い" % disc,
                          norm, norm))
        return (0, None, None)
    sq = isqrt_exact(disc.n) if disc.is_int() else None
    if sq is not None and a.is_int() and b.is_int() and cc.is_int():
        p = (-b + X.Rat(sq)) / (X.Rat(2) * a)
        q = (-b - X.Rat(sq)) / (X.Rat(2) * a)
        if q < p:
            p, q = q, p

        def factor_of(root):
            if root.d == 1:
                return X.add_n([x, X.num(-root)])
            return X.add_n([X.mul_n([X.num(X.Rat(root.d)), x]), X.num(-X.Rat(root.n))])

        f1, f2 = factor_of(p), factor_of(q)
        lead = a / (X.Rat(p.d) * X.Rat(q.d))
        factored = X.mul_n([f1, f2]) if lead.is_one() else X.mul_n([X.num(lead), f1, f2])
        steps.append(Step("因数分解", "左辺を積の形にする", norm, X.eq(factored, X.num(0))))
        return (1 if p == q else 2, X.num(p), X.num(q))
    sq_e = X.fn_e("sqrt", [X.num(disc)])
    denom = X.num(X.Rat(2) * a)
    e1 = X.simp(X.mul_n([X.add_n([X.num(-b), X.neg(sq_e)]), X.pow_e(denom, X.num(-1))]))
    e2 = X.simp(X.mul_n([X.add_n([X.num(-b), sq_e]), X.pow_e(denom, X.num(-1))]))
    if X.approx(e2) < X.approx(e1):
        e1, e2 = e2, e1
    steps.append(Step("解の公式",
                      "a = %s, b = %s, c = %s を x = (-b ± sqrt(b^2 - 4ac)) / (2a) に入れる"
                      % (a, b, cc), norm, X.eq(x, e1)))
    return (1 if disc.is_zero() else 2, e1, e2)


def solve_quad_ineq(r, c, op, shown):
    """二次不等式（C++ の slv::solve_quad_ineq と同じ規則・同じ文言）。"""
    var = r.var
    x = X.sym(var)
    a, b, cc = c[2], c[1], c[0]
    if a.neg():
        a, b, cc = -a, -b, -cc
        op = X.flip_op(op)
        r.steps.append(Step("両辺を -1 倍",
                            "x^2 の係数を正にする。負の数を掛けるので不等号の向きが変わる",
                            shown, X.rel(op, from_coeffs([cc, b, a], var), X.num(0))))
    nr, p, q = quad_roots(a, b, cc, var, r.steps)
    ge = op in (">", ">=")
    with_eq = op in (">=", "<=")
    r.ok = True
    if nr == 0:
        r.kind = "all" if ge else "empty"
        r.steps.append(Step("グラフの向き",
                            "上に開いた放物線が x 軸より上にあるので、すべての実数で成り立つ"
                            if ge else
                            "上に開いた放物線が x 軸より上にあるので、成り立つ x は無い",
                            shown, shown))
        return
    if nr == 1:
        if ge and with_eq:
            r.kind = "all"
            r.steps.append(Step("グラフの向き",
                                "接するだけなので、= も含めればすべての実数で成り立つ",
                                shown, shown))
            return
        if not ge and not with_eq:
            r.kind = "empty"
            r.steps.append(Step("グラフの向き", "接するだけなので、< 0 になる x は無い",
                                shown, shown))
            return
        if not ge and with_eq:
            r.kind = "point"
            r.roots.append(p)
            r.steps.append(Step("グラフの向き", "接点だけが解", X.eq(x, p), X.eq(x, p)))
            return
        r.ranges.append(Range(None, p, False, False))
        r.ranges.append(Range(p, None, False, False))
        r.kind = "inequality"
        r.steps.append(Step("グラフの向き", "接点では 0 になるので、そこだけ外す", shown, shown))
        return
    r.kind = "inequality"
    if ge:
        r.ranges.append(Range(None, p, False, with_eq))
        r.ranges.append(Range(q, None, with_eq, False))
        r.steps.append(Step("グラフの向き",
                            "上に開いた放物線なので、2 つの解の**外側**で 0 より大きい",
                            shown, shown))
    else:
        r.lo, r.hi, r.lo_eq, r.hi_eq = p, q, with_eq, with_eq
        r.steps.append(Step("グラフの向き",
                            "上に開いた放物線なので、2 つの解の**間**で 0 より小さい",
                            shown, shown))


def solve_ineq(e_in, want_var=""):
    s = Solution()
    op = e_in.name
    syms = X.collect_syms(e_in)
    diff0 = X.expand(X.sub(e_in.kids[0], e_in.kids[1]))    # diff0 op 0
    if not syms:
        v = X.approx(diff0)
        t = (v < 0) if op == "<" else (v <= 0) if op == "<=" else (v > 0) if op == ">" else (v >= 0)
        s.ok = True
        s.kind = "all" if t else "empty"
        return s
    s.var = want_var or syms[0]
    if len(syms) > 1:
        s.why = "変数が 2 つ以上あります（連立にするなら , で区切る）"
        return s

    c = []
    if not poly_coeffs(diff0, s.var, c):
        s.why = "一次式に落とせません"
        return s
    while len(c) > 1 and c[-1].is_zero():
        c.pop()
    deg = 0 if not c else len(c) - 1
    if deg > 2:
        s.why = "三次以上の不等式は未対応"
        return s
    if deg == 2:
        # 二次不等式。まず左辺に寄せた形を見せてから解く
        shown = X.rel(op, from_coeffs(c, s.var), X.num(0))
        if not X.equal(shown, e_in):
            s.steps.append(Step("移項", "右辺を左辺に移して 0 と比べる形にする", e_in, shown))
        solve_quad_ineq(s, c, op, shown)
        return s

    x = X.sym(s.var)
    if deg == 0:                                    # x が消えた（0 < 1 のような形）
        b = c[0] if c else X.Rat(0)
        z = X.Rat(0)
        if op == "<":
            t = b < z
        elif op == "<=":
            t = b < z or b.is_zero()
        elif op == ">":
            t = z < b
        else:
            t = z < b or b.is_zero()
        s.ok = True
        s.kind = "all" if t else "empty"
        return s

    a, b = c[1], c[0]
    # 1) 移項して a x (op) -b の形にする。既にその形なら手順に出さない
    cur = e_in
    after = X.rel(op, X.mul_n([X.num(a), x]), X.num(-b))
    if not X.equal(after, e_in):
        if b.is_zero():
            note = "右辺を左辺に移す"
        elif b.neg():
            note = "両辺に %s を足す" % (-b)
        else:
            note = "両辺から %s を引く" % b
        s.steps.append(Step("移項", note, e_in, after))
        cur = after

    # 2) 分母を払う。かけるのは**正の数**なので不等号の向きは変わらない
    lcm = _lcm(a.d, b.d)
    if lcm > 1:
        a = a * X.Rat(lcm)
        b = b * X.Rat(lcm)
        after = X.rel(op, X.mul_n([X.num(a), x]), X.num(-b))
        s.steps.append(Step("分母を払う",
                            "両辺に %d をかける（正の数なので不等号の向きは変わらない）" % lcm,
                            cur, after))
        cur = after

    # 3) 両辺を a で割る。**負の数で割るときは向きが変わる**（ここが中学の山場）
    bound = -b / a
    if not a.is_one():
        if a.neg():
            op = X.flip_op(op)
            s.steps.append(Step("両辺を割る（負の数）",
                                "両辺を %s で割る。負の数で割るので不等号の向きが変わる" % a,
                                cur, X.rel(op, x, X.num(bound))))
        else:
            s.steps.append(Step("両辺を割る", "両辺を %s で割る" % a, cur,
                                X.rel(op, x, X.num(bound))))
    set_range(s, op, X.num(bound))
    s.ok = True
    return s


# ---------------------------------------------------------------- 連立不等式


def as_ranges(s):
    """解を「範囲の列」に直す（C++ の slv::as_ranges と同じ）。"""
    if s.kind == "empty":
        return []
    if s.kind == "all":
        return [Range()]
    if s.kind == "point":
        return [Range(s.roots[0], s.roots[0], True, True)] if s.roots else []
    if s.ranges:
        return s.ranges
    if s.lo is not None or s.hi is not None:
        return [Range(s.lo, s.hi, s.lo_eq, s.hi_eq)]
    return [Range()]


def range_meet(a, b):
    """2 本の範囲の重なり。空なら None（C++ の slv::range_meet と同じ）。

    **境界の大小は approx で比べる**（sqrt(2) のような無理数が境界に出る）。
    """
    out = Range()
    if a.lo is not None and b.lo is not None:
        xa, xb = X.approx(a.lo), X.approx(b.lo)
        if xa > xb:
            out.lo, out.lo_eq = a.lo, a.lo_eq
        elif xb > xa:
            out.lo, out.lo_eq = b.lo, b.lo_eq
        else:
            out.lo, out.lo_eq = a.lo, (a.lo_eq and b.lo_eq)
    elif a.lo is not None:
        out.lo, out.lo_eq = a.lo, a.lo_eq
    elif b.lo is not None:
        out.lo, out.lo_eq = b.lo, b.lo_eq
    if a.hi is not None and b.hi is not None:
        xa, xb = X.approx(a.hi), X.approx(b.hi)
        if xa < xb:
            out.hi, out.hi_eq = a.hi, a.hi_eq
        elif xb < xa:
            out.hi, out.hi_eq = b.hi, b.hi_eq
        else:
            out.hi, out.hi_eq = a.hi, (a.hi_eq and b.hi_eq)
    elif a.hi is not None:
        out.hi, out.hi_eq = a.hi, a.hi_eq
    elif b.hi is not None:
        out.hi, out.hi_eq = b.hi, b.hi_eq
    if out.lo is not None and out.hi is not None:
        lo, hi = X.approx(out.lo), X.approx(out.hi)
        if hi < lo:
            return None
        if hi == lo and not (out.lo_eq and out.hi_eq):
            return None
    return out


def meet_all(a, b):
    """範囲の列どうしの重なり（「または」を含む答えの共通部分）。"""
    out = []
    for x in a:
        for y in b:
            g = range_meet(x, y)
            if g is not None:
                out.append(g)
    return out


def solve_sys_ineq(rels, want_var=""):
    r = Solution()
    ordn = ["1 つ目", "2 つ目", "3 つ目", "4 つ目"]
    acc = [Range()]                                  # 最初は「すべての実数」
    for i, one in enumerate(rels):
        s = solve_ineq(one, want_var)
        if not s.ok:
            r.why = s.why
            return r
        if not r.var:
            r.var = s.var
        if s.var and s.var != r.var:
            r.why = "変数が揃っていません"
            return r
        label = ordn[i] if i < 4 else "次"
        r.steps.append(Step(label + "の不等式", "まずこれを解く", one, one))
        r.steps.extend(s.steps)
        acc = meet_all(acc, as_ranges(s))
        if not acc:                                  # 1 本でも成り立たなければ全体が解なし
            r.steps.append(Step("共通範囲", "重なりが無いので解なし", X.num(0), X.num(0)))
            r.ok = True
            r.kind = "empty"
            return r
    r.ok = True
    if len(acc) == 1:
        g = acc[0]
        if g.lo is None and g.hi is None:
            r.kind = "all"
            return r
        if g.lo is not None and g.hi is not None and X.approx(g.lo) == X.approx(g.hi):
            r.steps.append(Step("共通範囲", "両端が同じ値なので解は 1 つ",
                                X.eq(X.sym(r.var), g.lo), X.eq(X.sym(r.var), g.lo)))
            r.roots.append(g.lo)
            r.kind = "point"
            return r
        r.lo, r.hi, r.lo_eq, r.hi_eq = g.lo, g.hi, g.lo_eq, g.hi_eq
    else:
        r.ranges = acc
    r.kind = "inequality"
    # 範囲は「x > 2 かつ x <= 5」の 2 本として持つ（a < x <= b の連鎖は木に無い）
    body = X.sym(r.var)
    g0 = acc[0]
    lo_rel = X.rel(">=" if g0.lo_eq else ">", body, g0.lo) if g0.lo is not None else None
    hi_rel = X.rel("<=" if g0.hi_eq else "<", body, g0.hi) if g0.hi is not None else None
    if lo_rel is not None and hi_rel is not None:
        shown = X.sys_of([lo_rel, hi_rel])
    else:
        shown = lo_rel if lo_rel is not None else hi_rel
    if shown is not None:
        r.steps.append(Step("共通範囲", "それぞれの範囲の重なりを取る", shown, shown))
    return r


# ---------------------------------------------------------------- 連立方程式（2 元 1 次）


def lin_eq_tree(a, vars_, rhs):
    """「a x + b y = c」の形に整えたものを式木で返す（手順表示のため）。"""
    ts = [X.mul_n([X.num(q), X.sym(vars_[i])]) for i, q in enumerate(a) if not q.is_zero()]
    l = X.num(0) if not ts else X.add_n(ts)
    return X.eq(l, X.num(rhs))


def solve_system(rels, want_var=""):
    r = Solution()
    if len(rels) != 2:
        r.why = "2 つの式の連立だけ対応しています"
        return r

    vars_ = []
    for e in rels:
        for v in X.collect_syms(e):
            if v not in vars_:
                vars_.append(v)
    # 答えは x, y の順に出す（出てきた順だと "y = 3, x = 2" と並ぶ）
    vars_.sort()
    if len(vars_) != 2:
        r.why = "変数が 1 つしかありません" if len(vars_) < 2 else "3 元以上の連立は未対応"
        return r

    A, C = [], []
    for e in rels:
        got = lin_coeffs(X.expand(X.sub(e.kids[0], e.kids[1])), vars_)
        if got is None:
            r.why = "一次の連立方程式に落とせません"
            return r
        a, c0 = got
        A.append(a)
        C.append(-c0)                               # a x + b y = -c0

    # 0) 整理（入力が既にこの形なら手順に出さない）
    norm = [lin_eq_tree(A[0], vars_, C[0]), lin_eq_tree(A[1], vars_, C[1])]
    in_tree = X.sys_of(list(rels))
    norm_tree = X.sys_of(list(norm))
    if not X.equal(in_tree, norm_tree):
        r.steps.append(Step("整理", "どちらも「x と y の項 = 数」の形に直す",
                            in_tree, norm_tree))

    # 1) 分母を払う（式ごとに）
    for i in range(2):
        l = C[i].d
        for q in A[i]:
            l = _lcm(l, q.d)
        if l > 1:
            A[i] = [q * X.Rat(l) for q in A[i]]
            C[i] = C[i] * X.Rat(l)
            which = "1 つ目" if i == 0 else "2 つ目"
            before = X.sys_of([norm[0], norm[1]])
            norm[i] = lin_eq_tree(A[i], vars_, C[i])
            r.steps.append(Step("分母を払う", "%sの式に %d をかける" % (which, l), before,
                                X.sys_of([norm[0], norm[1]])))

    # 2) 解があるか（行列式）
    det = A[0][0] * A[1][1] - A[1][0] * A[0][1]
    if det.is_zero():
        cross = A[0][0] * C[1] - A[1][0] * C[0]
        cross2 = A[0][1] * C[1] - A[1][1] * C[0]
        r.ok = True
        if cross.is_zero() and cross2.is_zero():
            r.kind = "dependent"
            r.steps.append(Step("係数を比べる", "2 つの式が同じものを表しているので、解は無限にある",
                                norm_tree, norm_tree))
        else:
            r.kind = "contradiction"
            r.steps.append(Step("係数を比べる",
                                "x と y の係数の比が同じで右辺の比だけ違うので、同時に成り立つ値は無い",
                                norm_tree, norm_tree))
        return r

    # 3) 片方の式に文字が 1 つしか無いなら、消す作業は要らない（0 で割る事故も防ぐ）
    single_i = single_v = -1
    for i in range(2):
        nz, w = 0, -1
        for v in range(2):
            if not A[i][v].is_zero():
                nz += 1
                w = v
        if nz == 1 and single_i < 0:
            single_i, single_v = i, w

    # 4) 代入法が自然な形（片方が「y = …」と書かれている）ならそちらを使う
    subst_i = subst_v = -1
    for i in range(2):
        if subst_i >= 0:
            break
        for v in range(2):
            lhs = rels[i].kids[0]
            if X.is_sym(lhs) and lhs.name == vars_[v]:
                if vars_[v] not in X.collect_syms(rels[i].kids[1]):
                    subst_i, subst_v = i, v
                    break

    if single_i >= 0:
        one_var = norm[single_i]
        solved_var = vars_[single_v]
        r.steps.append(Step("そのまま解ける",
                            "%sの式には %s しか無いので、先にこれを解く"
                            % ("1 つ目" if single_i == 0 else "2 つ目", solved_var),
                            X.sys_of([norm[0], norm[1]]), one_var))
    elif subst_i >= 0:
        other = 1 - subst_i
        sv = vars_[subst_v]
        val = rels[subst_i].kids[1]
        one_var = X.eq(X.subst(rels[other].kids[0], sv, val),
                       X.subst(rels[other].kids[1], sv, val))
        solved_var = vars_[1 - subst_v]
        r.steps.append(Step("代入法",
                            "%s = %s を%sの式に入れる"
                            % (sv, X.to_infix(val), "1 つ目" if other == 0 else "2 つ目"),
                            X.sys_of([rels[0], rels[1]]), one_var))
    else:
        # 加減法: 消す変数の係数の絶対値を揃えてから、辺々を足す／引く。
        # 消す変数は**係数を揃えるのが楽な方**（人もそうする）
        elim = 1 if _lcm(abs(A[0][1].n), abs(A[1][1].n)) < _lcm(abs(A[0][0].n),
                                                               abs(A[1][0].n)) else 0
        keep = 1 - elim
        ea, eb = abs(A[0][elim].n), abs(A[1][elim].n)
        L = _lcm(ea, eb)
        m0, m1 = L // ea, L // eb
        if m0 != 1 or m1 != 1:
            before = X.sys_of([norm[0], norm[1]])
            A[0] = [q * X.Rat(m0) for q in A[0]]
            C[0] = C[0] * X.Rat(m0)
            A[1] = [q * X.Rat(m1) for q in A[1]]
            C[1] = C[1] * X.Rat(m1)
            norm[0] = lin_eq_tree(A[0], vars_, C[0])
            norm[1] = lin_eq_tree(A[1], vars_, C[1])
            note = vars_[elim] + " の係数を揃える（"
            note += ("1 つ目を %d 倍" % m0) if m0 != 1 else "1 つ目はそのまま"
            note += ("、2 つ目を %d 倍）" % m1) if m1 != 1 else "、2 つ目はそのまま）"
            r.steps.append(Step("係数を揃える", note, before,
                                X.sys_of([norm[0], norm[1]])))
        same_sign = (A[0][elim].n > 0) == (A[1][elim].n > 0)
        if same_sign:
            a2 = [A[0][v] - A[1][v] for v in range(2)]
            c2 = C[0] - C[1]
        else:
            a2 = [A[0][v] + A[1][v] for v in range(2)]
            c2 = C[0] + C[1]
        one_var = lin_eq_tree(a2, vars_, c2)
        solved_var = vars_[keep]
        r.steps.append(Step("加減法",
                            "辺々を%sと %s が消える" % ("引く" if same_sign else "足す",
                                                       vars_[elim]),
                            X.sys_of([norm[0], norm[1]]), one_var))

    # 5) 1 変数になったら、方程式の解き方をそのまま使う（手順もそのまま継ぎ足す）
    s1 = solve_eq(one_var, solved_var)
    if not s1.ok or len(s1.roots) != 1:
        r.why = "連立の途中で 1 つに決まりませんでした" if s1.ok else s1.why
        return r
    r.steps.extend(s1.steps)
    v1 = s1.roots[0]

    # 6) もう片方は代入して求める。入れる先は「もう片方の文字が入っている式」
    other_var = vars_[1] if vars_[0] == solved_var else vars_[0]
    ov = 0 if vars_[0] == other_var else 1
    src = 1 if A[0][ov].is_zero() else 0
    base = rels[src]
    eq2 = X.eq(X.subst(base.kids[0], solved_var, v1), X.subst(base.kids[1], solved_var, v1))
    r.steps.append(Step("代入",
                        "%s = %s を%sの式に入れる"
                        % (solved_var, X.to_infix(v1), "1 つ目" if src == 0 else "2 つ目"),
                        X.eq(base.kids[0], base.kids[1]), eq2))
    s2 = solve_eq(eq2, other_var)
    if not s2.ok or len(s2.roots) != 1:
        r.why = "連立の途中で 1 つに決まりませんでした" if s2.ok else s2.why
        return r
    r.steps.extend(s2.steps)

    r.kind = "system"
    r.vars = vars_
    r.vals = [v1 if v == solved_var else s2.roots[0] for v in vars_]
    r.ok = True
    return r


# ---------------------------------------------------------------- 入口


# ---------------------------------------------------------------- 指数・対数・三角の方程式


def as_power(e):
    """「数の累乗」の形か（数そのものは指数 1 とみなす）。(底, 指数) か None。"""
    if X.is_num(e):
        return None if e.num.n <= 0 else (e.num, X.num(1))
    if e.k == X.POW and X.is_num(e.kids[0]) and e.kids[0].num.n > 0:
        return (e.kids[0].num, e.kids[1])
    return None


class LogSide:
    """片側を「Σ ci·log(a, fi) + 定数」にまとめたもの。"""

    def __init__(self):
        self.has_log = False
        self.is_ln = False
        self.base = X.Rat(0)
        self.arg = X.num(1)
        self.konst = X.num(0)
        self.args = []


def merge_log_side(side, var):
    """log a + log b = log ab、k log a = log a^k をまとめる（底がそろっているときだけ）。"""
    out = LogSide()
    ks = []
    ts = list(side.kids) if side.k == X.ADD else [side]
    for t in ts:
        if not has_v(t, var):
            ks.append(t)
            continue
        c, core = X.Rat(1), t
        if t.k == X.MUL:                             # 係数つき（2 log(x) など）
            rest = []
            for f in t.kids:
                if X.is_num(f):
                    c = c * f.num
                else:
                    rest.append(f)
            if len(rest) != 1:
                return None
            core = rest[0]
        if not c.is_int() or core.k != X.FN:
            return None
        if core.name == "ln" and len(core.kids) == 1:
            ln_here, a = True, core.kids[0]
        elif core.name == "log" and len(core.kids) == 2:
            if not X.is_num(core.kids[0]) or core.kids[0].num.n <= 0:
                return None
            if out.has_log and (out.is_ln or not (out.base == core.kids[0].num)):
                return None
            ln_here, a = False, core.kids[1]
            out.base = core.kids[0].num
        else:
            return None
        if out.has_log and out.is_ln != ln_here:
            return None
        out.is_ln = ln_here
        out.has_log = True
        out.args.append(a)
        out.arg = X.mul_n([out.arg, X.pow_e(a, X.num(c))])
    out.konst = X.num(0) if not ks else X.add_n(ks)
    return out


def solve_exp(lhs, rhs, var, depth, r):
    # **正の数の累乗は必ず正**（2^x = 0 や 2^x = -1 は解なし）。表を引く前に言う
    for a, b in ((lhs, rhs), (rhs, lhs)):
        if a.k != X.POW or not X.is_num(a.kids[0]) or a.kids[0].num.n <= 0:
            continue
        if not has_v(a.kids[1], var) or not X.is_num(b) or b.num.n > 0:
            continue
        r.steps.append(Step("値の範囲", "正の数の累乗は必ず正なので、この値にはならない",
                            X.eq(lhs, rhs), X.eq(lhs, rhs)))
        r.ok = True
        r.kind = "empty"
        return True
    pa, pb = as_power(lhs), as_power(rhs)
    if pa is None or pb is None:
        return False
    ba, ea = pa
    bb, eb = pb
    if not has_v(ea, var) and not has_v(eb, var):
        return False
    ra, ia = X.prim_pow(ba)
    rb, ib = X.prim_pow(bb)
    # **底をそろえられるなら指数どうしを比べる**（2^(x+1) = 4^x は 2 に寄せて x+1 = 2x）
    if ra == rb and not ra.is_one():
        neq = X.eq(X.mul_n([X.num(ia), ea]), X.mul_n([X.num(ib), eb]))
        r.steps.append(Step("底をそろえる", "両辺を %s の累乗で表す" % ra, X.eq(lhs, rhs), neq))
        r.steps.append(Step("指数を比べる", "底が同じなら指数どうしが等しい", neq, neq))
        s2 = solve_eq(neq, var, depth + 1)
        if not s2.ok:
            return False
        r.steps.extend(s2.steps)
        r.roots = s2.roots
        r.ok = True
        r.kind = s2.kind if s2.kind in ("identity", "contradiction") else "exponential"
        return True
    # 底がそろわない: 片方が数なら両辺の対数をとる（2^x = 3 → x = log_2(3)）
    va = has_v(ea, var)
    other = rhs if va else lhs
    side = ea if va else eb
    abase = ba if va else bb
    if has_v(other, var) or not X.is_num(other) or other.num.n <= 0:
        return False
    pr = lin_gen(side, var)
    if pr is None or pr[0].is_zero():
        return False
    p, rest = pr
    lg = X.fn_e("log", [X.num(abase), other])
    r.steps.append(Step("両辺の対数をとる",
                        "底 %s の対数をとると 指数 = log_%s(%s)"
                        % (abase, abase, X.to_infix(other)),
                        X.eq(lhs, rhs), X.eq(side, lg)))
    r.roots.append(X.simp(X.mul_n([X.add_n([lg, X.neg(rest)]), X.pow_e(X.num(p), X.num(-1))])))
    r.ok = True
    r.kind = "exponential"
    return True


def solve_log_eq(lhs, rhs, var, depth, r):
    L, R = merge_log_side(lhs, var), merge_log_side(rhs, var)
    if L is None or R is None:
        return False
    if not L.has_log and not R.has_log:
        return False
    if L.has_log and R.has_log and (L.is_ln != R.is_ln or (not L.is_ln and not (L.base == R.base))):
        return False
    is_ln = L.is_ln if L.has_log else R.is_ln
    base = L.base if L.has_log else R.base
    if not is_ln and (base.n <= 0 or base.is_one()):
        return False

    # log_a(argL) - log_a(argR) = konstR - konstL  →  argL = argR · a^(その差)
    cdiff = X.simp(X.add_n([R.konst, X.neg(L.konst)]))
    if has_v(cdiff, var):
        return False
    apow = X.fn_e("exp", [cdiff]) if is_ln else X.pow_e(X.num(base), cdiff)
    inner = X.mul_n([L.arg, X.pow_e(R.arg, X.num(-1))])
    merged = X.eq(X.fn_e("ln", [inner]) if is_ln else X.fn_e("log", [X.num(base), inner]), cdiff)
    r.steps.append(Step("対数をまとめる", "log a + log b = log ab、k log a = log a^k",
                        X.eq(lhs, rhs), merged))
    neq = X.eq(L.arg, X.mul_n([R.arg, apow]))
    r.steps.append(Step("対数の定義", "log_a(M) = c は M = a^c と同じ", merged, neq))
    # **中身が var の一次なら、そのまま解ける**。ln(x) = 1 の答えは exp(1) で、これは
    # 有理数の係数に落ちない（poly_coeffs は通らない）ので、こちらの道が要る
    rhsx = X.simp(X.mul_n([R.arg, apow]))
    lg = lin_gen(L.arg, var)
    if not has_v(rhsx, var) and lg is not None and not lg[0].is_zero():
        cand = [X.simp(X.mul_n([X.add_n([rhsx, X.neg(lg[1])]), X.pow_e(X.num(lg[0]), X.num(-1))]))]
    else:
        s2 = solve_eq(neq, var, depth + 1)
        if not s2.ok:
            return False
        r.steps.extend(s2.steps)
        cand = s2.roots

    # **真数条件**（log の中身は正でなければならない）。ここを落とすと嘘の解が混ざる
    all_args = L.args + R.args
    keep = []
    for rt in cand:
        ok = True
        for a in all_args:
            v = X.simp(X.subst(a, var, rt))
            if has_v(v, var) or X.approx(v) <= 1e-12:
                ok = False
                break
        if ok:
            keep.append(rt)
        else:
            r.steps.append(Step("真数条件",
                                "%s = %s は log の中身が正にならないので捨てる"
                                % (var, X.to_infix(rt)), rt, rt))
    r.roots = keep
    r.ok = True
    r.kind = "empty" if not keep else "logarithmic"
    return True


def solve_trig_eq(lhs, rhs, var, r):
    # 片側が sin/cos/tan、もう片側に var が無い
    f, v = lhs, rhs
    if not (f.k == X.FN and len(f.kids) == 1):
        f, v = rhs, lhs
    if not (f.k == X.FN and len(f.kids) == 1):
        return False
    fn = f.name
    if fn not in ("sin", "cos", "tan") or has_v(v, var):
        return False
    lg = lin_gen(f.kids[0], var)                     # 中身は p·var + q·π の形だけ
    if lg is None or lg[0].is_zero():
        return False
    p = lg[0]
    q = X.pi_coeff(lg[1])
    if q is None:
        return False
    vs = X.simp(v)
    # sin と cos は -1..1 を超えたら解なし（表を探す前に言う）
    if fn in ("sin", "cos") and X.is_num(vs) and (X.approx(vs) > 1.0 or X.approx(vs) < -1.0):
        r.steps.append(Step("値の範囲", "%s は -1 以上 1 以下なので、この値にはならない" % fn,
                            X.eq(lhs, rhs), X.eq(lhs, rhs)))
        r.ok = True
        r.kind = "empty"
        return True
    base = []                                        # 合う角（π の何倍か）
    for t in range(24):
        if t % 12 in (1, 5, 7, 11):
            continue
        val = X.trig_exact(fn, X.Rat(t, 12))
        if val is None:
            continue
        if X.equal(X.simp(val), vs):
            base.append(X.Rat(t, 12))
    if not base:
        return False                                 # 教科書の値の表に無い（逆三角関数が要る）
    xs = []
    for b in base:
        for n in range(-64, 65):
            xr = (b + X.Rat(2 * n) - q) / p          # x = xr·π
            if xr.n < 0 or not (xr < X.Rat(2)):      # 0 <= x < 2π（教科書の既定の範囲）
                continue
            if not any(o == xr for o in xs):
                xs.append(xr)
    xs.sort(key=lambda z: z.f())
    r.steps.append(Step("三角方程式",
                        "0 <= %s < 2pi の範囲で、%s がこの値になる角を全部挙げる" % (var, fn),
                        X.eq(lhs, rhs), X.eq(lhs, rhs)))
    for xr in xs:
        r.roots.append(X.num(0) if xr.is_zero()
                       else X.simp(X.mul_n([X.num(xr), X.fn_e("pi", [])])))
    r.ok = True
    r.kind = "empty" if not r.roots else "trig"
    return True


def solve_special(lhs, rhs, var, depth, r):
    if solve_trig_eq(lhs, rhs, var, r):
        return True
    r.steps = []
    if solve_log_eq(lhs, rhs, var, depth, r):
        return True
    r.steps = []
    if solve_exp(lhs, rhs, var, depth, r):
        return True
    r.steps = []
    return False


def solve(e_in, want_var=""):
    r = Solution()
    if e_in.k == X.SYS:
        eqs = ineqs = 0
        for c in e_in.kids:
            if c.k != X.REL:
                r.why = "連立の中に関係式でないものがあります"
                return r
            if c.name == "=":
                eqs += 1
            else:
                ineqs += 1
        if eqs and ineqs:
            r.why = "方程式と不等式を混ぜた連立は未対応"
            return r
        if ineqs:
            return solve_sys_ineq(list(e_in.kids), want_var)
        return solve_system(list(e_in.kids), want_var)
    if e_in.k != X.REL:
        r.why = "方程式ではありません（= も不等号もない）"
        return r
    if e_in.name != "=":
        return solve_ineq(e_in, want_var)
    return solve_eq(e_in, want_var)


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（C++ の answer_lines と同じ）。CLI・パリティが同じ関数を通る。


def show_e(e, latex):
    return X.to_latex(e) if latex else X.to_infix(e)


def one_range(var, g, latex=False):
    """1 本ぶんの範囲の書き方（C++ の slv::one_range と同じ）。"""
    le = " \\le " if latex else " <= "
    ge = " \\ge " if latex else " >= "
    lt, gt = " < ", " > "
    if g.lo is not None and g.hi is not None:
        return (show_e(g.lo, latex) + (le if g.lo_eq else lt) + var
                + (le if g.hi_eq else lt) + show_e(g.hi, latex))
    if g.lo is not None:
        return var + (ge if g.lo_eq else gt) + show_e(g.lo, latex)
    if g.hi is not None:
        return var + (le if g.hi_eq else lt) + show_e(g.hi, latex)
    return "すべての実数"


def range_text(s, latex=False):
    # **答えが 2 つの範囲になることがある**（二次不等式の「または」）
    if s.ranges:
        return " または ".join(one_range(s.var, g, latex) for g in s.ranges)
    le = " \\le " if latex else " <= "
    ge = " \\ge " if latex else " >= "
    lt, gt = " < ", " > "
    if s.lo is not None and s.hi is not None:
        return (show_e(s.lo, latex) + (le if s.lo_eq else lt) + s.var
                + (le if s.hi_eq else lt) + show_e(s.hi, latex))
    if s.lo is not None:
        return s.var + (ge if s.lo_eq else gt) + show_e(s.lo, latex)
    if s.hi is not None:
        return s.var + (le if s.hi_eq else lt) + show_e(s.hi, latex)
    return "すべての実数"


def answer_lines(s, latex=False):
    if not s.ok:
        return [s.why]
    if s.kind == "identity":
        return ["すべての値で成り立つ"]
    if s.kind == "contradiction":
        return ["解なし（矛盾）"]
    if s.kind == "dependent":
        return ["解は無限にある（2 つの式が同じものを表している）"]
    if s.kind == "all":
        return ["すべての実数で成り立つ"]
    if s.kind == "empty":
        return ["解なし"]
    if s.kind == "inequality":
        return [range_text(s, latex)]
    if s.kind == "system":
        return ["%s = %s" % (v, show_e(s.vals[i], latex)) for i, v in enumerate(s.vars)]
    # 複素数解（判別式が負）。**虚数単位は文字列で組む**（式木の定数にはしない）。
    # 実数解と一緒に出す（x^3 + 1 = 0 の答えは -1 と (1 ± sqrt(3) i)/2 の 3 つ）
    if s.croots:
        out = [] if s.roots else ["実数解なし"]
        out += ["%s = %s" % (s.var, show_e(rt, latex)) for rt in s.roots]
        for re, im in s.croots:
            t = "%s = " % s.var
            re0 = X.is_num(re) and re.num.is_zero()
            if not re0:
                t += show_e(re, latex)
            neg = X.approx(im) < 0
            ia = X.simp(X.neg(im)) if neg else im
            ims = show_e(ia, latex)
            # 括弧が要るのは「/ を含む形」と「和」と「分数」だけ（sqrt(3)i はそのままでよい）
            if ia.k in (X.ADD, X.MUL) or (X.is_num(ia) and not ia.num.is_int()):
                ims = "(" + ims + ")"
            if not re0:
                t += " - " if neg else " + "
            elif neg:
                t += "-"
            t += ("" if ims == "1" else ims) + "i"
            out.append(t)
        return out
    if s.kind == "trig" and not s.roots:
        return ["0 <= %s < 2pi に解はありません" % s.var]
    if not s.roots:
        return ["実数解なし"]
    return ["%s = %s" % (s.var, show_e(rt, latex)) for rt in s.roots]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--var", default="")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--var")))
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    s = solve(e, a.var)
    show = X.to_latex if a.latex else X.to_infix
    if not s.ok:
        # **答えの文言は answer_lines だけ**（C++ 側もそこを通る）
        for line in answer_lines(s, a.latex):
            print(line)
        return 1
    if a.steps:
        for i, st in enumerate(s.steps, 1):
            print("%d. [%s] %s" % (i, st.rule, st.note))
            print("   %s" % show(st.after))
    for line in answer_lines(s, a.latex):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
