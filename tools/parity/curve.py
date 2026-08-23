"""関数を調べる（接線・極値）のパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/curve.py
  python tools/parity/curve.py --n 300 --seed 5
"""
import argparse
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (式, --at。at は空文字なら付けない)
FIXED = [
    ("x^3 - 3x", ""), ("x^2", "1"), ("x^3 - 3x", "2"), ("x^2 + 2x + 3", ""),
    ("x^3", ""), ("x^4 - 2x^2", ""), ("1/x", ""), ("sin(x)", ""), ("cos(x)", ""),
    ("x^3 - 6x^2 + 9x", ""), ("exp(x)", ""), ("ln(x)", ""), ("sqrt(x)", "4"),
    ("x^3 - 3x^2 + 3x - 1", ""), ("2x^3 + 3x^2 - 12x", ""), ("x + 1/x", ""),
    ("x^2 - 4x + 1", "0"), ("x*exp(x)", ""), ("x^4", ""), ("-x^2 + 4x", ""),
    ("x^3 + x", ""), ("(x - 1)^2*(x + 2)", ""), ("x^5 - 5x", ""), ("tan(x)", ""),
    # 2 次関数（平方完成・頂点・軸・最大最小）
    ("x^2 - 4x + 1", ""), ("-x^2 + 6x - 5", ""), ("2x^2 + 4x + 5", ""),
    ("x^2/2 - x", ""), ("-3x^2 + 2x + 1", ""), ("x^2 + 1", "2"),
]


def gen(rng):
    k = rng.random()
    a = rng.randint(1, 4)
    b = rng.randint(-9, 9)
    c = rng.randint(-9, 9)
    at = str(rng.randint(-3, 3)) if rng.random() < 0.35 else ""
    if k < 0.35:
        return ("%dx^3 + %dx^2 + %dx" % (a, b, c), at)
    if k < 0.6:
        return ("%dx^2 + %dx + %d" % (a, b, c), at)
    if k < 0.72:
        return ("%dx^4 + %dx^2 + %d" % (a, b, c), at)
    if k < 0.84:
        return ("%dx^3 + %d" % (a, b), at)
    return (rng.choice(["sin(%dx)" % a, "exp(%dx)" % a, "%d/x" % a, "sqrt(x) + %dx" % a]), at)


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


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
        print("[SKIP] mathcam の実行ファイルが無い")
        return 0

    rng = random.Random(a.seed)
    cases = list(FIXED) + [gen(rng) for _ in range(a.n)]
    pyexe = sys.executable
    script = os.path.join(ROOT, "tools", "curve.py")
    bad = 0
    for src, at in cases:
        tail = ["--expr", src] + (["--at", at] if at else []) + ["--steps", "--latex"]
        c = run([exe, "curve"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] %s%s" % (src, (" @" + at) if at else ""))
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-24s -> %s" % (src, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
