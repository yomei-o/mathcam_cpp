"""面積（Python 側）— pure/area.hpp の鏡。定積分の応用。

  python tools/area.py --expr "x^2" --and "x" --steps
  python tools/area.py --expr "x^2 - 1" --from 0 --to 2
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X       # noqa: E402
import calc as C       # noqa: E402
import solve as S      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

Step = C.Step


class Result:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.var = "x"
        self.value = None
        self.cuts = []
        self.steps = []


def area(f, g, want_var="", lo=None, hi=None):
    r = Result()
    vs = sorted(set(X.collect_syms(f) + X.collect_syms(g)))
    r.var = want_var or (vs[0] if vs else "x")
    var = r.var
    d = X.expand(X.sub(f, g))                        # 差。これの符号で上下が決まる

    cuts = []                                        # 交点（f = g の解）と、指定された端
    s = S.solve(X.eq(d, X.num(0)), var)
    if s.ok:
        for t in s.roots:
            if not C.has_var(t, var):
                cuts.append(t)
    if lo is not None:
        cuts.append(lo)
    if hi is not None:
        cuts.append(hi)
    if lo is not None and hi is not None:            # 範囲の外の交点は使わない
        a0, b0 = X.approx(lo), X.approx(hi)
        cuts = [t for t in cuts if a0 - 1e-12 <= X.approx(t) <= b0 + 1e-12]
    cuts.sort(key=lambda e: X.approx(e))
    uniq = []
    for t in cuts:
        if not uniq or not X.equal(uniq[-1], t):
            uniq.append(t)
    cuts = uniq
    if len(cuts) < 2:
        r.why = "囲まれた範囲が決まりません（交点が足りないか、範囲の指定が要ります）"
        return r
    r.cuts = cuts
    r.steps.append(Step("区切りを決める",
                        "交点と端で区切る: %s = %s" % (var, ", ".join(X.to_infix(t) for t in cuts)),
                        d, d))

    parts = []                                       # 各区間で ∫(f - g)、絶対値で足す
    for i in range(len(cuts) - 1):
        ir = C.integrate(d, var, cuts[i], cuts[i + 1])
        if not ir.ok:
            r.why = ir.why
            return r
        v = X.simp(ir.value)
        neg = X.approx(v) < 0
        if neg:
            v = X.simp(X.neg(v))
        r.steps.append(Step("区間ごとに積分する",
                            "∫[%s..%s](上 - 下) = %s%s"
                            % (X.to_infix(cuts[i]), X.to_infix(cuts[i + 1]),
                               "-" if neg else "", X.to_infix(v))
                            + ("（下に出ているので符号を反転）" if neg else ""),
                            d, v))
        parts.append(v)
    r.value = X.simp(X.add_n(parts))
    r.steps.append(Step("足す", "区間ごとの面積を足す", r.value, r.value))
    r.ok = True
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    return ["面積 = %s" % (X.to_latex(r.value) if latex else X.to_infix(r.value))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--and", dest="other", default="0")
    ap.add_argument("--var", default="")
    ap.add_argument("--from", dest="lo", default="")
    ap.add_argument("--to", dest="hi", default="")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--and", "--var", "--from", "--to")))
    f, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    g, err = X.parse(a.other)
    if err:
        print("parse error(--and): %s" % err)
        return 1
    lo = hi = None
    if a.lo:
        lo, err = X.parse(a.lo)
        if err:
            print("parse error(--from): %s" % err)
            return 1
    if a.hi:
        hi, err = X.parse(a.hi)
        if err:
            print("parse error(--to): %s" % err)
            return 1
    r = area(f, g, a.var, lo, hi)
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
