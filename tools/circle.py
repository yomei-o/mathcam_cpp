"""円の方程式（Python 側）— pure/circle.hpp の鏡。

  python tools/circle.py --expr "x^2 + y^2 - 4x + 2y - 4 = 0" --steps
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X       # noqa: E402
import solve as S      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

Step = S.Step


class Result:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.vx = "x"
        self.vy = "y"
        self.cx = None
        self.cy = None
        self.r2 = None
        self.r = None
        self.standard = None
        self.kind = ""
        self.steps = []


def coeffs(e, vx, vy):
    """e を「a(x^2 + y^2) + bx + cy + d」として係数を取り出す。"""
    a = b = c = d = X.Rat(0)
    ax = ay = X.Rat(0)
    ts = list(e.kids) if e.k == X.ADD else [e]
    for t in ts:
        k, v, deg = X.Rat(1), "", 0
        fs = list(t.kids) if t.k == X.MUL else [t]
        for f in fs:
            if X.is_num(f):
                k = k * f.num
                continue
            bs, p = f, X.num(1)
            if f.k == X.POW:
                bs, p = f.kids[0], f.kids[1]
            if not X.is_sym(bs) or not X.is_num(p) or not p.num.is_int() or p.num.neg():
                return None
            if v and v != bs.name:
                return None                          # xy の項は円にならない
            v = bs.name
            deg += p.num.n
        if not v:
            d = d + k
            continue
        if v not in (vx, vy):
            return None
        if deg == 2:
            if v == vx:
                ax = ax + k
            else:
                ay = ay + k
            continue
        if deg == 1:
            if v == vx:
                b = b + k
            else:
                c = c + k
            continue
        return None                                  # 3 次以上
    if ax.is_zero() or not (ax == ay):
        return None                                  # x^2 と y^2 の係数が同じでないと円でない
    return (ax, b, c, d)


def circle(in_e, want_x="", want_y=""):
    r = Result()
    if in_e.k == X.REL:
        if in_e.name != "=":
            r.why = "= の式にしてください"
            return r
        lhs = X.expand(X.sub(in_e.kids[0], in_e.kids[1]))
    else:
        lhs = X.expand(in_e)
    vs = sorted(X.collect_syms(lhs))
    if len(vs) != 2:
        r.why = "2 変数（x と y）の式にしてください"
        return r
    r.vx = want_x or vs[0]
    r.vy = want_y or vs[1]

    got = coeffs(lhs, r.vx, r.vy)
    if got is None:
        r.why = "円の方程式の形ではありません"
        return r
    a, b, c, d = got
    if not a.is_one():
        r.steps.append(Step("両辺を割る", "x^2 の係数を 1 にする（%s で割る）" % a, in_e, in_e))
        b, c, d = b / a, c / a, d / a
        a = X.Rat(1)
    p, q = -b / X.Rat(2), -c / X.Rat(2)
    rr = p * p + q * q - d                           # 半径の 2 乗
    x1 = X.pow_e(X.add_n([X.sym(r.vx), X.num(-p)]), X.num(2))
    y1 = X.pow_e(X.add_n([X.sym(r.vy), X.num(-q)]), X.num(2))
    r.standard = X.eq(X.add_n([x1, y1]), X.num(rr))
    r.steps.append(Step("平方完成", "x と y をそれぞれ平方完成する", lhs, r.standard))
    r.cx, r.cy, r.r2 = X.num(p), X.num(q), X.num(rr)
    r.ok = True
    if rr.neg():
        r.kind = "図形なし"
        r.steps.append(Step("右辺の符号", "右辺が負なので、この式を満たす点は無い",
                            r.standard, r.standard))
        return r
    if rr.is_zero():
        r.kind = "1 点"
        r.steps.append(Step("右辺の符号", "右辺が 0 なので、中心の 1 点だけ",
                            r.standard, r.standard))
        return r
    r.kind = "円"
    r.r = X.pow_e(X.num(rr), X.num(X.Rat(1, 2)))
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    show = X.to_latex if latex else X.to_infix
    out = [show(r.standard)]
    if r.kind == "図形なし":
        out.append("この式を満たす点はありません")
        return out
    if r.kind == "1 点":
        out.append("1 点 (%s, %s) だけ" % (show(r.cx), show(r.cy)))
        return out
    out.append("中心 (%s, %s)、半径 %s" % (show(r.cx), show(r.cy), show(r.r)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr",)))
    e, err = X.parse(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    r = circle(e)
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
