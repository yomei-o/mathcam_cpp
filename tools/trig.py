"""三角関数の変形（Python 側）— pure/trig.hpp の鏡。加法定理・2 倍角・合成。

  python tools/trig.py --expr "sin(x) + sqrt(3)cos(x)" --steps
  python tools/trig.py --expr "sin(2x)" --mode expand
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X       # noqa: E402
import calc as C       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

Step = C.Step


class Result:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.value = None
        self.steps = []
        self.composed = False
        self.amp = None
        self.phase = None


def is_trig(e, name):
    """sin/cos の中身を「1 つの角」として見る。"""
    return e.k == X.FN and e.name == name and len(e.kids) == 1


def expand_once(e):
    """加法定理と 2 倍角を 1 段だけ開く。開けたら (式, 規則名)。"""
    if not (is_trig(e, "sin") or is_trig(e, "cos")):
        return None
    sn = is_trig(e, "sin")
    u = e.kids[0]
    # n 倍角（整数 n >= 2）: n u = u + (n-1)u と見て加法定理に落とす
    if (u.k == X.MUL and len(u.kids) == 2 and X.is_num(u.kids[0])
            and u.kids[0].num.is_int() and u.kids[0].num.n >= 2):
        n = u.kids[0].num.n
        base = u.kids[1]
        a = base
        b = base if n == 2 else X.mul_n([X.num(n - 1), base])
        rule = "2 倍角の公式" if n == 2 else "加法定理"
    elif u.k == X.ADD and len(u.kids) >= 2:
        a = u.kids[0]
        rest = list(u.kids[1:])
        b = rest[0] if len(rest) == 1 else X.add_n(rest)
        rule = "加法定理"
    else:
        return None
    if sn:
        out = X.add_n([X.mul_n([X.fn_e("sin", [a]), X.fn_e("cos", [b])]),
                       X.mul_n([X.fn_e("cos", [a]), X.fn_e("sin", [b])])])
    else:
        out = X.add_n([X.mul_n([X.fn_e("cos", [a]), X.fn_e("cos", [b])]),
                       X.neg(X.mul_n([X.fn_e("sin", [a]), X.fn_e("sin", [b])]))])
    return (out, rule)


def expand_tree(e):
    """木のどこか 1 か所を開く（上から順に）。"""
    got = expand_once(e)
    if got is not None:
        return got
    for i, k in enumerate(e.kids):
        sub = expand_tree(k)
        if sub is not None:
            ks = list(e.kids)
            ks[i] = sub[0]
            return (X.simp(X.raw(e.k, ks, e.name)), sub[1])
    return None


def split_ab(e):
    """a sin(u) + b cos(u) の係数を式のまま取り出す（sqrt を含んでよい）。"""
    if e.k != X.ADD:
        return None
    a, b, u = X.num(0), X.num(0), None
    for t in e.kids:
        coef, core = [], None
        fs = list(t.kids) if t.k == X.MUL else [t]
        for f in fs:
            if is_trig(f, "sin") or is_trig(f, "cos"):
                if core is not None:
                    return None
                core = f
                continue
            coef.append(f)
        if core is None:
            return None
        if u is None:
            u = core.kids[0]
        elif not X.equal(u, core.kids[0]):
            return None
        c = X.num(1) if not coef else X.mul_n(coef)
        if is_trig(core, "sin"):
            a = X.add_n([a, c])
        else:
            b = X.add_n([b, c])
    if u is None or (X.is_num(a) and a.num.is_zero() and X.is_num(b) and b.num.is_zero()):
        return None
    return (a, b, u)


def transform(in_e, mode="auto"):
    r = Result()
    r.value = in_e
    r.ok = True
    why_compose = ""                                 # 合成は届かなかったときの言い方

    # 1) 合成（a sin u + b cos u -> r sin(u + α)）
    if mode != "expand":
        got = split_ab(X.simp(in_e))
        if got is not None:
            a, b, u = got
            r2 = X.simp(X.expand(X.add_n([X.mul_n([a, a]), X.mul_n([b, b])])))
            amp = X.pow_e(r2, X.num(X.Rat(1, 2)))
            ca = X.simp(X.mul_n([a, X.pow_e(amp, X.num(-1))]))
            sa = X.simp(X.mul_n([b, X.pow_e(amp, X.num(-1))]))
            for t in range(24):
                if t % 12 in (1, 5, 7, 11):
                    continue
                cv = X.trig_exact("cos", X.Rat(t, 12))
                sv = X.trig_exact("sin", X.Rat(t, 12))
                if cv is None or sv is None:
                    continue
                if not X.equal(X.simp(cv), ca) or not X.equal(X.simp(sv), sa):
                    continue
                # α は -π < α <= π で書く（教科書は sin x - cos x を sqrt(2) sin(x - π/4) と書く）
                tt = t - 24 if t > 12 else t
                al = X.num(0) if tt == 0 else X.simp(X.mul_n([X.num(X.Rat(tt, 12)),
                                                              X.fn_e("pi", [])]))
                val = X.mul_n([amp, X.fn_e("sin", [X.add_n([u, al])])])
                r.steps.append(Step("三角関数の合成",
                                    "a sin x + b cos x = r sin(x + α)。r = sqrt(a^2 + b^2) = %s"
                                    "、cos α = %s、sin α = %s"
                                    % (X.to_infix(amp), X.to_infix(ca), X.to_infix(sa)),
                                    in_e, val))
                r.value = val
                r.composed = True
                r.amp, r.phase = amp, al
                return r
            if True:                                 # 角が特別角でないときの言い方（auto でも使う）
                r.amp = amp
                r.steps.append(Step("三角関数の合成",
                                    "r = sqrt(a^2 + b^2) = %s までは出るが、cos α = %s、"
                                    "sin α = %s に合う特別角が無い"
                                    % (X.to_infix(amp), X.to_infix(ca), X.to_infix(sa)),
                                    in_e, in_e))
                r.why = "α が特別角にならないので、r = %s までしか書けません" % X.to_infix(amp)
                if mode == "compose":
                    return r
                r.steps = []                         # auto のときは開くほうも試す
                why_compose = r.why
                r.why = ""

    # 2) 加法定理・2 倍角で開く
    if mode != "compose":
        cur = X.simp(in_e)
        for _ in range(8):
            got = expand_tree(cur)
            if got is None:
                break
            out = X.simp(X.expand(got[0]))
            r.steps.append(Step(got[1], "%s を開く" % X.to_infix(cur), cur, out))
            cur = out
        if r.steps:
            r.value = cur
            return r

    r.why = why_compose or "この形は変形できません（加法定理・2 倍角・合成のどれにも当てはまらない）"
    r.ok = False
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    return [X.to_latex(r.value) if latex else X.to_infix(r.value)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--mode", default="auto")
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--mode")))
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    r = transform(e, a.mode)
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
