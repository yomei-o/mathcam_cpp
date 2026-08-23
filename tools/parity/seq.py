"""数列と Σ のパリティ — 同じ入力で C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/seq.py                   # 固定 + 乱数
  python tools/parity/seq.py --n 400 --seed 3

solve / calc と同じで、**答えだけでなく手順の列（規則の名前・説明・各段の式）まで比べる**。
CLI の `--steps --latex` の全行をそのまま突き合わせるので、表示の文言まで一致を要求する。

乱数は「教科書に出る形」に寄せて作る。Σ は多項式（k^3 まで）と等比、下端が 1 でないもの、
上端が数のもの。数列は 等差・等比・階差 と、どれでもない並び（見分けられませんと言うか）。
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

# (サブコマンド, 引数の並び)
FIXED = [
    ("sum", ["--expr", "k^2"]),
    ("sum", ["--expr", "k"]),
    ("sum", ["--expr", "1"]),
    ("sum", ["--expr", "5"]),
    ("sum", ["--expr", "k^3"]),
    ("sum", ["--expr", "3k^2 - k"]),
    ("sum", ["--expr", "k^2 + k"]),
    ("sum", ["--expr", "2k + 1"]),
    ("sum", ["--expr", "k(k+1)"]),
    ("sum", ["--expr", "(k+1)^2"]),
    ("sum", ["--expr", "k^3 - 3k^2 + 2k"]),
    ("sum", ["--expr", "2^(k-1)"]),
    ("sum", ["--expr", "3*2^k"]),
    ("sum", ["--expr", "(1/2)^k"]),
    ("sum", ["--expr", "k^4"]),                       # 未対応と言うか
    ("sum", ["--expr", "sin(k)"]),                    # 未対応と言うか
    ("sum", ["--expr", "k^2", "--to", "10"]),
    ("sum", ["--expr", "k^2", "--to", "1"]),
    ("sum", ["--expr", "k^2", "--to", "0"]),
    ("sum", ["--expr", "k", "--from", "3", "--to", "n"]),
    ("sum", ["--expr", "k^2", "--from", "5", "--to", "10"]),
    ("sum", ["--expr", "k^2 + 1", "--from", "2", "--to", "n"]),
    ("sum", ["--expr", "2^k", "--from", "0", "--to", "n"]),
    ("sum", ["--expr", "k", "--from", "-3", "--to", "n"]),
    ("sum", ["--expr", "sum(k, 1, n, k^2)"]),
    ("sum", ["--expr", "sum(i, 1, m, i^3)"]),
    ("sum", ["--expr", "j^2 - j", "--var", "j", "--to", "m"]),
    ("seq", ["--terms", "2, 5, 8, 11"]),
    ("seq", ["--terms", "1, 3, 5, 7, 9"]),
    ("seq", ["--terms", "10, 7, 4, 1"]),
    ("seq", ["--terms", "3, 6, 12, 24"]),
    ("seq", ["--terms", "1, 2, 4, 8, 16"]),
    ("seq", ["--terms", "8, 4, 2, 1"]),
    ("seq", ["--terms", "1, 2, 4, 7, 11"]),
    ("seq", ["--terms", "1, 4, 9, 16, 25"]),
    ("seq", ["--terms", "1, 3, 7, 15, 31"]),
    ("seq", ["--terms", "2, 3, 6, 15, 42"]),
    ("seq", ["--terms", "1, 1, 2, 3, 5, 8"]),         # 見分けられませんと言うか
    ("seq", ["--terms", "1, 2"]),                     # 項が足りない
    ("seq", ["--terms", "5, 5, 5, 5"]),
    ("seq", ["--terms", "1/2, 1, 3/2, 2"]),
    ("seq", ["--terms", "2, 5, 8, 11", "--nth", "10"]),
    ("seq", ["--terms", "3, 6, 12, 24", "--nth", "8"]),
    ("seq", ["--terms", "1, 2, 4, 7, 11", "--nth", "20"]),
]


def gen_sum(rng):
    """Σ。多項式（k^3 まで）と等比を、下端・上端を振って作る。"""
    v = rng.choice(["k", "k", "k", "i", "j"])
    if rng.random() < 0.22:                            # 等比
        r = rng.choice([2, 3, -2, "1/2", "1/3"])
        c = rng.randint(-4, 4) or 2
        sh = rng.choice(["", "-1", "+1"])
        body = "%d*(%s)^(%s%s)" % (c, r, v, sh)
    else:                                              # 多項式
        deg = rng.randint(0, 3)
        parts = []
        for d in range(deg + 1):
            co = rng.randint(-5, 5)
            if co == 0 and d != deg:
                continue
            if co == 0:
                co = 1
            if d == 0:
                parts.append("%d" % co)
            elif d == 1:
                parts.append("%d%s" % (co, v))
            else:
                parts.append("%d%s^%d" % (co, v, d))
        body = " + ".join(parts) if parts else "1"
    args = ["--expr", body]
    if v != "k":
        args += ["--var", v]
    x = rng.random()
    if x < 0.2:
        args += ["--to", str(rng.randint(1, 12))]
    elif x < 0.35:
        args += ["--from", str(rng.randint(2, 5)), "--to", "n"]
    elif x < 0.45:
        args += ["--from", str(rng.randint(-3, 0)), "--to", "n"]
    elif x < 0.55:
        args += ["--from", str(rng.randint(1, 4)), "--to", str(rng.randint(1, 12))]
    return ("sum", args)


def gen_seq(rng):
    """数列。等差・等比・階差・どれでもない、を混ぜて項の並びを作る。"""
    kind = rng.random()
    cnt = rng.randint(3, 6)
    if kind < 0.3:                                     # 等差
        a, d = rng.randint(-9, 9), rng.randint(-5, 5)
        vals = [a + d * i for i in range(cnt)]
    elif kind < 0.55:                                  # 等比
        a, r = rng.randint(-5, 5) or 3, rng.choice([2, 3, -2, -1])
        vals = [a * r ** i for i in range(cnt)]
    elif kind < 0.85:                                  # 階差（差が等差 or 等比）
        cnt = max(cnt, 4)
        a = rng.randint(-6, 6)
        b0, bd = rng.randint(-4, 4) or 1, rng.randint(-3, 3)
        geo = rng.random() < 0.4
        vals, cur = [a], a
        for i in range(cnt - 1):
            step = b0 * (2 ** i) if geo else b0 + bd * i
            cur += step
            vals.append(cur)
    else:                                              # どれでもない
        vals = [rng.randint(-9, 9) for _ in range(cnt)]
    args = ["--terms", ", ".join(str(v) for v in vals)]
    if rng.random() < 0.2:
        args += ["--nth", str(rng.randint(1, 12))]
    return ("seq", args)


def gen(rng):
    return gen_sum(rng) if rng.random() < 0.6 else gen_seq(rng)


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
        print("[SKIP] mathcam の実行ファイルが無い（sh build/cc.sh pure/mathcam.cpp -o mathcam.exe）")
        return 0

    rng = random.Random(a.seed)
    cases = list(FIXED) + [gen(rng) for _ in range(a.n)]
    pyexe = sys.executable
    script = os.path.join(ROOT, "tools", "seq.py")
    bad = 0
    for sub, args in cases:
        tail = args + ["--steps", "--latex"]
        c = run([exe, sub] + tail)
        p = run([pyexe, script, sub] + tail)
        if c != p:
            print("[FAIL] %s %s" % (sub, " ".join(args)))
            print("   cpp: %s" % " / ".join(c))
            print("   py : %s" % " / ".join(p))
            bad += 1
        elif a.verbose:
            print("  ok  %-40s -> %s" % (sub + " " + " ".join(args), c[-1] if c else ""))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d）、%d 件が不一致"
          % (len(cases), len(FIXED), a.n, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
