"""漸化式（Python 側）— pure/recur.hpp の鏡。

  python tools/recur.py --next "2a + 1" --a1 1 --steps
  python tools/recur.py --next "a + n" --a1 1
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X       # noqa: E402
import seq as Q        # noqa: E402
import solve as S      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

Step = Q.Step


class Result:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.type = ""
        self.var = "n"
        self.term = None
        self.sum = None
        self.steps = []


def split_pa(next_e):
    """next を「p·a + rest」に分ける（a は a_n、rest は a を含まない式）。"""
    p = X.Rat(0)
    ks = []
    ts = list(next_e.kids) if next_e.k == X.ADD else [next_e]
    for t in ts:
        if not S.has_v(t, "a"):
            ks.append(t)
            continue
        if t.k == X.SYM and t.name == "a":
            p = p + X.Rat(1)
            continue
        if t.k == X.MUL:
            c, na = X.Rat(1), 0
            for f in t.kids:
                if X.is_num(f):
                    c = c * f.num
                elif f.k == X.SYM and f.name == "a":
                    na += 1
                else:
                    return None                      # a·n のような形は未対応
            if na != 1:
                return None
            p = p + c
            continue
        return None
    return (p, X.num(0) if not ks else X.add_n(ks))


def verify(term, var, next_e, a1, upto=6):
    """一般項が漸化式を満たすか（a_1 から回して確かめる）。"""
    cur = a1
    for i in range(1, upto + 1):
        got = X.simp(X.subst(term, var, X.num(i)))
        if not X.is_num(got) or not (got.num == cur):
            return False
        nx = X.subst(next_e, "a", X.num(cur))
        nx = X.simp(X.subst(nx, var, X.num(i)))
        if not X.is_num(nx):
            return False
        cur = nx.num
    return True


def solve(next_e, a1, want_var="n"):
    r = Result()
    r.var = want_var or "n"
    var = r.var
    n = X.sym(var)
    got = split_pa(next_e)
    if got is None:
        r.why = "a_(n+1) = p a_n + f(n) の形にしてください"
        return r
    p, rest = got
    shown = X.eq(X.sym("a"), next_e)

    if p == X.Rat(1):
        # a_(n+1) = a_n + f(n)。f が定数なら等差、そうでなければ階差
        if not S.has_v(rest, var):
            r.type = "等差型"
            if not X.is_num(rest):
                r.why = "公差が数になりません"
                return r
            d = rest.num
            r.steps.append(Step("等差型", "a_(n+1) - a_n = %s で一定" % d, shown, shown))
            r.term = Q.nice(X.add_n([X.num(a1), X.mul_n([X.num(d), X.add_n([n, X.num(-1)])])]))
            r.steps.append(Step("一般項", "a_n = 初項 + (n - 1)×公差", r.term, r.term))
        else:
            r.type = "階差型"
            r.steps.append(Step("階差型", "a_(n+1) - a_n = %s なので Σ で足す" % X.to_infix(rest),
                                shown, shown))
            fk = X.subst(rest, var, X.sym("k"))
            sm = Q.sigma(fk, "k", X.num(1), X.add_n([n, X.num(-1)]))
            if not sm.ok:
                r.why = sm.why
                return r
            r.steps.extend(sm.steps)
            r.term = Q.nice(X.add_n([X.num(a1), sm.value]))
            r.steps.append(Step("一般項", "a_n = a_1 + Σ[k=1..n-1] f(k)（n >= 2）",
                                r.term, r.term))
    elif X.is_num(rest) and rest.num.is_zero():
        r.type = "等比型"
        r.steps.append(Step("等比型", "a_(n+1) / a_n = %s で一定" % p, shown, shown))
        r.term = X.simp(X.mul_n([X.num(a1), X.pow_e(X.num(p), X.add_n([n, X.num(-1)]))]))
        r.steps.append(Step("一般項", "a_n = 初項 × 公比^(n - 1)", r.term, r.term))
    elif X.is_num(rest):
        # a_(n+1) = p a_n + q。特性方程式 x = px + q の解 c を引くと等比数列になる
        r.type = "特性方程式"
        q = rest.num
        c = q / (X.Rat(1) - p)
        r.steps.append(Step("特性方程式", "x = %sx + %s を解くと x = %s" % (p, q, c),
                            X.eq(X.sym("x"), X.add_n([X.mul_n([X.num(p), X.sym("x")]), X.num(q)])),
                            X.num(c)))
        r.steps.append(Step("等比数列に直す",
                            "a_n - %s は公比 %s の等比数列（初項 %s）" % (c, p, a1 - c),
                            shown, shown))
        r.term = X.simp(X.add_n([X.mul_n([X.num(a1 - c),
                                          X.pow_e(X.num(p), X.add_n([n, X.num(-1)]))]),
                                 X.num(c)]))
        r.steps.append(Step("一般項", "a_n = (a_1 - c)·p^(n-1) + c", r.term, r.term))
    else:
        r.why = "p a_n + q（q は数）か a_n + f(n) の形だけ解けます"
        return r

    if not verify(r.term, var, next_e, a1):
        r.why = "出した一般項が漸化式に合いませんでした"
        return r
    tot = Q.sigma(X.subst(r.term, var, X.sym("k")), "k", X.num(1), n)
    if tot.ok:
        r.sum = tot.value
        r.steps.append(Step("初項から第 n 項までの和",
                            "S_n = Σ[k=1..n] a_k = %s" % X.to_infix(tot.value),
                            r.term, tot.value))
    r.ok = True
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    show = X.to_latex if latex else X.to_infix
    out = [r.type, "一般項: a_%s = %s" % (r.var, show(r.term))]
    if r.sum is not None:
        out.append("和: S_%s = %s" % (r.var, show(r.sum)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--next", dest="nxt", required=True)
    ap.add_argument("--a1", required=True)
    ap.add_argument("--var", default="n")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--next", "--a1", "--var")))
    e, err = X.parse(a.nxt)
    if err:
        print("parse error: %s" % err)
        return 1
    a1, err = X.parse(a.a1)
    if err or not X.is_num(a1):
        print("--a1 は数で書いてください")
        return 1
    r = solve(e, a1.num, a.var)
    show = X.to_latex if a.latex else X.to_infix
    if a.steps:
        for i, st in enumerate(r.steps, 1):
            print("%d. [%s] %s" % (i, st.rule, st.note))
            print("   %s" % show(st.after))
    for line in answer_lines(r, a.latex):
        print(line)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
