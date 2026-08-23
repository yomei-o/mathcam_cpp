"""因数分解（Python 側）— pure/factor.hpp の鏡。

手順の名前・文言・答えの形まで C++ と同じにする（tools/parity/factor.py が縛る）。

  python tools/factor.py --expr "x^2 + 5x + 6" --steps
  python tools/factor.py --expr "6x^2y + 9xy^2" --steps
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X       # noqa: E402
import solve as S      # noqa: E402
import seq as Q        # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class Step:
    __slots__ = ("rule", "note", "before", "after")

    def __init__(self, rule, note, before, after):
        self.rule = rule
        self.note = note
        self.before = before
        self.after = after


class Result:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.value = None
        self.steps = []
        self.changed = False


class Mono:
    """項を「有理数の係数」と「変数 -> 次数」に割ったもの（共通因数を探すため）。"""

    __slots__ = ("coef", "pows")

    def __init__(self):
        self.coef = X.Rat(1)
        self.pows = []


def deg_in(m, v):
    for name, d in m.pows:
        if name == v:
            return d
    return 0


def as_mono(t):
    m = Mono()
    fs = list(t.kids) if t.k == X.MUL else [t]
    for f in fs:
        if X.is_num(f):
            m.coef = m.coef * f.num
            continue
        b, p = f, X.num(1)
        if f.k == X.POW:
            b, p = f.kids[0], f.kids[1]
        if not X.is_sym(b) or not X.is_num(p) or not p.num.is_int() or p.num.neg():
            return None
        hit = False
        for i, (name, d) in enumerate(m.pows):
            if name == b.name:
                m.pows[i] = (name, d + p.num.n)
                hit = True
                break
        if not hit:
            m.pows.append((b.name, p.num.n))
    m.pows.sort()
    return m


def mono_e(m):
    fs = [X.num(m.coef)]
    for name, d in m.pows:
        fs.append(X.sym(name) if d == 1 else X.pow_e(X.sym(name), X.num(d)))
    return X.mul_n(fs)


def factor_one_var(e, var):
    """1 変数の多項式を因数分解して (式, 規則名) を返す。分けられなければ None。"""
    c = []
    if not S.poly_coeffs(e, var, c):
        return None
    while len(c) > 1 and c[-1].is_zero():
        c.pop()
    if len(c) < 3:
        return None                                  # 1 次以下は分けない
    f = Q.factor_poly(c, var)
    # **(x - 1)^2 は Mul ではなく Pow になる**（mul_n が同じ因数をまとめるため）。
    # Mul だけを見ていたので x^2 - 2x + 1 が「分けられない」と出ていた。
    nlin = 0
    parts = []
    fs = list(f.kids) if f.k == X.MUL else [f]
    for k in fs:
        if X.is_num(k):
            continue
        if (k.k == X.POW and X.is_num(k.kids[1]) and k.kids[1].num.is_int()
                and k.kids[1].num.n > 1 and k.kids[0].k == X.ADD):
            nlin += k.kids[1].num.n
            parts.extend([k.kids[0]] * k.kids[1].num.n)
            continue
        if k.k != X.ADD:
            return None                              # 分かれていない（元の多項式のまま）
        nlin += 1
        parts.append(k)
    if nlin < 2:
        return None
    deg = len(c) - 1
    if deg > 2:
        return (f, "因数定理")
    if len(parts) == 2 and X.equal(parts[0], parts[1]):
        return (f, "平方の形")
    if c[1].is_zero():
        return (f, "和と差の積")
    return (f, "たすき掛け")


def factor_hom2(e, vx, vy):
    """2 変数の同次 2 次式 a x^2 + b xy + c y^2 を分ける。"""
    a, b, c = X.Rat(0), X.Rat(0), X.Rat(0)
    ts = list(e.kids) if e.k == X.ADD else [e]
    for t in ts:
        m = as_mono(t)
        if m is None:
            return None
        dx, dy = deg_in(m, vx), deg_in(m, vy)
        if dx + dy != 2:
            return None                              # 同次 2 次だけ
        for name, _d in m.pows:
            if name not in (vx, vy):
                return None
        if dx == 2:
            a = a + m.coef
        elif dy == 2:
            c = c + m.coef
        else:
            b = b + m.coef
    if a.is_zero() or not a.is_int() or not b.is_int() or not c.is_int():
        return None
    D = b.n * b.n - 4 * a.n * c.n
    sq = X.iroot(D, 2) if D >= 0 else None
    if sq is None:
        return None                                  # 有理数の範囲で分かれない
    r1, r2 = X.Rat(-b.n + sq, 2 * a.n), X.Rat(-b.n - sq, 2 * a.n)
    f1 = X.add_n([X.mul_n([X.num(r1.d), X.sym(vx)]), X.mul_n([X.num(-r1.n), X.sym(vy)])])
    f2 = X.add_n([X.mul_n([X.num(r2.d), X.sym(vx)]), X.mul_n([X.num(-r2.n), X.sym(vy)])])
    lead = a / (X.Rat(r1.d) * X.Rat(r2.d))
    out = X.mul_n([f1, f2]) if lead.is_one() else X.mul_n([X.num(lead), f1, f2])
    if X.equal(f1, f2):
        return (out, "平方の形")
    if b.is_zero():
        return (out, "和と差の積")
    return (out, "たすき掛け")


def factor(in_e):
    r = Result()
    e = X.expand(in_e)
    r.value = e
    r.ok = True
    if X.is_num(e):
        r.why = "数なので因数分解できません"
        return r

    # 1) 共通因数（係数の最大公約数と、各変数の最小の次数）
    ts = X.disp_terms(e) if e.k == X.ADD else [e]
    ms = []
    all_mono = True
    for t in ts:
        m = as_mono(t)
        if m is None:
            all_mono = False
            break
        ms.append(m)
    rest = e
    common = Mono()
    if all_mono and ms:
        gn, ld = 0, 1
        for m in ms:
            gn = Q.llgcd(gn, m.coef.n)
            ld = ld // Q.llgcd(ld, m.coef.d) * m.coef.d
        g = X.Rat(1) if gn == 0 else X.Rat(gn, ld)
        if ms[0].coef.neg():
            g = -g                                   # 先頭が負なら - もくくり出す
        cm = Mono()
        cm.coef = g
        for v, _d0 in ms[0].pows:
            mn = -1
            for m in ms:
                d = deg_in(m, v)
                mn = d if mn < 0 else min(mn, d)
            if mn > 0:
                cm.pows.append((v, mn))
        if not cm.coef.is_one() or cm.pows:
            ce = mono_e(cm)
            rest = X.expand(X.mul_n([e, X.pow_e(ce, X.num(-1))]))
            if not (X.is_num(ce) and ce.num.is_one()):
                common = cm
                r.steps.append(Step("共通因数でくくる",
                                    "どの項にもある %s を外に出す" % X.to_infix(ce),
                                    e, X.mul_n([ce, rest])))

    # 2) 残りを分ける
    vs = sorted(X.collect_syms(rest))                # 2 変数のとき x を先に見る（符号が揃う）
    inner = rest
    got = None
    if len(vs) == 1:
        got = factor_one_var(rest, vs[0])
    elif len(vs) == 2:
        got = factor_hom2(rest, vs[0], vs[1])
    if got is not None:
        inner, rule = got
        note = ("a^2 - b^2 = (a + b)(a - b)" if rule == "和と差の積" else
                "a^2 ± 2ab + b^2 = (a ± b)^2" if rule == "平方の形" else
                "掛けて定数項、足して 1 次の係数になる 2 数を探す" if rule == "たすき掛け" else
                "代入して 0 になる値から因数を見つける")
        r.steps.append(Step(rule, note, rest, inner))

    ce = mono_e(common)
    trivial = X.is_num(ce) and ce.num.is_one()
    r.value = inner if trivial else X.mul_n([ce, inner])
    r.changed = (got is not None) or not trivial
    if not r.changed:
        r.why = "有理数の範囲ではこれ以上分けられません"
    return r


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def answer_lines(r, latex=False):
    if not r.ok:
        return [r.why]
    out = [X.to_latex(r.value) if latex else X.to_infix(r.value)]
    if not r.changed:
        out.append(r.why)
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
    r = factor(e)
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
