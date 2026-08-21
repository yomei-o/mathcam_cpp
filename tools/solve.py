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


def solve_eq(e_in, want_var=""):
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
    if deg > 1:
        s.why = "二次以上の不等式は未対応"
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


def intersect(r, s):
    """2 つの範囲の重なりを取る。境界が同じ値なら**厳しい方**（等号なし）が残る。"""
    if s.lo is not None:
        if r.lo is None or r.lo.num < s.lo.num:
            r.lo, r.lo_eq = s.lo, s.lo_eq
        elif r.lo.num == s.lo.num:
            r.lo_eq = r.lo_eq and s.lo_eq
    if s.hi is not None:
        if r.hi is None or s.hi.num < r.hi.num:
            r.hi, r.hi_eq = s.hi, s.hi_eq
        elif r.hi.num == s.hi.num:
            r.hi_eq = r.hi_eq and s.hi_eq


def solve_sys_ineq(rels, want_var=""):
    r = Solution()
    ordn = ["1 つ目", "2 つ目", "3 つ目", "4 つ目"]
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
        if s.kind == "empty":                       # 1 本でも成り立たなければ全体が解なし
            r.ok = True
            r.kind = "empty"
            return r
        if s.kind == "all":
            continue                                # 常に成り立つ式は範囲を狭めない
        intersect(r, s)

    if r.lo is None and r.hi is None:
        r.ok = True
        r.kind = "all"
        return r
    r.kind = "inequality"
    if r.lo is not None and r.hi is not None:
        lo, hi = r.lo, r.hi
        if hi.num < lo.num or (lo.num == hi.num and not (r.lo_eq and r.hi_eq)):
            r.steps.append(Step("共通範囲", "2 つの範囲に重なりが無いので解なし",
                                X.num(0), X.num(0)))
            r.ok = True
            r.kind = "empty"
            return r
        if lo.num == hi.num:                        # x >= 2 かつ x <= 2 → x = 2 の 1 点
            r.steps.append(Step("共通範囲", "両端が同じ値なので解は 1 つ",
                                X.eq(X.sym(r.var), lo), X.eq(X.sym(r.var), lo)))
            r.roots.append(lo)
            r.ok = True
            r.kind = "point"
            return r
    # 範囲は「x > 2 かつ x <= 5」の 2 本として持つ（a < x <= b の連鎖は木に無い）
    body = X.sym(r.var)
    lo_rel = X.rel(">=" if r.lo_eq else ">", body, r.lo) if r.lo is not None else None
    hi_rel = X.rel("<=" if r.hi_eq else "<", body, r.hi) if r.hi is not None else None
    if lo_rel is not None and hi_rel is not None:
        shown = X.sys_of([lo_rel, hi_rel])
    else:
        shown = lo_rel if lo_rel is not None else hi_rel
    r.steps.append(Step("共通範囲", "それぞれの範囲の重なりを取る", shown, shown))
    r.ok = True
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


def range_text(s, latex=False):
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
    if not s.roots:
        return ["実数解なし"]
    return ["%s = %s" % (s.var, show_e(rt, latex)) for rt in s.roots]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--var", default="")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args()
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    s = solve(e, a.var)
    show = X.to_latex if a.latex else X.to_infix
    if not s.ok:
        print("solve: %s" % s.why)
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
