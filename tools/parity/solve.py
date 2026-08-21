"""solve のパリティ — 同じ方程式を入れたら C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/solve.py                 # 固定 + 乱数で作った方程式
  python tools/parity/solve.py --n 400 --seed 3

答えだけを比べるのでは足りない。**手順の列（規則の名前・説明・各段の式）まで比べる**。
手順がこのプロジェクトの成果物そのもので、片方だけ変えたら「言語によって解き方が違う」
アプリになる。CLI の出力（`--steps --latex` の全行）をそのまま突き合わせるのが一番強い縛りで、
これは表示の文言まで含めて一致を要求する。

乱数の方程式は「解ける形」に寄せて作る（一次と二次を、整数解・分数解・無理数解・実数解なし
の 4 通りが混ざるように）。乱数で任意の式を作ると大半が「対応外」になってテストが薄くなる。
"""
import argparse
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X          # noqa: E402
import solve as S         # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED = [
    "2x + 3 = 7", "x + 1 = 1", "3x = 0", "x/2 + 1 = 3", "2x = x + 5",
    "x/2 + x/3 = 5", "-x + 4 = 1", "2(x + 1) = 6", "5 = x", "0 = x - 7",
    "x^2 - 5x + 6 = 0", "x^2 - 4 = 0", "x^2 = 2", "x^2 = 8", "x^2 + x + 1 = 0",
    "x^2 + 2x + 1 = 0", "2x^2 - 8 = 0", "x^2 - x = 0", "3x^2 + 5x - 2 = 0",
    "x^2 + x = 1", "(x + 1)(x - 2) = 0", "x^2/2 - 2 = 0", "x^2 + 1 = 0",
    "3 = 3", "4 = 5", "x = x", "x = x + 1",
    "y^2 - 9 = 0", "2t + 1 = 0",
]


def gen(rng):
    """解ける形の方程式。一次と二次を、係数の作り方を振って混ぜる。"""
    v = rng.choice(["x", "x", "x", "y", "t"])
    if rng.random() < 0.45:
        a = rng.randint(-9, 9) or 2
        b = rng.randint(-9, 9)
        c = rng.randint(-9, 9)
        if rng.random() < 0.3:                       # 分数係数（分母を払う手が出る）
            return "%s%s/%d + %d = %d" % (a, v, rng.randint(2, 6), b, c)
        return "%d%s + %d = %d" % (a, v, b, c)
    a = rng.choice([1, 1, 1, 2, 3, -1])
    if rng.random() < 0.5:                            # 根から作る（因数分解できる形）
        r1, r2 = rng.randint(-6, 6), rng.randint(-6, 6)
        b = -a * (r1 + r2)
        c = a * r1 * r2
        return "%d%s^2 + %d%s + %d = 0" % (a, v, b, v, c)
    b, c = rng.randint(-9, 9), rng.randint(-9, 9)     # 無理数解や実数解なしも混ざる
    return "%d%s^2 + %d%s + %d = 0" % (a, v, b, v, c)


def cpp(exe, src):
    p = subprocess.run([exe, "solve", "--expr", src, "--steps", "--latex"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


def py(src):
    e, err = X.parse(src)
    if err:
        return ["parse error: %s" % err]
    s = S.solve(e)
    out = []
    if not s.ok:
        return ["solve: %s" % s.why]
    for i, st in enumerate(s.steps, 1):
        out.append("%d. [%s] %s" % (i, st.rule, st.note))
        out.append("   %s" % X.to_latex(st.after))
    if s.kind == "identity":
        out.append("すべての値で成り立つ")
    elif s.kind == "contradiction":
        out.append("解なし（矛盾）")
    elif not s.roots:
        out.append("実数解なし")
    else:
        for r in s.roots:
            out.append("%s = %s" % (s.var, X.to_latex(r)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
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
    for src in cases:
        c, p = cpp(exe, src), py(src)
        if c != p:
            print("[FAIL] %s" % src)
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-26s -> %s" % (src, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
