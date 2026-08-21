"""小学校の計算の手順のパリティ — 同じ式を入れたら C++ と Python が同じ手順を出すか。

  python tools/parity/arith.py --n 300

比べるのは**手順の全行**（規則名・計算した部分・その後の式）と最後の答え。
手順がこのプロジェクトの成果物なので、答えだけ合っていても意味がない。

`mathcam solve --steps` と `python tools/arith.py` の出力をそのまま突き合わせる
（どちらも「方程式でない式は計算問題として 1 手ずつ計算する」道を通る）。
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
    "{1.8 × 3.5 - (10.2 - 6.8)} × 9",
    "3.7 × (2 - 0.4) + 0.96 ÷ 1.2",
    "mixed(2,5,8) × frac(4,7) - (mixed(5,1,3) - frac(1,2)) ÷ 5",
    "6 × {mixed(1,2,9) - (frac(2,3) + frac(1,2))} ÷ frac(4,9)",
    "frac(3,4) ÷ frac(2,5)",
    "103 × 12 - 36",
    "2 + 3 × 4",
    "(2 + 3) × 4",
    "12 ÷ 4 ÷ 3",
    "8 - (3 - 1)",
    "0.5 + 0.25 × 4",
    "mixed(1,1,2) + mixed(2,1,3)",
]


def cpp(exe, src):
    p = subprocess.run([exe, "solve", "--expr", src, "--steps"], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


def py(src):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "arith.py"),
                        "--expr", src], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


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
        print("[SKIP] mathcam の実行ファイルが無い")
        return 0

    rng = G.Rng(a.seed)
    cases = list(FIXED) + [G.arith(rng) for _ in range(a.n)]
    bad = 0
    for src in cases:
        c, p = cpp(exe, src), py(src)
        if c != p:
            print("[FAIL] %s" % src)
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-40s -> %s" % (src, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
