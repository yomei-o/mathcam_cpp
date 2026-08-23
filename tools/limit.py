"""極限（Python 側）— pure/limit.hpp の鏡。

  python tools/limit.py --expr "(x^2 - 1)/(x - 1)" --to 1 --steps
  python tools/limit.py --expr "(2x^2 + 1)/(x^2 - x)" --to inf
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
        self.inf = 0                 # +1: +∞ / -1: -∞ / 0: 収束
        self.diverge = False
        self.steps = []


def div_root(c, a):
    """多項式を (var - a) で割る（0/0 の約分。割り切れるときだけ新しい係数を返す）。"""
    n = len(c)
    if n < 2:
        return None
    b = [X.Rat(0)] * (n - 1)
    b[n - 2] = c[n - 1]
    for i in range(n - 2, 0, -1):
        b[i - 1] = c[i] + a * b[i]
    if not (c[0] + a * b[0]).is_zero():
        return None
    return b


def poly_at(c, a):
    v, pw = X.Rat(0), X.Rat(1)
    for q in c:
        v = v + q * pw
        pw = pw * a
    return v


def limit(f, want_var="", a=None, at_inf=0):
    r = Result()
    vs = X.collect_syms(f)
    r.var = want_var or (vs[0] if vs else "x")
    var = r.var

    up, down = X.split_num_den(f)
    num = X.num(1) if not up else (up[0] if len(up) == 1 else X.mul_n(up))
    den = X.num(1) if not down else (down[0] if len(down) == 1 else X.mul_n(down))

    cn, cd = [], []
    poly = S.poly_coeffs(X.expand(num), var, cn) and S.poly_coeffs(X.expand(den), var, cd)
    if poly:
        while len(cn) > 1 and cn[-1].is_zero():
            cn.pop()
        while len(cd) > 1 and cd[-1].is_zero():
            cd.pop()

    # ---------------- x -> ±∞
    if at_inf:
        if not poly:
            r.why = "x -> 無限大 は分数式のときだけ解けます"
            return r
        dn, dd = len(cn) - 1, len(cd) - 1
        r.steps.append(Step("最高次で割る",
                            "分子と分母を x^%d で割ると、残るのは最高次の係数だけ"
                            % (dd if dd > dn else dn), f, f))
        r.ok = True
        if dn < dd:
            r.steps.append(Step("次数を比べる", "分母のほうが次数が高いので 0 に近づく",
                                f, X.num(0)))
            r.value = X.num(0)
            return r
        if dn == dd:
            v = cn[dn] / cd[dd]
            r.steps.append(Step("次数を比べる", "次数が同じなので最高次の係数の比になる",
                                f, X.num(v)))
            r.value = X.num(v)
            return r
        lead = cn[dn] / cd[dd]
        gap = dn - dd
        sign = -1 if lead.neg() else 1
        if at_inf < 0 and gap % 2 == 1:              # x -> -∞ で奇数次なら向きが変わる
            sign = -sign
        r.steps.append(Step("次数を比べる", "分子のほうが次数が高いので発散する", f, f))
        r.inf = sign
        return r

    # ---------------- 有限の a
    if a is None or not X.is_num(a):
        r.why = "近づく先は数でないと解けません"
        return r
    av = a.num
    dv = X.simp(X.subst(den, var, a))
    nv = X.simp(X.subst(num, var, a))
    if X.is_num(dv) and not dv.num.is_zero():
        v = X.simp(X.subst(f, var, a))
        if not C.has_var(v, var):
            r.steps.append(Step("そのまま代入する", "分母が 0 にならないので、代入するだけでよい",
                                f, v))
            r.ok = True
            r.value = v
            return r
    if X.is_num(dv) and dv.num.is_zero() and X.is_num(nv) and not nv.num.is_zero():
        r.steps.append(Step("分母だけが 0", "分子は 0 でないので、値はどこまでも大きくなる", f, f))
        r.ok = True
        r.diverge = True
        return r

    # 0/0 の形
    if poly and X.is_num(dv) and dv.num.is_zero():
        r.steps.append(Step("0/0 の形",
                            "分子も分母も 0 になるので、共通の因数 (%s - %s) で約分する"
                            % (var, av), f, f))
        cut = 0
        while poly_at(cn, av).is_zero() and poly_at(cd, av).is_zero():
            n2, d2 = div_root(cn, av), div_root(cd, av)
            if n2 is None or d2 is None:
                break
            cn, cd = n2, d2
            cut += 1
        if cut == 0:
            r.why = "約分できませんでした"
            return r
        shown = X.mul_n([S.from_coeffs(cn, var), X.pow_e(S.from_coeffs(cd, var), X.num(-1))])
        r.steps.append(Step("約分する", "%d 回割れる" % cut, f, shown))
        if poly_at(cd, av).is_zero():
            r.steps.append(Step("分母だけが 0", "約分しても分母が 0 なので発散する", shown, shown))
            r.ok = True
            r.diverge = True
            return r
        v = X.simp(X.subst(shown, var, a))
        r.steps.append(Step("代入する", "約分したあとなら代入できる", shown, v))
        r.ok = True
        r.value = v
        return r

    # sin(kx)/(mx) -> k/m（数学 III の基本公式）
    if av.is_zero() and num.k == X.FN and len(num.kids) == 1 and num.name in ("sin", "tan"):
        ab = C.linear_in(num.kids[0], var)
        cd2 = C.linear_in(den, var)
        if (ab is not None and ab[1].is_zero() and not ab[0].is_zero()
                and cd2 is not None and cd2[1].is_zero() and not cd2[0].is_zero()):
            v = X.num(ab[0] / cd2[0])
            r.steps.append(Step("sin x / x の公式",
                                "x -> 0 のとき sin(x)/x -> 1 を使う（中身に合わせて係数を出す）",
                                f, v))
            r.ok = True
            r.value = v
            return r

    r.why = "この形の極限は未対応"
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    if r.diverge:
        return ["発散する（値は定まらない）"]
    if r.inf > 0:
        return ["+∞ に発散する"]
    if r.inf < 0:
        return ["-∞ に発散する"]
    return [X.to_latex(r.value) if latex else X.to_infix(r.value)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--var", default="")
    ap.add_argument("--to", required=True)
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--var", "--to")))
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    at_inf, to = 0, None
    if a.to in ("inf", "+inf"):
        at_inf = 1
    elif a.to == "-inf":
        at_inf = -1
    else:
        to, err = X.parse(a.to)
        if err:
            print("parse error(--to): %s" % err)
            return 1
    r = limit(e, a.var, to, at_inf)
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
