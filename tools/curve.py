"""関数を調べる（Python 側）— pure/curve.hpp の鏡。接線と極値。

  python tools/curve.py --expr "x^3 - 3x" --steps
  python tools/curve.py --expr "x^2" --at 1
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
        self.d1 = None
        self.d2 = None
        self.crit = []
        self.kinds = []
        self.vals = []
        self.has_at = False
        self.at = None
        self.tangent = None
        self.normal = None
        self.steps = []


def curve(f, want_var="", at=None):
    r = Result()
    vs = X.collect_syms(f)
    r.var = want_var or (vs[0] if vs else "x")
    var = r.var
    x = X.sym(var)

    try:
        r.d1 = X.simp(X.expand(C.diff(f, var)))
    except C.Fail:
        r.why = "この式は微分できません"
        return r
    try:
        r.d2 = X.simp(X.expand(C.diff(r.d1, var)))
    except C.Fail:
        r.d2 = None
    r.steps.append(Step("微分する", "f'(%s) = %s" % (var, X.to_infix(r.d1)), f, r.d1))

    # 接線（--at）。y = f'(a)(x - a) + f(a)
    if at is not None:
        r.has_at = True
        r.at = at
        fa = X.simp(X.subst(f, var, at))
        ma = X.simp(X.subst(r.d1, var, at))
        if C.has_var(fa, var) or C.has_var(ma, var):
            r.why = "接点の値が求まりません"
            return r
        r.tangent = X.expand(X.add_n([X.mul_n([ma, X.add_n([x, X.neg(at)])]), fa]))
        r.steps.append(Step("接線の式",
                            "y = f'(%s)(%s - %s) + f(%s)"
                            % (X.to_infix(at), var, X.to_infix(at), X.to_infix(at)),
                            r.d1, r.tangent))
        # 法線（接線に垂直。傾きが 0 のときは x = a の縦線になるので出さない）
        if not (X.is_num(ma) and ma.num.is_zero()):
            r.normal = X.expand(X.add_n([
                X.mul_n([X.neg(X.pow_e(ma, X.num(-1))), X.add_n([x, X.neg(at)])]), fa]))

    # 極値: f'(x) = 0 を解いて、f'' の符号で見分ける
    s = S.solve(X.eq(r.d1, X.num(0)), var)
    if s.ok and s.roots:
        r.steps.append(Step("f'(x) = 0 を解く", "傾きが 0 になるところを探す",
                            X.eq(r.d1, X.num(0)), X.eq(r.d1, X.num(0))))
        for st in s.steps:                           # 手の型が違うので詰め替える
            r.steps.append(Step(st.rule, st.note, st.before, st.after))
        cs = sorted(s.roots, key=lambda e: X.approx(e))
        for c in cs:
            fv = X.simp(X.subst(f, var, c))
            kind = "判定できない"
            if r.d2 is not None:
                dv = X.simp(X.subst(r.d2, var, c))
                if not C.has_var(dv, var):
                    t = X.approx(dv)
                    if t > 1e-12:
                        kind = "極小"
                    elif t < -1e-12:
                        kind = "極大"
            r.crit.append(c)
            r.kinds.append(kind)
            r.vals.append(fv)
            r.steps.append(Step("増減を調べる",
                                "%s = %s では f''(%s) の符号から %s"
                                % (var, X.to_infix(c), X.to_infix(c), kind),
                                X.eq(x, c), fv))
    elif s.ok:
        r.steps.append(Step("f'(x) = 0 を解く", "傾きが 0 になるところは無いので極値も無い",
                            X.eq(r.d1, X.num(0)), X.eq(r.d1, X.num(0))))
    r.ok = True
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    show = X.to_latex if latex else X.to_infix
    out = ["f'(%s) = %s" % (r.var, show(r.d1))]
    if r.has_at:
        out.append("接線: y = %s" % show(r.tangent))
        if r.normal is not None:
            out.append("法線: y = %s" % show(r.normal))
    if not r.crit:
        out.append("極値なし")
        return out
    for i, c in enumerate(r.crit):
        out.append("%s: %s = %s のとき %s" % (r.kinds[i], r.var, show(c), show(r.vals[i])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--var", default="")
    ap.add_argument("--at", default="")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--var", "--at")))
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    at = None
    if a.at:
        at, err = X.parse(a.at)
        if err:
            print("parse error(--at): %s" % err)
            return 1
    r = curve(e, a.var, at)
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
