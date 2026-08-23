"""円の方程式のパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/circle.py
  python tools/parity/circle.py --n 300 --seed 5
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

FIXED = [
    "x^2 + y^2 - 4x + 2y - 4 = 0", "x^2 + y^2 = 9", "x^2 + y^2 - 2x = 0",
    "x^2 + y^2 + 2x + 2y + 2 = 0", "x^2 + y^2 + 1 = 0", "2x^2 + 2y^2 - 4x = 6",
    "x^2 - y^2 = 1", "x^2 + y^2 - 6x - 8y = 0", "x^2 + y^2 - 3 = 0", "x + y = 1",
    "x^2 + y^2 + xy = 1", "3x^2 + 3y^2 = 12", "x^2 + y^2 - x - y = 0",
    "x^2 + y^2 = 0", "a^2 + b^2 - 2a = 3",
]


def gen(rng):
    p, q = rng.randint(-5, 5), rng.randint(-5, 5)
    k = rng.random()
    if k < 0.6:                                      # 中心と半径から作る（きれいに割れる）
        r2 = rng.randint(-2, 6)
        return "x^2 + y^2 + %dx + %dy + %d = 0" % (-2 * p, -2 * q, p * p + q * q - r2)
    if k < 0.8:
        a = rng.randint(2, 4)
        return "%dx^2 + %dy^2 + %dx = %d" % (a, a, rng.randint(-6, 6), rng.randint(-4, 9))
    return rng.choice(["x^2 - y^2 = %d" % rng.randint(1, 5),
                       "x^2 + %dy^2 = 4" % rng.randint(2, 3),
                       "x^2 + y^2 + %dxy = 1" % rng.randint(1, 3),
                       "x + %dy = 3" % rng.randint(1, 4)])


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
    script = os.path.join(ROOT, "tools", "circle.py")
    bad = 0
    for src in cases:
        tail = ["--expr", src, "--steps", "--latex"]
        c = run([exe, "circle"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] %s" % src)
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-30s -> %s" % (src, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
