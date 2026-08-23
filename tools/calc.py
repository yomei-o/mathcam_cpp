"""微分と積分（Python 側）— pure/calc.hpp の鏡。

規則も手順の文言も C++ と同じにする（`tools/parity/calc.py` が CLI の出力を全行突き合わせる）。
何ができるかは pure/calc.hpp の冒頭に書いてある。

  python tools/calc.py --expr "x^3 + 2x" --steps
  python tools/calc.py --expr "3x^2 + 1" --integ --from 0 --to 2 --steps
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class Step:
    __slots__ = ("rule", "note", "before", "after")

    def __init__(self, rule, note, before, after):
        self.rule, self.note, self.before, self.after = rule, note, before, after


class Result:
    __slots__ = ("ok", "why", "value", "steps", "definite", "lo", "hi", "anti")

    def __init__(self):
        self.ok = False
        self.why = ""
        self.value = None
        self.steps = []
        self.definite = False
        self.lo = self.hi = None
        self.anti = None


def has_var(e, var):
    if e.k == X.SYM:
        return e.name == var
    return any(has_var(k, var) for k in e.kids)


def rule_of(e, var):
    """その式に使う規則の名前（C++ の cal::rule_of と同じ）。"""
    if not has_var(e, var):
        return "定数"
    if e.k == X.SYM:
        return "変数そのもの"
    if e.k == X.ADD:
        return "和の微分"
    if e.k == X.POW:
        b = e.kids[0]
        return "x の n 乗" if (b.k == X.SYM and b.name == var) else "合成関数"
    if e.k == X.MUL:
        n = sum(1 for f in e.kids if has_var(f, var))
        return "定数倍" if n <= 1 else "積の微分"
    if e.k == X.FN:
        return "合成関数"
    return "微分"


class Fail(Exception):
    pass


def diff(e, var):
    """微分（C++ の cal::diff と同じ規則）。できない形は Fail を投げる。"""
    if not has_var(e, var):
        return X.num(0)
    if e.k == X.SYM:
        return X.num(1)
    if e.k == X.ADD:
        return X.add_n([diff(k, var) for k in e.kids])
    if e.k == X.MUL:
        terms = []
        for i in range(len(e.kids)):
            fs = [diff(e.kids[j], var) if i == j else e.kids[j] for j in range(len(e.kids))]
            terms.append(X.mul_n(fs))
        return X.add_n(terms)
    if e.k == X.POW:
        b, p = e.kids
        if not has_var(p, var):
            if not X.is_num(p):
                raise Fail("指数が数でない")
            return X.mul_n([p, X.pow_e(b, X.num(p.num - X.Rat(1))), diff(b, var)])
        if not has_var(b, var):
            return X.mul_n([e, X.fn_e("ln", [b]), diff(p, var)])
        raise Fail("底にも指数にも変数がある形は未対応")
    if e.k == X.FN:
        if len(e.kids) != 1:
            raise Fail("この関数の微分は未対応")
        f = e.kids[0]
        inner = diff(f, var)
        n = e.name
        if n == "sin":
            return X.mul_n([X.fn_e("cos", [f]), inner])
        if n == "cos":
            return X.mul_n([X.num(-1), X.fn_e("sin", [f]), inner])
        if n == "tan":
            return X.mul_n([X.pow_e(X.fn_e("cos", [f]), X.num(-2)), inner])
        if n == "ln":
            return X.mul_n([X.pow_e(f, X.num(-1)), inner])
        if n == "exp":
            return X.mul_n([e, inner])
        raise Fail("この関数の微分は未対応")
    raise Fail("微分できない形")


def pick_var(e, want):
    if want:
        return want
    vs = X.collect_syms(e)
    return vs[0] if vs else "x"


def differentiate(e, want_var=""):
    r = Result()
    var = pick_var(e, want_var)
    try:
        d = X.simp(diff(e, var))
    except Fail:
        r.ok = False
        r.why = "この式の微分は未対応"
        return r
    r.ok = True
    if e.k == X.ADD:
        r.steps.append(Step("和の微分", "項ごとに微分して足す", e, e))
        for t in X.disp_terms(e):
            dt = X.simp(diff(t, var))
            r.steps.append(Step(rule_of(t, var),
                                "%s を %s で微分すると %s" % (X.to_infix(t), var, X.to_infix(dt)),
                                t, dt))
    else:
        r.steps.append(Step(rule_of(e, var), "%s を %s で微分する" % (X.to_infix(e), var), e, d))
    r.value = X.expand(d)
    return r


def linear_in(e, var):
    """a*var + b の形なら (a, b) を返す。違えば None（C++ の cal::linear_in と同じ）。"""
    a, b = X.Rat(0), X.Rat(0)
    ts = e.kids if e.k == X.ADD else [e]
    for t in ts:
        if not has_var(t, var):
            if not X.is_num(t):
                return None
            b = b + t.num
            continue
        if t.k == X.SYM and t.name == var:
            a = a + X.Rat(1)
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
            a = a + c
            continue
        return None
    return (a, b)


def integ_term(t, var):
    """1 項の積分。(式, 規則名) か None（C++ の cal::integ_term と同じ）。"""
    if not has_var(t, var):
        return (X.mul_n([t, X.sym(var)]), "定数の積分")
    if t.k == X.MUL:
        c, rest = X.Rat(1), []
        for f in t.kids:
            if X.is_num(f):
                c = c * f.num
            else:
                rest.append(f)
        if not (c == X.Rat(1)) and rest:
            sub = integ_term(rest[0] if len(rest) == 1 else X.mul_n(rest), var)
            if sub is None:
                return None
            return (X.mul_n([X.num(c), sub[0]]), sub[1])
    if t.k == X.SYM and t.name == var:
        return (X.mul_n([X.num(X.Rat(1, 2)), X.pow_e(X.sym(var), X.num(2))]), "x の n 乗の積分")
    if t.k == X.POW:
        b, p = t.kids
        if not X.is_num(p) or has_var(p, var):
            return None
        ab = linear_in(b, var)
        if ab is None or ab[0].is_zero():
            return None
        a, c = ab
        if p.num == X.Rat(-1):
            return (X.mul_n([X.num(X.Rat(1) / a), X.fn_e("ln", [X.fn_e("abs", [b])])]),
                    "1/x の積分" if c.is_zero() else "1 次の中身の 1/(ax+b)")
        np = p.num + X.Rat(1)
        return (X.mul_n([X.num(X.Rat(1) / (a * np)), X.pow_e(b, X.num(np))]),
                "x の n 乗の積分" if b.k == X.SYM else "1 次の中身の n 乗")
    if t.k == X.FN and len(t.kids) == 1:
        f = t.kids[0]
        ab = linear_in(f, var)
        if ab is None or ab[0].is_zero():
            return None
        ia = X.num(X.Rat(1) / ab[0])
        if t.name == "sin":
            return (X.mul_n([ia, X.num(-1), X.fn_e("cos", [f])]), "sin の積分")
        if t.name == "cos":
            return (X.mul_n([ia, X.fn_e("sin", [f])]), "cos の積分")
        if t.name == "exp":
            return (X.mul_n([ia, X.fn_e("exp", [f])]), "exp の積分")
    return None


def integrate(e, want_var="", lo=None, hi=None):
    r = Result()
    var = pick_var(e, want_var)
    # まず展開せずに試す（`(2x + 1)^3` は `(2x + 1)^4/8` と書けるほうが教科書的）
    whole = integ_term(e, var)
    if whole is not None:
        ts = [e]
    else:
        e0 = X.expand(e)
        ts = X.disp_terms(e0) if e0.k == X.ADD else [e0]
    if len(ts) > 1:
        r.steps.append(Step("和の積分", "項ごとに積分して足す", X.expand(e), X.expand(e)))
    parts = []
    for t in ts:
        got = integ_term(t, var)
        if got is None:
            r.ok = False
            r.why = "%s の積分は未対応（初等関数で書けない形かもしれない）" % X.to_infix(t)
            return r
        it = X.simp(got[0])
        r.steps.append(Step(got[1], "%s を積分すると %s" % (X.to_infix(t), X.to_infix(it)), t, it))
        parts.append(it)
    anti = X.simp(X.add_n(parts))
    r.ok = True
    r.anti = anti
    if lo is not None and hi is not None:
        r.definite = True
        r.lo, r.hi = lo, hi
        fb = X.simp(X.subst(anti, var, hi))
        fa = X.simp(X.subst(anti, var, lo))
        r.steps.append(Step("上端と下端を入れる",
                            "F(%s) - F(%s) = %s - %s" % (X.to_infix(hi), X.to_infix(lo),
                                                         X.to_infix(fb), X.to_infix(fa)),
                            anti, X.add_n([fb, X.mul_n([X.num(-1), fa])])))
        r.value = X.expand(X.add_n([fb, X.mul_n([X.num(-1), fa])]))
    else:
        r.value = anti
    return r


def answer_lines(r, latex=False, is_integral=False):
    """**答えの文言はここだけ**（C++ の cal::answer_lines と同じ）。"""
    if not r.ok:
        return [r.why]
    v = X.to_latex(r.value) if latex else X.to_infix(r.value)
    if not is_integral or r.definite:
        return [v]
    return [v + " + C"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--var", default="")
    ap.add_argument("--integ", action="store_true")
    ap.add_argument("--from", dest="lo", default="")
    ap.add_argument("--to", dest="hi", default="")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--var", "--from", "--to")))
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    lo = hi = None
    if a.lo and a.hi:
        lo, e2 = X.parse(a.lo)
        if e2:
            print("parse error(--from): %s" % e2)
            return 1
        hi, e3 = X.parse(a.hi)
        if e3:
            print("parse error(--to): %s" % e3)
            return 1
    r = integrate(e, a.var, lo, hi) if a.integ else differentiate(e, a.var)
    if a.steps:
        for i, st in enumerate(r.steps, 1):
            print("%d. [%s] %s" % (i, st.rule, st.note))
            print("   %s" % (X.to_latex(st.after) if a.latex else X.to_infix(st.after)))
    for line in answer_lines(r, a.latex, a.integ):
        print(line)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
