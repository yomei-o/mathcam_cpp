"""学習用の式を乱数で作る（Python 側）— pure/gen_expr.hpp の鏡。

乱数は splitmix64（このプロジェクトで唯一の乱数）。**同じ種なら C++ と同じ式列が出る**ので、
どちらでデータセットを作っても同じものになる。`tools/parity/dataset.py` が実際に突き合わせる。
呼び出し順を 1 つ変えるだけで列が変わるので、C++ 側と同じ順序で乱数を引くこと
（frac でなくても分母を 1 回引いているのは、そのため）。

  python tools/genexpr.py --n 10 --seed 1
"""
import argparse
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MASK = (1 << 64) - 1


class Rng:
    """pure/rng.hpp と同じ splitmix64。仕様はあちらのコメントが正。"""

    __slots__ = ("s",)

    def __init__(self, seed=0):
        self.s = seed & MASK

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK
        return z ^ (z >> 31)

    def below(self, n):
        return self.next() % n

    def unit(self):
        return (self.next() >> 11) * (1.0 / 9007199254740992.0)


def pick(r, lo, hi):
    return lo + r.below(hi - lo + 1)


# 変数に使う文字。**クラス表にある文字を全部出す**（x, y, t だけだと a・b・p が学習データに
# ほとんど出ず、実写で a が x、b と p が t に化けた）。x を少し厚くするのは教科書がそうだから。
# 26 個ちょうど（`below(26)` の 1 回で引く）。C++ の kVars と同じ並び・同じ重み。
VARS = ["x", "x", "x", "x", "y", "y", "y", "t", "t",
        "a", "a", "b", "b", "c", "c", "p", "p",
        "q", "r", "s", "n", "e", "g", "i", "o", "l"]


def atom(r, var, depth):
    k = r.below(100)
    if k < 45:
        return str(pick(r, -9, 99))
    if k < 60:
        return "%d/%d" % (pick(r, 1, 9), pick(r, 2, 9))
    if k < 90:
        return var
    if depth > 0:
        return "sqrt(%d)" % pick(r, 2, 30)
    return str(pick(r, 2, 12))


def term(r, var, depth):
    if depth <= 0:
        return atom(r, var, depth)
    k = r.below(100)
    if k < 22:
        return atom(r, var, depth)
    if k < 38:
        return term(r, var, depth - 1) + " + " + term(r, var, depth - 1)
    if k < 52:
        return term(r, var, depth - 1) + " - " + term(r, var, depth - 1)
    if k < 64:
        return "(" + term(r, var, depth - 1) + ")(" + term(r, var, depth - 1) + ")"
    if k < 76:
        return "(" + term(r, var, depth - 1) + ")/(" + term(r, var, depth - 1) + ")"
    if k < 86:
        return "(" + term(r, var, depth - 1) + ")^" + str(pick(r, 2, 3))
    if k < 94:
        return "sqrt(" + term(r, var, depth - 1) + ")"
    return "%d%s" % (pick(r, 2, 9), var)


def _quad(var, a, b, c):
    s = ("" if a == 1 else str(a)) + var + "^2"
    if b:
        s += (" + " if b > 0 else " - ") + ("" if abs(b) == 1 else str(abs(b))) + var
    if c:
        s += (" + " if c > 0 else " - ") + str(abs(c))
    return s + " = 0"


def one(r):
    var = VARS[r.below(26)]
    kind = r.below(100)
    if kind < 35:
        return term(r, var, 2)
    if kind < 65:
        a, b, c = pick(r, 1, 9), pick(r, -9, 9), pick(r, -9, 9)
        frac = r.below(100) < 30
        den = pick(r, 2, 5)             # frac でなくても引く（乱数列を揃えるため）
        s = ("" if a == 1 else str(a)) + var
        if frac:
            s += "/%d" % den
        if b:
            s += (" + " if b > 0 else " - ") + str(abs(b))
        return s + " = %d" % c
    if kind < 90:
        a = 1 if r.below(100) < 70 else pick(r, 2, 3)
        r1, r2 = pick(r, -6, 6), pick(r, -6, 6)
        return _quad(var, a, -a * (r1 + r2), a * r1 * r2)
    a, b, c = pick(r, 1, 3), pick(r, -9, 9), pick(r, -9, 9)
    return _quad(var, a, b, c)


# ---------------------------------------------------------------- 小学校の計算
#
# 教科書の書き方（× ÷ を字で書く、小数点、帯分数、中括弧）で 1 行を作る。返すのは
# typeset.present_arith が読める記法（frac / mixed）で、同じ文字列を expr.parse に通せば
# 値も出る。**乱数は 1 つずつローカルに受ける**（C++ 側と順序を合わせるため）。


def dec(r, lo, hi, digits):
    ip = pick(r, lo, hi)
    if digits <= 0:
        return str(ip)
    fp = pick(r, 1, 9 if digits == 1 else 99)
    return "%d.%d" % (ip, fp)


def arith(r):
    kind = r.below(100)
    if kind < 25:                                    # 小数の四則
        a = dec(r, 1, 9, 1)
        b = dec(r, 1, 9, 1)
        c = dec(r, 1, 20, 1)
        d = dec(r, 1, 9, 1)
        return "%s × (%s - 0.%d) + %s ÷ %s" % (a, b, pick(r, 1, 9), c, d)
    if kind < 45:                                    # 中括弧の入った整数の計算
        a, b, c, d, e = (pick(r, 2, 12), pick(r, 2, 9), pick(r, 10, 40), pick(r, 1, 9),
                         pick(r, 2, 9))
        return "{%d × %d - (%d - %d)} × %d" % (a, b, c, d, e)
    if kind < 70:                                    # 分数と帯分数
        w, an, ad = pick(r, 1, 5), pick(r, 1, 7), pick(r, 2, 9)
        bn, bd, k = pick(r, 1, 7), pick(r, 2, 9), pick(r, 2, 9)
        return ("mixed(%d,%d,%d) × frac(%d,%d) - frac(%d,%d)"
                % (w, an, ad, bn, bd, bn, k))
    if kind < 85:                                    # 分数どうしの割り算
        an, ad, bn, bd = pick(r, 1, 9), pick(r, 2, 9), pick(r, 1, 9), pick(r, 2, 9)
        return "frac(%d,%d) ÷ frac(%d,%d)" % (an, ad, bn, bd)
    if kind < 92:                                    # 大きい数の掛け算・引き算（103 × 12 - 36）
        a, b, c = pick(r, 11, 199), pick(r, 2, 24), pick(r, 2, 99)
        return "%d × %d - %d" % (a, b, c)
    # **文字と × ÷ を同じ絵に出す形。** これが無いと、検出器は「文字が出る絵」と
    # 「× が出る絵」を別々に見ることになり、x と × を見分ける必要がない
    # （実測: 実写で × が x と読まれた。出荷中のモデルは × のクラスすら持っていない）。
    v = VARS[r.below(26)]
    a, b = pick(r, 2, 12), pick(r, 2, 9)
    f = r.below(3)
    if f == 0:
        return "%d × %s + %d" % (a, v, b)
    if f == 1:
        return "%s × %d - %d" % (v, a, b)
    return "%d × %s ÷ %d" % (a, v, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--arith", action="store_true", help="小学校の計算を出す")
    a = ap.parse_args()
    r = Rng(a.seed)
    for _ in range(a.n):
        e = arith(r) if a.arith else one(r)
        # --state は「どこで C++ とずれたか」を特定するため（状態が一致していれば、
        # そこまでの乱数の消費数が同じということ）
        print("%d	%s" % (r.s, e) if a.state else e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
