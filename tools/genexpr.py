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
    VARS = ["x", "x", "x", "y", "t"]
    var = VARS[r.below(5)]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--state", action="store_true")
    a = ap.parse_args()
    r = Rng(a.seed)
    for _ in range(a.n):
        e = one(r)
        # --state は「どこで C++ とずれたか」を特定するため（状態が一致していれば、
        # そこまでの乱数の消費数が同じということ）
        print("%d	%s" % (r.s, e) if a.state else e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
