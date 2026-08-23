"""漸化式のパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/recur.py
  python tools/parity/recur.py --n 300 --seed 5
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

# (--next, --a1)
FIXED = [
    ("a + 3", "2"), ("2a", "3"), ("2a + 1", "1"), ("3a - 4", "3"), ("a + n", "1"),
    ("a + 2n - 1", "0"), ("a + 2^n", "1"), ("a*n", "1"), ("-2a + 3", "0"),
    ("a/2 + 1", "4"), ("a", "5"), ("a - 2", "10"), ("3a", "1"), ("a + n^2", "0"),
    ("-a + 4", "1"), ("a + 3^n", "2"), ("4a - 6", "3"), ("a/3 + 2", "9"),
]


def gen(rng):
    k = rng.random()
    a1 = str(rng.randint(-5, 9))
    if k < 0.25:
        return ("a + %d" % rng.randint(-6, 6), a1)
    if k < 0.5:
        return ("%da" % (rng.randint(2, 4) * rng.choice([1, -1])), a1)
    if k < 0.75:
        return ("%da + %d" % (rng.randint(2, 4) * rng.choice([1, -1]), rng.randint(-6, 6)), a1)
    return ("a + %s" % rng.choice(["n", "2n", "n^2", "2^n", "%dn + %d" % (rng.randint(1, 4),
                                                                         rng.randint(-4, 4))]),
            a1)


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
    script = os.path.join(ROOT, "tools", "recur.py")
    bad = 0
    for nxt, a1 in cases:
        tail = ["--next", nxt, "--a1", a1, "--steps", "--latex"]
        c = run([exe, "recur"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] a_(n+1) = %s, a_1 = %s" % (nxt, a1))
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-16s a1=%-3s -> %s" % (nxt, a1, c[1] if len(c) > 1 else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
