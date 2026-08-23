"""面積のパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/area.py
  python tools/parity/area.py --n 200 --seed 5
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

# (f, g, from, to)。空文字は付けない
FIXED = [
    ("x^2", "x", "", ""), ("x^2", "4", "", ""), ("x^2 - 1", "0", "0", "2"),
    ("x", "x^3", "", ""), ("sin(x)", "0", "0", "pi"), ("x^2", "-x^2 + 2", "", ""),
    ("x^3", "x", "", ""), ("x^2", "x^2", "", ""), ("exp(x)", "0", "0", "1"),
    ("x^2 - 4x + 3", "0", "", ""), ("-x^2 + 4", "0", "", ""), ("x^2", "2x", "", ""),
    ("x^3 - x", "0", "-1", "1"), ("x", "0", "0", "3"), ("1/x", "0", "1", "2"),
    ("cos(x)", "0", "0", "pi"), ("x^2 + 1", "x + 3", "", ""), ("x^4", "x^2", "", ""),
]


def gen(rng):
    k = rng.random()
    r1, r2 = rng.randint(-4, 4), rng.randint(-4, 4)
    if k < 0.4:                                      # 2 次と 1 次（交点 2 つ）
        return ("x^2 + %dx + %d" % (-(r1 + r2), r1 * r2), "0", "", "")
    if k < 0.6:
        a = rng.randint(1, 3)
        return ("%dx^2" % a, "%dx + %d" % (rng.randint(-4, 4), abs(rng.randint(0, 6))), "", "")
    if k < 0.8:                                      # 範囲つき
        lo = rng.randint(-3, 0)
        return ("x^2 + %dx + %d" % (rng.randint(-4, 4), rng.randint(-4, 4)), "0",
                str(lo), str(lo + rng.randint(1, 4)))
    return (rng.choice(["x^3 - %dx" % rng.randint(1, 4), "sin(x)", "x^3"]), "0",
            str(rng.randint(-2, 0)), str(rng.randint(1, 3)))


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
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
    script = os.path.join(ROOT, "tools", "area.py")
    bad = 0
    for f, g, lo, hi in cases:
        tail = ["--expr", f, "--and", g]
        if lo:
            tail += ["--from", lo]
        if hi:
            tail += ["--to", hi]
        tail += ["--steps", "--latex"]
        c = run([exe, "area"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] %s / %s [%s..%s]" % (f, g, lo, hi))
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-22s %-12s -> %s" % (f, g, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
