"""ベクトル（Python 側）— pure/vector.hpp の鏡。

  python tools/vector.py --a "1, 2" --b "3, 4" --steps
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
        self.a = []
        self.b = []
        self.dot = None
        self.na = None
        self.nb = None
        self.cosv = None
        self.angle = None
        self.sum = None
        self.diff = None
        self.para = False
        self.perp = False
        self.steps = []


def show_vec(v, latex):
    show = X.to_latex if latex else X.to_infix
    return "(" + ", ".join(show(e) for e in v) + ")"


def analyze(a, b):
    r = Result()
    r.a, r.b = a, b
    if len(a) != len(b) or not (2 <= len(a) <= 3):
        r.why = "2 次元か 3 次元で、成分の数をそろえてください"
        return r
    ds = [X.mul_n([a[i], b[i]]) for i in range(len(a))]
    aa = [X.mul_n([a[i], a[i]]) for i in range(len(a))]
    bb = [X.mul_n([b[i], b[i]]) for i in range(len(a))]
    r.dot = X.simp(X.expand(X.add_n(ds)))
    r.na = X.pow_e(X.simp(X.expand(X.add_n(aa))), X.num(X.Rat(1, 2)))
    r.nb = X.pow_e(X.simp(X.expand(X.add_n(bb))), X.num(X.Rat(1, 2)))
    r.sum = [X.simp(X.add_n([a[i], b[i]])) for i in range(len(a))]
    r.diff = [X.simp(X.add_n([a[i], X.neg(b[i])])) for i in range(len(a))]
    r.steps.append(Step("内積", "成分どうしを掛けて足す", r.dot, r.dot))
    r.steps.append(Step("大きさ", "|a| = sqrt(a・a)", r.na, r.na))

    if X.is_num(r.dot) and r.dot.num.is_zero():
        r.perp = True
        r.steps.append(Step("垂直", "内積が 0 なので 2 つのベクトルは垂直", r.dot, r.dot))
    par = True                                       # a1 b2 - a2 b1 = 0（3 次元なら外積が 0）
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            cr = X.simp(X.expand(X.add_n([X.mul_n([a[i], b[j]]),
                                          X.neg(X.mul_n([a[j], b[i]]))])))
            if not (X.is_num(cr) and cr.num.is_zero()):
                par = False
    if par:
        r.para = True
        r.steps.append(Step("平行", "成分の比が等しいので 2 つのベクトルは平行", r.dot, r.dot))

    den = X.simp(X.mul_n([r.na, r.nb]))
    if X.is_num(den) and den.num.is_zero():
        r.ok = True
        return r
    r.cosv = X.simp(X.mul_n([r.dot, X.pow_e(den, X.num(-1))]))
    r.steps.append(Step("なす角", "cos θ = a・b / (|a||b|) = %s" % X.to_infix(r.cosv),
                        r.cosv, r.cosv))
    for t in range(13):                              # 0 <= θ <= π の特別角だけ探す
        if t % 12 in (1, 5, 7, 11):
            continue
        cv = X.trig_exact("cos", X.Rat(t, 12))
        if cv is None or not X.equal(X.simp(cv), r.cosv):
            continue
        r.angle = X.num(0) if t == 0 else X.simp(X.mul_n([X.num(X.Rat(t, 12)),
                                                          X.fn_e("pi", [])]))
        break
    r.ok = True
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    show = X.to_latex if latex else X.to_infix
    out = ["内積: %s" % show(r.dot),
           "大きさ: |a| = %s、|b| = %s" % (show(r.na), show(r.nb)),
           "和: %s、差: %s" % (show_vec(r.sum, latex), show_vec(r.diff, latex))]
    if r.perp:
        out.append("垂直（内積が 0）")
    if r.para:
        out.append("平行（成分の比が等しい）")
    if r.cosv is not None:
        out.append("cos θ = %s" % show(r.cosv))
        if r.angle is not None:
            out.append("なす角 θ = %s" % show(r.angle))
        else:
            out.append("なす角は特別角になりません")
    return out


def parse_vec(s):
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        e, err = X.parse(part)
        if err:
            return (None, err)
        out.append(e)
    return (out, "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    args = ap.parse_args(X.cli_argv(("--a", "--b")))
    a, err = parse_vec(args.a)
    if err:
        print("parse error(--a): %s" % err)
        return 1
    b, err = parse_vec(args.b)
    if err:
        print("parse error(--b): %s" % err)
        return 1
    r = analyze(a, b)
    show = X.to_latex if args.latex else X.to_infix
    if args.steps:
        for i, st in enumerate(r.steps, 1):
            print("%d. [%s] %s" % (i, st.rule, st.note))
            print("   %s" % show(st.after))
    for line in answer_lines(r, args.latex):
        print(line)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
