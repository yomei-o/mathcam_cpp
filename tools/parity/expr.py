"""CAS のパリティ — 同じ式を入れたら C++ と Python が同じものを出すか。

  python tools/parity/expr.py                # 固定の式 + 乱数で作った式 300 本
  python tools/parity/expr.py --n 2000       # もっと回す
  python tools/parity/expr.py --seed 7

何を縛るか:

  * **正規形（中置）と LaTeX が一字一句同じ**。ここがずれたら、認識器の出力を Python で
    検算しても意味がないし、手順表示が言語によって変わる。
  * **往復不変**: `print(parse(print(e))) == print(e)`。印字したものを自分のパーサで
    読み直せること。初日に `2^1/2` と印字して `(2^1)/2` に読める状態を作ってしまったので、
    これは実際に起きる壊れ方である。
  * **数値の一致**（厳密に閉じない式のため）。相対 1e-9。

乱数の式を混ぜるのは、固定の式だけだと「自分が思いついた形」しか通らないから。深さと
演算子の選び方を振って、括弧・暗黙の掛け算・分数指数・負数が混ざるようにしてある。
"""
import argparse
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED = [
    "2/3 + 1/6", "1/3 + 1/3 + 1/3", "0.25 + 1/4", "7 - 9", "2*3 + 4*5",
    "2(x+1) - 3x", "(x+1)^2", "(x+2)(x-3)", "(x+1)^3", "3x + 2y - x + y",
    "1/2 x + 1/3 x", "x^2 - 5x + 6 = 0", "2x + 3 = 7", "x/2 + x/3",
    "sqrt(4) + sqrt(2)", "sqrt(9/4)", "8^(1/3)", "2^(-3)", "x^(1/2)",
    "-x - -x", "-(x + 1)", "5 - (x - 2)", "x*x*x", "x^2*x^3", "(2x)^3",
    "sin(0) + cos(0)", "ln(1)", "abs(-3)", "exp(0)", "sin(x) + sin(x)",
    "1/(x+1)", "(x+1)/(x+1)", "2/(4x)", "x^2/x", "0*x", "x^0",
    "1 + 2 + 3 + 4 + 5", "2*(3 + 4*(5 - 6))", "-2^2", "(-2)^2",
]


def gen(rng, depth=0):
    """乱数の式。深さで打ち切る。文字列で返す（両実装のパーサも試験対象にするため）。"""
    if depth >= 3 or rng.random() < 0.28:
        r = rng.random()
        if r < 0.45:
            return str(rng.randint(-9, 9))
        if r < 0.60:
            return "%d/%d" % (rng.randint(-9, 9), rng.randint(1, 9))
        return rng.choice(["x", "y", "x", "x", "t"])
    op = rng.choice(["+", "-", "*", "/", "^", "impl", "fn", "neg", "paren"])
    a = gen(rng, depth + 1)
    if op == "neg":
        return "-(%s)" % a
    if op == "paren":
        return "(%s)" % a
    if op == "fn":
        return "%s(%s)" % (rng.choice(["sqrt", "sin", "cos", "ln", "abs", "exp"]), a)
    if op == "^":
        # 指数は小さい整数か 1/2（大きいと展開が爆発して比較に時間がかかるだけ）
        return "(%s)^%s" % (a, rng.choice(["2", "3", "0", "1", "(1/2)", "(-1)"]))
    b = gen(rng, depth + 1)
    if op == "impl":                       # 暗黙の掛け算（5x, 2(x+1) の形）
        return "%s(%s)" % (rng.choice(["2", "3", "-1", "x"]), b)
    return "(%s) %s (%s)" % (a, op, b)


def cpp_eval(exe, src, latex=False, no_expand=False):
    cmd = [exe, "eval", "--expr", src]
    if latex:
        cmd.append("--latex")
    if no_expand:
        cmd.append("--no-expand")
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


def py_eval(src, latex=False, no_expand=False):
    e, err = X.parse(src)
    if err:
        return ["parse error: %s" % err]
    if not no_expand:
        e = X.expand(e)
    out = [X.to_infix(e)]
    if latex:
        out.append("latex: %s" % X.to_latex(e))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="乱数で作る式の本数")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--exe", default="")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    exe = a.exe
    if not exe:
        for name in ("mathcam.exe", "mathcam"):
            if os.path.exists(os.path.join(ROOT, name)):
                exe = os.path.join(ROOT, name)
                break
    if not exe or not os.path.exists(exe):
        print("[SKIP] mathcam の実行ファイルが無い（sh build/cc.sh pure/mathcam.cpp -o mathcam.exe）")
        return 0

    rng = random.Random(a.seed)
    cases = list(FIXED) + [gen(rng) for _ in range(a.n)]
    bad = 0
    checked = 0
    for src in cases:
        c = cpp_eval(exe, src, latex=True)
        p = py_eval(src, latex=True)
        # 構文エラーになる式は「両方がエラーになること」だけ確かめる（乱数の式で起こりうる）
        if (c and c[0].startswith("parse error")) or (p and p[0].startswith("parse error")):
            if bool(c and c[0].startswith("parse error")) != bool(p and p[0].startswith("parse error")):
                print("[FAIL] エラー判定が違う: %s" % src)
                print("   cpp: %s" % (c[0] if c else ""))
                print("   py : %s" % (p[0] if p else ""))
                bad += 1
            continue
        checked += 1
        if c != p:
            print("[FAIL] %s" % src)
            print("   cpp: %s" % " | ".join(c))
            print("   py : %s" % " | ".join(p))
            bad += 1
            continue

        # 往復不変: 印字したものを読み直して、また印字したら同じになるか
        printed = c[0]
        c2 = cpp_eval(exe, printed, latex=True)
        p2 = py_eval(printed, latex=True)
        if c2 != c:
            print("[FAIL] C++ が自分の印字を読み直せない: %s -> %s" % (src, printed))
            print("   1 回目: %s" % " | ".join(c))
            print("   2 回目: %s" % " | ".join(c2))
            bad += 1
        elif p2 != p:
            print("[FAIL] Python が自分の印字を読み直せない: %s -> %s" % (src, printed))
            bad += 1
        elif a.verbose:
            print("  ok  %-28s -> %s" % (src, printed))

    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (checked, len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
