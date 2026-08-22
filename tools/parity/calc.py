"""微分・積分のパリティ — 同じ式を入れたら C++ と Python が同じ手順と答えを出すか。

  python tools/parity/calc.py --n 200

比べるのは**手順の全行と答え**（`mathcam diff --steps` / `mathcam integ --steps` と
`tools/calc.py` の出力をそのまま突き合わせる）。手順がこのプロジェクトの成果物なので、
答えだけ合っていても意味がない。

式は固定の一覧 + **乱数で作ったもの**（多項式・根号・積・合成・三角・指数・対数）。
積分は「できない形」も混ぜる（両方が同じ理由で断ることを確かめる）。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import genexpr as G       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED = [
    "x^3 + 2x", "3x^2 - 5x + 6", "sqrt(x)", "1/x", "x*sin(x)", "(2x + 1)^3",
    "exp(2x)", "ln(x)", "x^2 + 1/x", "5", "x", "-x^2 + 3x", "sin(3x) + cos(2x)",
    "x*exp(x)", "tan(x)", "(x^2 + 1)^4", "sqrt(2x + 1)", "1/(2x + 3)",
]
# 定積分の範囲（式ごとに 1 つ）
RANGES = ["0,2", "1,3", "-1,1"]


def rnd_expr(r):
    """微積分向けの式を乱数で作る（生成器の gen_expr とは別。ここは 1 変数に絞る）。"""
    k = r.below(100)
    a = G.pick(r, 1, 9)
    b = G.pick(r, -9, 9)
    n = G.pick(r, 2, 4)
    if k < 20:
        return "%dx^%d + %dx + %d" % (a, n, b, G.pick(r, -9, 9))
    if k < 32:
        return "%dx^%d" % (a, n)
    if k < 44:
        return "sqrt(%dx + %d)" % (a, abs(b) + 1)
    if k < 54:
        return "1/(%dx + %d)" % (a, abs(b) + 1)
    if k < 64:
        return "(%dx + %d)^%d" % (a, b, n)
    if k < 72:
        return "%dx*sin(%dx)" % (a, G.pick(r, 1, 4))
    if k < 80:
        return "exp(%dx)" % a
    if k < 88:
        return "ln(%dx + %d)" % (a, abs(b) + 1)
    if k < 94:
        return "cos(%dx) + %dx" % (a, b)
    return "%d/x + %dx^2" % (a, G.pick(r, 1, 5))


def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.replace("\r\n", "\n").rstrip("\n").splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
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

    r = G.Rng(a.seed)
    cases = [(s, None) for s in FIXED]
    for i in range(a.n):
        src = rnd_expr(r)
        rng = RANGES[r.below(len(RANGES))] if r.below(100) < 40 else None
        cases.append((src, rng))

    bad = 0
    for src, rng in cases:
        for integ in (False, True):
            cpp = [exe, "diff" if not integ else "integ", "--expr", src, "--steps"]
            py = [sys.executable, os.path.join("tools", "calc.py"), "--expr", src, "--steps"]
            if integ:
                py.append("--integ")
                if rng:
                    lo, hi = rng.split(",")
                    cpp += ["--from", lo, "--to", hi]
                    py += ["--from", lo, "--to", hi]
            ca, pb = run(cpp), run(py)
            if ca != pb:
                bad += 1
                print("[FAIL] %s %s%s" % ("∫" if integ else "d/dx", src,
                                          ("  [" + rng + "]") if (integ and rng) else ""))
                for i in range(max(len(ca), len(pb))):
                    x = ca[i] if i < len(ca) else "(なし)"
                    y = pb[i] if i < len(pb) else "(なし)"
                    if x != y:
                        print("   cpp: %s" % x)
                        print("   py : %s" % y)
                if bad > 6:
                    print("… 多すぎるので打ち切る")
                    return 1
    print("%d 件を突き合わせ（固定 %d + 乱数 %d、微分と積分の両方）、%d 件が不一致"
          % (len(cases) * 2, len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
