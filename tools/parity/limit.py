"""極限のパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/limit.py
  python tools/parity/limit.py --n 300 --seed 5
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
    ("x^2 + 1", "2"), ("(x^2 - 1)/(x - 1)", "1"), ("(x^2 - 4)/(x - 2)", "2"),
    ("1/x", "0"), ("(2x^2 + 1)/(x^2 - x)", "inf"), ("(x + 1)/(x^2 + 1)", "inf"),
    ("(x^3 + 1)/(x - 1)", "inf"), ("(x^3 + 1)/(x - 1)", "-inf"), ("sin(x)/x", "0"),
    ("sin(3x)/(2x)", "0"), ("(x^3 - 1)/(x - 1)", "1"), ("(x^2 - 1)/(x - 1)^2", "1"),
    ("tan(x)/x", "0"), ("exp(x)", "0"), ("ln(x)", "1"), ("(-2x^3 + 1)/x^2", "inf"),
    ("(-2x^3 + 1)/x^2", "-inf"), ("x/(x + 1)", "inf"), ("(x - 3)/(x^2 - 9)", "3"),
    ("(x^2 - 5x + 6)/(x - 2)", "2"), ("1/(x - 1)^2", "1"), ("x^3 - 2x", "-1"),
    ("sqrt(x)", "4"), ("(x^2 + 1)/x", "0"), ("sin(x)/(3x)", "0"), ("cos(x)/x", "0"),
]


def gen(rng):
    k = rng.random()
    a = rng.randint(1, 4)
    b = rng.randint(-5, 5)
    r1, r2 = rng.randint(-4, 4), rng.randint(-4, 4)
    if k < 0.3:                                      # 0/0 になる形（根から作る）
        return ("(x^2 + %dx + %d)/(x + %d)" % (-(r1 + r2), r1 * r2, -r1), str(r1))
    if k < 0.5:                                      # そのまま代入
        return ("%dx^2 + %dx + %d" % (a, b, rng.randint(-9, 9)), str(rng.randint(-3, 3)))
    if k < 0.7:                                      # x -> ±∞
        return ("(%dx^%d + %d)/(%dx^%d + 1)" % (a, rng.randint(1, 3), b,
                                                rng.randint(1, 4), rng.randint(1, 3)),
                rng.choice(["inf", "-inf"]))
    if k < 0.85:                                     # 分母だけ 0
        return ("(x + %d)/(x + %d)^%d" % (b, -r1, rng.randint(1, 2)), str(r1))
    return (rng.choice(["sin(%dx)/(%dx)" % (a, rng.randint(1, 4)), "tan(%dx)/x" % a]), "0")


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
    script = os.path.join(ROOT, "tools", "limit.py")
    bad = 0
    for src, to in cases:
        tail = ["--expr", src, "--to", to, "--steps", "--latex"]
        c = run([exe, "limit"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] %s -> %s" % (src, to))
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-28s -> %-5s %s" % (src, to, c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
