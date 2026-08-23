"""ベクトルのパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/vector.py
  python tools/parity/vector.py --n 300 --seed 5
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
    ("1, 2", "3, 4"), ("1, 0", "1, 1"), ("1, 2", "2, 4"), ("1, 2", "2, -1"),
    ("1, 1", "-1, -1"), ("1, 2, 3", "4, 5, 6"), ("1, 0", "0, 1"),
    ("2, 0", "1, sqrt(3)"), ("0, 0", "1, 1"), ("1, 2", "1, 2"),
    ("1/2, 1/2", "1, 1"), ("3, 4", "4, -3"), ("1, 1, 0", "0, 1, 1"),
    ("1, 2", "3, 4, 5"), ("1", "2"), ("-1, 0", "1, 0"),
]


def gen(rng):
    n = 2 if rng.random() < 0.75 else 3
    def one():
        return ", ".join(str(rng.randint(-4, 4)) for _ in range(n))
    a = one()
    if rng.random() < 0.2:                           # 平行になりやすい組も混ぜる
        k = rng.randint(-3, 3)
        b = ", ".join(str(int(x) * k) for x in a.split(", "))
        return (a, b)
    return (a, one())


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
    script = os.path.join(ROOT, "tools", "vector.py")
    bad = 0
    for va, vb in cases:
        tail = ["--a", va, "--b", vb, "--steps", "--latex"]
        c = run([exe, "vec"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] a=(%s) b=(%s)" % (va, vb))
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  a=(%-12s) b=(%-12s) -> %s" % (va, vb, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
