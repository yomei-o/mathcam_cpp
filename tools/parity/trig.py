"""三角関数の変形のパリティ — C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/trig.py
  python tools/parity/trig.py --n 300 --seed 5
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

# (式, --mode。空なら auto)
FIXED = [
    ("sin(x) + sqrt(3)cos(x)", ""), ("sin(x) + cos(x)", ""), ("sqrt(3)sin(x) + cos(x)", ""),
    ("sin(x) - cos(x)", ""), ("-sin(x) - cos(x)", ""), ("sqrt(3)sin(x) - cos(x)", ""),
    ("2sin(x) + 2cos(x)", ""), ("2sin(x) + 3cos(x)", ""), ("2sin(x) + 3cos(x)", "compose"),
    ("sin(2x)", ""), ("cos(2x)", ""), ("sin(3x)", ""), ("cos(3x)", ""),
    ("sin(x + pi/3)", ""), ("cos(x - pi/4)", ""), ("sin(x + y)", ""), ("cos(x + y)", ""),
    ("cos(2x + pi/3)", ""), ("sin(x)", ""), ("x + 1", ""), ("sin(2x) + cos(2x)", ""),
    ("sin(x) + sqrt(3)cos(x)", "expand"), ("sin(4x)", ""), ("3sin(x)", ""),
    ("cos(x) + sin(x) + 1", ""), ("sin(x)cos(x)", ""),
]


def gen(rng):
    k = rng.random()
    v = rng.choice(["x", "x", "t"])
    if k < 0.35:                                     # 合成（特別角になるものとならないもの）
        a = rng.choice(["1", "2", "3", "sqrt(3)", "-1", "sqrt(2)"])
        b = rng.choice(["1", "2", "3", "sqrt(3)", "-1", "sqrt(2)"])
        return ("%s*sin(%s) + %s*cos(%s)" % (a, v, b, v), "")
    if k < 0.6:                                      # n 倍角
        return ("%s(%d%s)" % (rng.choice(["sin", "cos"]), rng.randint(2, 4), v), "")
    if k < 0.8:                                      # 加法定理
        return ("%s(%s + %s)" % (rng.choice(["sin", "cos"]), v,
                                 rng.choice(["pi/3", "pi/4", "pi/6", "y", "pi/2"])), "")
    return (rng.choice(["%s(%s)" % (rng.choice(["sin", "cos", "tan"]), v),
                        "%s + 1" % v, "sin(%s)^2" % v]), rng.choice(["", "compose", "expand"]))


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
    script = os.path.join(ROOT, "tools", "trig.py")
    bad = 0
    for src, mode in cases:
        tail = ["--expr", src] + (["--mode", mode] if mode else []) + ["--steps", "--latex"]
        c = run([exe, "trig"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] %s%s" % (src, (" [" + mode + "]") if mode else ""))
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
