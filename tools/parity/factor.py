"""因数分解のパリティ — 同じ式で C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/factor.py
  python tools/parity/factor.py --n 400 --seed 3

**答えが元の式と等しいこと**も毎回確かめる（展開して突き合わせる）。因数分解は
「読める形にする」仕事なので、形が違っても値が変われば即バグ。手順の全行も比べる。

乱数は「分けられる形」と「分けられない形」を混ぜて作る（根から作る / 適当な係数）。
"""
import argparse
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X          # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED = [
    "x^2 + 5x + 6", "x^2 - 5x + 6", "2x^2 - 3x - 2", "4x^2 - 25", "x^2 - 2x + 1",
    "9x^2 - 12x + 4", "x^2 + 12xy + 36y^2", "x^2 - y^2", "6x^2y + 9xy^2",
    "x^3 - 6x^2 + 11x - 6", "x^3 - 8", "x^2 - 2", "x^2 + 1", "3x + 6", "x^2 + x",
    "49a^2 - 81b^2", "5 - 6a + a^2", "-x^2 + 4", "2x^2 + 8x + 8", "x^4 - 16",
    "(x + 1)(x + 2)", "x^2 + 2xy - 3y^2", "x + y + z", "5", "0", "x", "-3x^2 - 6x",
    "x^2/4 - 1", "12x^3 - 3x", "a^2 - 2ab + b^2", "4x^2 + 12xy + 9y^2", "x^2 + 4x + 5",
]


def gen(rng):
    """分けられる形と分けられない形を混ぜる。"""
    k = rng.random()
    v = rng.choice(["x", "x", "x", "a", "t"])
    w = rng.choice(["y", "b"])
    if k < 0.30:                                     # 根から作る 2 次（必ず分かれる）
        r1, r2 = rng.randint(-6, 6), rng.randint(-6, 6)
        a = rng.choice([1, 1, 1, 2, 3, -1])
        return "%d%s^2 + %d%s + %d" % (a, v, -a * (r1 + r2), v, a * r1 * r2)
    if k < 0.45:                                     # 適当な 2 次（分かれないこともある）
        return "%d%s^2 + %d%s + %d" % (rng.randint(1, 4), v, rng.randint(-9, 9), v,
                                       rng.randint(-9, 9))
    if k < 0.60:                                     # 共通因数つき
        return "%d%s^3 + %d%s^2 + %d%s" % (rng.randint(2, 6), v, rng.randint(-9, 9), v,
                                           rng.randint(-9, 9), v)
    if k < 0.75:                                     # 2 変数の同次 2 次
        r1, r2 = rng.randint(-4, 4), rng.randint(-4, 4)
        return "%s^2 + %d%s%s + %d%s^2" % (v, -(r1 + r2), v, w, r1 * r2, w)
    if k < 0.88:                                     # 根から作る 3 次（因数定理）
        r1, r2, r3 = rng.randint(-4, 4), rng.randint(-4, 4), rng.randint(-4, 4)
        b = -(r1 + r2 + r3)
        c = r1 * r2 + r2 * r3 + r3 * r1
        d = -r1 * r2 * r3
        return "%s^3 + %d%s^2 + %d%s + %d" % (v, b, v, c, v, d)
    # 単項式や、そもそも分けようのないもの
    return rng.choice(["%d%s" % (rng.randint(2, 9), v), "%d" % rng.randint(-9, 9),
                       "%s + %s" % (v, w), "%s^2 + %s^2" % (v, w)])


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
    script = os.path.join(ROOT, "tools", "factor.py")
    bad = wrong = 0
    for src in cases:
        tail = ["--expr", src, "--steps", "--latex"]
        c = run([exe, "factor"] + tail)
        p = run([pyexe, script] + tail)
        if c != p:
            print("[FAIL] %s" % src)
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
            continue
        # **値が変わっていないこと**（因数分解は形を変えるだけ）
        got = run([exe, "factor", "--expr", src])
        e0, err0 = X.parse(src)
        e1, err1 = X.parse(got[0]) if got else (None, "empty")
        if err0 or err1 or not X.equal(X.expand(e0), X.expand(e1)):
            print("[FAIL] 値が変わった: %s -> %s" % (src, got[0] if got else ""))
            wrong += 1
        elif a.verbose:
            print("  ok  %-26s -> %s" % (src, got[0]))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致、%d 件が値ずれ"
          % (len(cases), len(FIXED), a.n, bad, wrong))
    return 1 if (bad or wrong) else 0


if __name__ == "__main__":
    sys.exit(main())
