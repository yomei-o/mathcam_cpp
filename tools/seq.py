"""数列と Σ（Python 側）— pure/seq.hpp の鏡。

手順の名前・文言・答えの形まで C++ と同じにする（tools/parity/seq.py が縛る）。

  python tools/seq.py sum --expr "k^2" --to n --steps
  python tools/seq.py sum --expr "sum(k, 1, n, 3k^2 - k)" --steps
  python tools/seq.py seq --terms "1, 2, 4, 7, 11" --steps
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


class Step:
    __slots__ = ("rule", "note", "before", "after")

    def __init__(self, rule, note, before, after):
        self.rule = rule
        self.note = note
        self.before = before
        self.after = after


def sum_e(var, lo, hi, body):
    """Σ の木。kids = {束縛変数, 下端, 上端, 中身}。印字は to_latex が \\sum_{k=1}^{n} にする。"""
    return X.raw(X.FN, [X.sym(var), lo, hi, body], "sum")


def is_sum(e):
    return e.k == X.FN and e.name == "sum" and len(e.kids) == 4


class Sum:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.value = None
        self.steps = []
        self.var = ""
        self.lo = None
        self.hi = None


# ---------------------------------------------------------------- 因数分解（答えの見た目）


llgcd = X.llgcd                                      # 道具は expr.py に置いてある
divisors = X.divisors                                # （solve.py からも使うため）


def factor_poly(c, var):
    """係数の並び（低次から）を「有理数 × 一次式の積 × 残り」に直す。

    有理根定理で根を**小さい分母・小さい分子から順に**探す（並べる順を決めておかないと
    言語によって因数の出方が変わる）。割り切れた分だけ取り出し、残りはそのまま置く。
    """
    c = list(c)
    while len(c) > 1 and c[-1].is_zero():
        c.pop()
    if not c:
        return X.num(0)
    if len(c) == 1:
        return X.num(c[0])

    L = 1                                              # 分母を払って整数係数にする
    for q in c:
        L = L // llgcd(L, q.d) * q.d
    a = [q.n * (L // q.d) for q in c]
    g = 0
    for v in a:
        g = llgcd(g, v)
    if g == 0:
        return X.num(0)
    a = [v // g for v in a]
    if a[-1] < 0:                                      # 先頭の係数を正にそろえる
        a = [-v for v in a]
        g = -g
    lead = X.Rat(g, L)

    fs = []
    while True:
        if len(a) <= 1:
            break
        if a[0] == 0:                                  # 定数項が 0 なら var でくくれる
            fs.append(X.sym(var))
            a = a[1:]
            continue
        qs, ps = divisors(a[-1]), divisors(a[0])
        found = False
        for q in qs:
            for p0 in ps:
                for s in (1, -1):
                    p = s * p0
                    if llgcd(p, q) != 1:
                        continue
                    v = X.Rat(0)                       # a(p/q) を厳密に計算する
                    r = X.Rat(p, q)
                    pw = X.Rat(1)
                    for i in range(len(a)):
                        v = v + X.Rat(a[i]) * pw
                        pw = pw * r
                    if not v.is_zero():
                        continue
                    d = len(a) - 1                     # (q x - p) で割る
                    b = [0] * d
                    b[d - 1] = a[d] // q
                    for i in range(d - 1, 0, -1):
                        b[i - 1] = (a[i] + p * b[i]) // q
                    fs.append(X.add_n([X.sym(var), X.num(X.Rat(-p))]) if q == 1 else
                              X.add_n([X.mul_n([X.num(X.Rat(q)), X.sym(var)]),
                                       X.num(X.Rat(-p))]))
                    a = b
                    found = True
                    break
                if found:
                    break
            if found:
                break
        if not found:
            break
    rest = [X.Rat(v) for v in a]
    parts = []
    rp = S.from_coeffs(rest, var)
    if not (X.is_num(rp) and rp.num.is_one()):
        parts.append(rp)
    parts.extend(fs)
    if not lead.is_one():
        parts.insert(0, X.num(lead))
    if not parts:
        return X.num(1)
    return X.mul_n(parts)


def nice(e):
    """答えの見た目を整える: 1 変数の多項式なら因数の積に、そうでなければ展開したまま。"""
    x = X.expand(e)
    vs = X.collect_syms(x)
    if len(vs) != 1:
        return x
    c = []
    if not S.poly_coeffs(x, vs[0], c):
        return x
    return factor_poly(c, vs[0])


# ---------------------------------------------------------------- Σ


def power_sum(p, m):
    """Σ[k=1..m] k^p の公式（p = 0,1,2,3）。教科書の形のまま作る。"""
    half = X.mul_n([X.num(X.Rat(1, 2)), m, X.add_n([m, X.num(1)])])
    if p == 0:
        return m
    if p == 1:
        return half
    if p == 2:
        return X.mul_n([X.num(X.Rat(1, 6)), m, X.add_n([m, X.num(1)]),
                        X.add_n([X.mul_n([X.num(2), m]), X.num(1)])])
    return X.pow_e(half, X.num(2))                     # p == 3


def power_rule(p):
    if p == 0:
        return "定数の和"
    if p == 1:
        return "Σk の公式"
    if p == 2:
        return "Σk^2 の公式"
    return "Σk^3 の公式"


def mstr(m):
    """公式の説明に埋める上端の書き方（n - 1 のような式は括弧でくくる）。"""
    t = X.to_infix(m)
    return "(" + t + ")" if m.k in (X.ADD, X.MUL) else t


def power_note(p, m):
    """公式の説明。**上端を入れた形で書く**（「Σk = n(n+1)/2」の n を実際の上端に置き換える）。

    上端が n - 1 のとき「(n-1)((n-1)+1)/2」と書くと読めないので、足し算は先に済ませる。
    """
    m1 = mstr(X.simp(X.add_n([m, X.num(1)])))
    m2 = mstr(X.simp(X.add_n([X.mul_n([X.num(2), m]), X.num(1)])))
    if p == 0:
        return "Σ 1 = " + mstr(m) + " （項の個数だけ足す）"
    if p == 1:
        return "Σk = " + mstr(m) + m1 + "/2"
    if p == 2:
        return "Σk^2 = " + mstr(m) + m1 + m2 + "/6"
    return "Σk^3 = {" + mstr(m) + m1 + "/2}^2"


def geom_term(t, var):
    """項が c * r^(a*var + b) の形か（等比）。そうなら (c, r, a, b)、違えば None。"""
    c = X.Rat(1)
    got = None
    fs = list(t.kids) if t.k == X.MUL else [t]
    for f in fs:
        if X.is_num(f):
            c = c * f.num
            continue
        if f.k != X.POW or not X.is_num(f.kids[0]):
            return None
        if got is not None:
            return None                                # 2^k * 3^k は扱わない
        lc = []
        if not S.poly_coeffs(f.kids[1], var, lc):
            return None
        if len(lc) != 2 or not lc[1].is_int() or not lc[0].is_int() or lc[1].is_zero():
            return None
        got = (f.kids[0].num, lc[1].n, lc[0].n)
    if got is None:
        return None
    return (c, got[0], got[1], got[2])


def sum_term(t, var, m):
    """1 項ぶんの Σ[var=1..m]。解けたら (式, 規則名, 説明)、解けなければ None。"""
    c = []
    if S.poly_coeffs(t, var, c):
        while len(c) > 1 and c[-1].is_zero():
            c.pop()
        p = len(c) - 1
        if p > 3:
            return None                                # 4 乗以上の公式は教科書に無い
        if p == 0 or c[p].is_zero():
            return (X.mul_n([X.num(c[0] if c else X.Rat(0)), m]), power_rule(0), power_note(0, m))
        # 単項でないなら呼ぶ側が項ごとに分けているはず。ここに来るのは c[p] x^p だけの形
        for i in range(p):
            if not c[i].is_zero():
                return None
        out = power_sum(p, m) if c[p].is_one() else X.mul_n([X.num(c[p]), power_sum(p, m)])
        note = power_note(p, m)
        if not c[p].is_one():
            note = "係数 " + str(c[p]) + " を外に出して " + note
        return (out, power_rule(p), note)
    g = geom_term(t, var)
    if g is not None:
        cc, r, a, b = g
        if r.is_zero():
            return None
        ratio = X.rpow(r, a)                           # 公比（a が負でも rpow が扱う）
        first = cc * X.rpow(r, a + b)                  # var = 1 のときの値
        if ratio.is_one():
            return (X.mul_n([X.num(first), m]), "定数の和",
                    "公比が 1 なので同じ数を " + mstr(m) + " 個足す")
        out = X.mul_n([X.num(first / (ratio - X.Rat(1))),
                       X.add_n([X.pow_e(X.num(ratio), m), X.num(-1)])])
        return (out, "等比数列の和",
                "初項 " + str(first) + "、公比 " + str(ratio) + " の等比数列の和 a(r^n - 1)/(r - 1)")
    return None


def sigma(body_in, var, lo, hi):
    """Σ[var=lo..hi] body。"""
    r = Sum()
    r.var, r.lo, r.hi = var, lo, hi
    whole = sum_e(var, lo, hi, body_in)
    if not X.is_num(lo) or not lo.num.is_int():
        r.why = "Σ の下端は整数でないと解けません"
        return r
    L = lo.num.n
    if X.is_num(hi) and hi.num.is_int() and hi.num.n < L:      # 項が無い
        r.ok = True
        r.value = X.num(0)
        r.steps.append(Step("項が無い", "上端が下端より小さいので和は 0", whole, X.num(0)))
        return r

    # 下端を 1 にそろえる。公式は Σ[k=1..m] の形でしか書かれていないので、そこに寄せる
    m = hi
    extra = []                                         # 下端が 0 以下のときに書き出す項
    cut_head = L >= 2                                  # 下端が 2 以上なら Σ[1..L-1] を引く
    if cut_head:
        shown = X.add_n([sum_e(var, X.num(1), hi, body_in),
                         X.neg(sum_e(var, X.num(1), X.num(L - 1), body_in))])
        r.steps.append(Step("下端をずらす",
                            "公式は k = 1 から。Σ[k=%d..] = Σ[k=1..] - Σ[k=1..%d]" % (L, L - 1),
                            whole, shown))
    elif L <= 0:
        if 1 - L > 32:
            r.why = "Σ の下端が小さすぎます"
            return r
        xs = [X.simp(X.subst(body_in, var, X.num(k))) for k in range(L, 1)]
        extra = list(xs)
        xs.append(sum_e(var, X.num(1), hi, body_in))
        r.steps.append(Step("下端をずらす", "k が 0 以下の項は書き出して、残りを公式で足す",
                            whole, X.add_n(xs)))

    body = X.expand(body_in)                           # 中身を項に分ける
    ts = X.disp_terms(body) if body.k == X.ADD else [body]
    if len(ts) > 1:
        xs = [sum_e(var, X.num(1), m, t) for t in ts]
        r.steps.append(Step("和の分解", "Σ は項ごとに分けられる",
                            sum_e(var, X.num(1), m, body), X.add_n(xs)))

    parts = []
    for t in ts:
        got = sum_term(t, var, m)
        if got is None:
            r.why = X.to_infix(t) + " の Σ は未対応（k^4 以上や k·2^k のような形）"
            return r
        s, rule, note = got
        s = X.simp(s)
        r.steps.append(Step(rule, note, sum_e(var, X.num(1), m, t), s))
        parts.append(s)
    total = X.add_n(parts)

    if cut_head:                                       # Σ[1..L-1] を引く
        cut = X.num(0)
        for t in ts:
            cut = X.add_n([cut, sum_term(t, var, X.num(L - 1))[0]])
        before = X.add_n([total, X.neg(cut)])
        r.steps.append(Step("引く分を計算する",
                            "Σ[k=1..%d] = %s" % (L - 1, X.to_infix(X.simp(cut))),
                            before, before))
        total = X.add_n([total, X.neg(cut)])
    for x in extra:
        total = X.add_n([total, x])

    v = nice(total)
    r.steps.append(Step("まとめる", "通分して因数でくくる", total, v))
    r.ok = True
    r.value = v
    return r


# ---------------------------------------------------------------- 数列（項の並びから）


class Seq:
    def __init__(self):
        self.ok = False
        self.why = ""
        self.type = ""            # "等差数列" / "等比数列" / "階差数列"
        self.var = "n"
        self.term = None          # 一般項 a_n
        self.sum = None           # 初項から第 n 項までの和 S_n
        self.nth = None
        self.nth_i = 0
        self.steps = []
        self.given = []
        self.first = X.Rat(0)
        self.delta = X.Rat(0)
        self.ratio = X.Rat(0)


def arith_of(a):
    """等差か（差が一定）。公差を返す。"""
    if len(a) < 3:
        return None
    d = a[1] - a[0]
    for i in range(2, len(a)):
        if not (a[i] - a[i - 1] == d):
            return None
    return d


def geom_of(a):
    """等比か（比が一定）。公比を返す。"""
    if len(a) < 3:
        return None
    for v in a:
        if v.is_zero():
            return None
    r = a[1] / a[0]
    for i in range(2, len(a)):
        if not (a[i] / a[i - 1] == r):
            return None
    return r


def list_str(a):
    return ", ".join(str(v) for v in a)


def matches(term, var, a):
    """一般項が与えられた項を全部再現するか（見分けを間違えたまま答えを出さないための確認）。"""
    for i, want in enumerate(a):
        v = X.simp(X.subst(term, var, X.num(i + 1)))
        if not X.is_num(v) or not (v.num == want):
            return False
    return True


def analyze(a, var="n"):
    s = Seq()
    s.var = var
    s.given = list(a)
    if len(a) < 3:
        s.why = "項が 3 つ以上ないと数列を見分けられません"
        return s
    n = X.sym(var)
    s.first = a[0]

    d = arith_of(a)
    r = geom_of(a) if d is None else None
    if d is not None:
        s.type = "等差数列"
        s.delta = d
        s.steps.append(Step("階差を取る", "となり合う項の差は " + str(d) + " で一定",
                            X.num(a[1] - a[0]), X.num(d)))
        s.term = nice(X.add_n([X.num(a[0]), X.mul_n([X.num(d), X.add_n([n, X.num(-1)])])]))
        s.steps.append(Step("等差数列の一般項",
                            "a_n = 初項 + (n - 1) × 公差 = %s + (n - 1)×%s" % (a[0], d),
                            s.term, s.term))
    elif r is not None:
        s.type = "等比数列"
        s.ratio = r
        s.steps.append(Step("比を取る", "となり合う項の比は " + str(r) + " で一定",
                            X.num(a[1]), X.num(r)))
        s.term = X.simp(X.mul_n([X.num(a[0]), X.pow_e(X.num(r), X.add_n([n, X.num(-1)]))]))
        s.steps.append(Step("等比数列の一般項",
                            "a_n = 初項 × 公比^(n - 1) = %s×%s^(n - 1)" % (a[0], r),
                            s.term, s.term))
    else:
        # 階差数列: b_k = a_(k+1) - a_k を作って、それが等差か等比なら a_n = a_1 + Σ[k=1..n-1] b_k
        if len(a) < 4:
            s.why = "等差でも等比でもありません（階差を見るには 4 項必要）"
            return s
        b = [a[i] - a[i - 1] for i in range(1, len(a))]
        k = X.sym("k")
        bd, br = arith_of(b), None
        if bd is not None:
            bk = X.simp(X.add_n([X.num(b[0]), X.mul_n([X.num(bd), X.add_n([k, X.num(-1)])])]))
        else:
            br = geom_of(b)
            if br is None:
                s.why = "等差でも等比でもありません（階差も一定になりません）"
                return s
            bk = X.simp(X.mul_n([X.num(b[0]), X.pow_e(X.num(br), X.add_n([k, X.num(-1)]))]))
        s.type = "階差数列"
        s.steps.append(Step("階差を取る",
                            "差の数列 b_k は " + list_str(b) + " で、これが等差か等比になる",
                            X.num(b[0]), bk))
        hi = X.add_n([n, X.num(-1)])
        sm = sigma(bk, "k", X.num(1), hi)
        if not sm.ok:
            s.why = sm.why
            return s
        s.steps.append(Step("階差数列の一般項", "a_n = a_1 + Σ[k=1..n-1] b_k （n ≥ 2）",
                            sum_e("k", X.num(1), hi, bk), sm.value))
        s.steps.extend(sm.steps)
        s.term = nice(X.add_n([X.num(a[0]), sm.value]))

    if not matches(s.term, var, a):
        s.why = "一般項が与えられた項に合いません（数列を見分けられませんでした）"
        return s
    tot = sigma(X.subst(s.term, var, X.sym("k")), "k", X.num(1), X.sym(var))
    if tot.ok:
        s.sum = tot.value
        s.steps.append(Step("初項から第 n 項までの和",
                            "S_n = Σ[k=1..n] a_k = " + X.to_infix(tot.value),
                            sum_e("k", X.num(1), X.sym(var), s.term), tot.value))
    s.ok = True
    return s


# ---------------------------------------------------------------- 答えの文字列
#
# **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。


def show_e(e, latex):
    return X.to_latex(e) if latex else X.to_infix(e)


def sum_answer_lines(s, latex=False):
    if not s.ok:
        return [s.why]
    return [show_e(s.value, latex)]


def seq_answer_lines(s, latex=False):
    if not s.ok:
        return [s.why]
    out = []
    if s.type == "等差数列":
        out.append("等差数列（初項 %s、公差 %s）" % (s.first, s.delta))
    elif s.type == "等比数列":
        out.append("等比数列（初項 %s、公比 %s）" % (s.first, s.ratio))
    else:
        out.append("階差数列（初項 %s）" % s.first)
    out.append("一般項: a_%s = %s" % (s.var, show_e(s.term, latex)))
    if s.sum is not None:
        out.append("和: S_%s = %s" % (s.var, show_e(s.sum, latex)))
    if s.nth is not None:
        out.append("第 %d 項: %s" % (s.nth_i, show_e(s.nth, latex)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sum", "seq"])
    ap.add_argument("--expr", default="")
    ap.add_argument("--terms", default="")
    ap.add_argument("--var", default="")
    ap.add_argument("--from", dest="lo", default="1")
    ap.add_argument("--to", dest="hi", default="n")
    ap.add_argument("--nth", type=int, default=0)
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--latex", action="store_true")
    a = ap.parse_args(X.cli_argv(("--expr", "--terms", "--var", "--from", "--to", "--nth")))

    if a.cmd == "sum":
        var = a.var or "k"
        e, err = X.parse(a.expr)
        if err:
            print("parse error: %s" % err)
            return 1
        if is_sum(e):
            var, lo, hi, e = e.kids[0].name, e.kids[1], e.kids[2], e.kids[3]
        else:
            lo, err = X.parse(a.lo)
            if err:
                print("parse error(--from): %s" % err)
                return 1
            hi, err = X.parse(a.hi)
            if err:
                print("parse error(--to): %s" % err)
                return 1
        r = sigma(e, var, lo, hi)
        lines = sum_answer_lines(r, a.latex)
    else:
        var = a.var or "n"
        vals = []
        for part in a.terms.split(","):
            part = part.strip()
            if not part:
                continue
            v, err = X.parse(part)
            if err or not X.is_num(v):
                print("項が数ではありません: %s" % part)
                return 1
            vals.append(v.num)
        r = analyze(vals, var)
        if r.ok and a.nth > 0:
            r.nth_i = a.nth
            r.nth = X.simp(X.subst(r.term, var, X.num(a.nth)))
        lines = seq_answer_lines(r, a.latex)

    if a.steps:
        for i, st in enumerate(r.steps, 1):
            print("%d. [%s] %s" % (i, st.rule, st.note))
            print("   %s" % (X.to_latex(st.after) if a.latex else X.to_infix(st.after)))
    for line in lines:
        print(line)
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
