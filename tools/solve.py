"""解く（Python 側）— pure/solve.hpp の鏡。

本体は答えではなく**手順**である。答えだけなら係数を取り出して解の公式に入れれば済む。
読める手順にするために:

  * 変形の 1 手ごとに「規則の名前・変形前・変形後・一言説明」を残す
  * 正規化（同類項をまとめる・約分する）は手順に出さない。人が紙に書かない操作を並べると
    読めなくなる。出すのは移項・分母を払う・両辺を割る・因数分解・解の公式だけ
  * 因数分解できるなら公式より先に試す。人はそう解くし、手順が短くなる

  python tools/solve.py --expr "x^2 - 5x + 6 = 0" --steps
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
        self.kind = ""
        self.var = ""
        self.roots = []
        self.steps = []


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
        coef, deg = X.Rat(1), 0
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
                    and X.is_num(f.kids[1]) and f.kids[1].num.is_int() and f.kids[1].num.n >= 0):
                deg += f.kids[1].num.n
                continue
            return False                      # 1/x や sin(x) が混ざる
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
    return False


def from_coeffs(c, var):
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


def isqrt_exact(v):
    if v < 0:
        return None
    r = round(math.sqrt(v))
    for c in range(max(0, r - 2), r + 3):
        if c * c == v:
            return c
    return None


def solve(e_in, want_var=""):
    s = Solution()
    if e_in.k != X.EQ:
        s.why = "方程式ではありません（= がない）"
        return s

    syms = X.collect_syms(e_in)
    if not syms:
        d = X.expand(X.sub(e_in.kids[0], e_in.kids[1]))
        s.ok = True
        s.kind = "identity" if (X.is_num(d) and d.num.is_zero()) else "contradiction"
        return s
    s.var = want_var or syms[0]
    if len(syms) > 1:
        s.why = "変数が 2 つ以上あります（連立は未対応）"
        return s

    lhs, rhs = e_in.kids
    diff = X.expand(X.sub(lhs, rhs))
    if not (X.is_num(rhs) and rhs.num.is_zero()):
        s.steps.append(Step("移項", "右辺を左辺に移して = 0 の形にする",
                            e_in, X.eq(diff, X.num(0))))

    c = []
    if not poly_coeffs(diff, s.var, c):
        s.why = "一次・二次の多項式に落とせません"
        return s
    while len(c) > 1 and c[-1].is_zero():
        c.pop()
    deg = 0 if not c else len(c) - 1

    lcm = 1
    for q in c:
        lcm = lcm * q.d // math.gcd(lcm, q.d)
    if lcm > 1:
        before = X.eq(from_coeffs(c, s.var), X.num(0))
        c = [q * X.Rat(lcm) for q in c]
        s.steps.append(Step("分母を払う", "両辺に %d をかける" % lcm, before,
                            X.eq(from_coeffs(c, s.var), X.num(0))))

    if deg == 0:
        s.ok = True
        s.kind = "identity" if (not c or c[0].is_zero()) else "contradiction"
        return s

    if deg == 1:
        s.kind = "linear"
        a, b = c[1], c[0]
        before = X.eq(from_coeffs(c, s.var), X.num(0))
        if not b.is_zero():
            s.steps.append(Step("移項", "両辺から %s を引く" % b,
                                before, X.eq(from_coeffs([X.Rat(0), a], s.var), X.num(-b))))
        root = X.num(-b / a)
        if not a.is_one():
            s.steps.append(Step("両辺を割る", "両辺を %s で割る" % a,
                                X.eq(X.mul_n([X.num(a), X.sym(s.var)]), X.num(-b)),
                                X.eq(X.sym(s.var), root)))
        s.roots.append(root)
        s.ok = True
        return s

    if deg == 2:
        s.kind = "quadratic"
        a, b, cc = c[2], c[1], c[0]
        norm = X.eq(from_coeffs(c, s.var), X.num(0))
        disc = b * b - X.Rat(4) * a * cc
        sq = isqrt_exact(disc.n) if disc.is_int() else None
        x = X.sym(s.var)

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
    if s.kind == "identity":
        print("すべての値で成り立つ")
        return 0
    if s.kind == "contradiction":
        print("解なし（矛盾）")
        return 0
    if not s.roots:
        print("実数解なし")
        return 0
    for r in s.roots:
        print("%s = %s" % (s.var, show(r)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
