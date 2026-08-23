"""solve のパリティ — 同じ方程式を入れたら C++ と Python が同じ手順・同じ答えを出すか。

  python tools/parity/solve.py                 # 固定 + 乱数で作った方程式
  python tools/parity/solve.py --n 400 --seed 3

答えだけを比べるのでは足りない。**手順の列（規則の名前・説明・各段の式）まで比べる**。
手順がこのプロジェクトの成果物そのもので、片方だけ変えたら「言語によって解き方が違う」
アプリになる。CLI の出力（`--steps --latex` の全行）をそのまま突き合わせるのが一番強い縛りで、
これは表示の文言まで含めて一致を要求する。

乱数の方程式は「解ける形」に寄せて作る（一次と二次を、整数解・分数解・無理数解・実数解なし
の 4 通りが混ざるように）。乱数で任意の式を作ると大半が「対応外」になってテストが薄くなる。
"""
import argparse
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X          # noqa: E402
import solve as S         # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED = [
    "2x + 3 = 7", "x + 1 = 1", "3x = 0", "x/2 + 1 = 3", "2x = x + 5",
    "x/2 + x/3 = 5", "-x + 4 = 1", "2(x + 1) = 6", "5 = x", "0 = x - 7",
    "x^2 - 5x + 6 = 0", "x^2 - 4 = 0", "x^2 = 2", "x^2 = 8", "x^2 + x + 1 = 0",
    "x^2 + 2x + 1 = 0", "2x^2 - 8 = 0", "x^2 - x = 0", "3x^2 + 5x - 2 = 0",
    "x^2 + x = 1", "(x + 1)(x - 2) = 0", "x^2/2 - 2 = 0", "x^2 + 1 = 0",
    "3 = 3", "4 = 5", "x = x", "x = x + 1",
    "y^2 - 9 = 0", "2t + 1 = 0",
    # 不等式（負の数で割ると向きが変わる所を必ず通す）
    "3x - 5 > 1", "-2x + 1 >= 7", "x/2 + 1 < x/3", "2x <= 6", "x > x + 1", "x < x + 1",
    "-x > 3", "4 - x <= 0", "5 > 2", "0 >= 1",
    # 連立方程式（加減法・代入法・そのまま解ける・解なし・無限）
    "x + y = 5, 2x - y = 1", "2x + 3y = 8, 3x - 2y = -1", "y = 2x - 1, 3x + y = 9",
    "2x = 6, x + y = 5", "x + y = 1, 2x + 2y = 5", "x + y = 1, 2x + 2y = 2",
    "x/2 + y = 3, x - y = 1", "3a + b = 7, a - b = 1",
    # 連立不等式（重なる・重ならない・1 点・片側だけ）
    "2x > 4, x - 1 <= 4", "x > 5, x < 2", "x >= 2, x <= 2", "x > 1, x > 3",
    "-x > -5, 2x >= 4",
    # 三角方程式（0 <= x < 2pi。表に無い値は「解けません」と言うところも縛る）
    "sin(x) = 1/2", "cos(x) = 1/2", "tan(x) = 1", "sin(x) = 0", "cos(x) = -1",
    "sin(x) = 2", "cos(x) = -2", "sin(2x) = 1/2", "sin(x + pi/6) = 1/2",
    "cos(x) = sqrt(3)/2", "sin(x) = 1/3", "tan(x) = sqrt(3)", "cos(3x) = 0",
    # 指数方程式
    "2^x = 8", "2^x = 3", "2^(x+1) = 4^x", "3^(x^2) = 9", "2^x = 1/8", "5^(2x) = 25",
    "2^x = 0", "2^x = -1", "9^x = 27", "4^(x-1) = 8",
    # 絶対値（方程式と不等式。教科書の場合分けと「確かめる」まで）
    "|x - 1| = 3", "|x| = 5", "|x| = -2", "|2x + 1| = 7", "|x - 1| = x",
    "|x - 1| = x - 3", "|x| = 0", "|x^2 - 4| = 0", "abs(x - 1) = 3",
    "|x - 1| < 2", "|x - 1| <= 2", "|x| > 3", "|x - 2| >= 1", "|x| < -1", "|x| > -1",
    "|2x - 3| < 5", "|3 - x| > 1",
    # 高次方程式（因数定理・n 乗根）と複素数解
    "x^3 - 6x^2 + 11x - 6 = 0", "x^3 - x = 0", "x^3 + 1 = 0", "x^3 = 8", "x^3 - 2 = 0",
    "x^4 - 5x^2 + 4 = 0", "x^4 - 16 = 0", "x^4 = 5", "x^4 + 1 = 0", "x^5 - x = 0",
    "2x^3 - 3x^2 - 3x + 2 = 0", "x^3 + x + 1 = 0", "x^3 - 3x^2 + 3x - 1 = 0",
    "x^2 + 1 = 0", "x^2 + x + 1 = 0", "x^2 - 2x + 5 = 0", "2x^2 + 2x + 5 = 0",
    "x^6 - 1 = 0", "x^3/2 - 4 = 0", "y^3 + 8 = 0",
    # 対数方程式（真数条件で偽の解を捨てるところまで）
    "log(2, x) = 3", "ln(x) = 0", "ln(x) = 1", "log(2, x) + log(2, x - 2) = 3",
    "log(10, x) = 2", "log(2, x) = log(2, 5)", "log(3, x) = -2", "2*log(2, x) = 4",
    "log(2, x) + log(2, x + 1) = 1", "log(5, x) = 0",
    # 二次不等式（外側・内側・実数解なし・重解・無理数の境界・x^2 の係数が負）
    "x^2 - 5x + 6 > 0", "x^2 - 5x + 6 >= 0", "x^2 - 5x + 6 < 0", "x^2 - 5x + 6 <= 0",
    "x^2 - 2 < 0", "x^2 - 2 >= 0", "x^2 + x + 1 > 0", "x^2 + x + 1 < 0",
    "x^2 - 2x + 1 <= 0", "x^2 - 2x + 1 < 0", "x^2 - 2x + 1 >= 0", "x^2 - 2x + 1 > 0",
    "-x^2 + 4 > 0", "-x^2 + 4 <= 0", "2x^2 - 3x - 2 >= 0", "x^2 < 4x",
    "x^2 > 3x - 2", "x^2 + 1 <= 2x - 3", "3x^2 <= 12", "y^2 - 9 > 0",
    # 二次を含む連立不等式（「または」どうしの重なりが出る）
    "x^2 - 5x + 6 > 0, x > 0", "x^2 - 9 >= 0, x^2 - 25 <= 0", "x^2 - 4 < 0, x >= 0",
    "x^2 - 5x + 6 <= 0, x < 2", "x^2 > 1, x^2 < 4", "x^2 - 1 > 0, x < -3",
]


def gen_ineq(rng):
    """一次不等式。**負の係数を必ず混ぜる**（向きが変わる手を通すため）。"""
    v = rng.choice(["x", "x", "y", "t"])
    op = rng.choice(["<", "<=", ">", ">="])
    a = rng.randint(-9, 9) or -2
    b = rng.randint(-9, 9)
    c = rng.randint(-9, 9)
    if rng.random() < 0.25:                          # 分数係数（分母を払う手が出る）
        return "%s%s/%d + %d %s %d" % (a, v, rng.randint(2, 6), b, op, c)
    if rng.random() < 0.2:                           # 右辺にも文字がある形
        return "%d%s + %d %s %d%s + %d" % (a, v, b, op, rng.randint(-4, 4), v, c)
    return "%d%s + %d %s %d" % (a, v, b, op, c)


def gen_sys(rng):
    """2 元 1 次の連立方程式。整数解・分数解・解なし・無限が混ざるように作る。"""
    v1, v2 = rng.choice([("x", "y"), ("x", "y"), ("a", "b")])
    a1, b1 = rng.randint(-5, 5) or 1, rng.randint(-5, 5) or 2
    a2, b2 = rng.randint(-5, 5) or 3, rng.randint(-5, 5) or 1
    if rng.random() < 0.12:                          # 係数が比例（解なし or 無限）
        k = rng.choice([2, 3, -2])
        a2, b2 = a1 * k, b1 * k
    c1, c2 = rng.randint(-9, 9), rng.randint(-9, 9)
    if rng.random() < 0.2:                           # 「y = …」の形（代入法が出る）
        return "%s = %d%s + %d, %d%s + %d%s = %d" % (v2, a1, v1, c1, a2, v1, b2, v2, c2)
    return "%d%s + %d%s = %d, %d%s + %d%s = %d" % (a1, v1, b1, v2, c1, a2, v1, b2, v2, c2)


def gen_sys_ineq(rng):
    """連立不等式（2 本）。重なる・重ならない・1 点が混ざる。"""
    v = rng.choice(["x", "x", "y"])
    op1 = rng.choice([">", ">="])
    op2 = rng.choice(["<", "<="])
    a1 = rng.randint(-4, 4) or 1
    a2 = rng.randint(-4, 4) or -1
    return "%d%s + %d %s %d, %d%s + %d %s %d" % (
        a1, v, rng.randint(-6, 6), op1, rng.randint(-9, 9),
        a2, v, rng.randint(-6, 6), op2, rng.randint(-9, 9))


def gen_quad_ineq(rng):
    """二次不等式。**根から作る場合と作らない場合を混ぜる**（因数分解できる形・無理数解・
    実数解なしの 3 通りが必ず出るように）。x^2 の係数が負の形も入れる（向きが変わる手）。
    """
    v = rng.choice(["x", "x", "y", "t"])
    op = rng.choice(["<", "<=", ">", ">="])
    a = rng.choice([1, 1, 1, 2, 3, -1, -2])
    if rng.random() < 0.5:                           # 根から作る（因数分解できる）
        r1, r2 = rng.randint(-6, 6), rng.randint(-6, 6)
        b = -a * (r1 + r2)
        c = a * r1 * r2
    else:                                            # 無理数解・実数解なしも出る
        b, c = rng.randint(-9, 9), rng.randint(-9, 9)
    if rng.random() < 0.2:                           # 右辺にも項がある形（移項の手が出る）
        return "%d%s^2 + %d%s %s %d" % (a, v, b, v, op, -c)
    return "%d%s^2 + %d%s + %d %s 0" % (a, v, b, v, c, op)


def gen_sys_quad(rng):
    """二次を含む連立不等式（範囲の列どうしの重なり）。"""
    v = rng.choice(["x", "x", "y"])
    op1 = rng.choice(["<", "<=", ">", ">="])
    r1, r2 = rng.randint(-5, 5), rng.randint(-5, 5)
    b, c = -(r1 + r2), r1 * r2
    op2 = rng.choice(["<", "<=", ">", ">="])
    return "%s^2 + %d%s + %d %s 0, %s %s %d" % (v, b, v, c, op1, v, op2, rng.randint(-6, 6))


def gen(rng):
    """解ける形の式。方程式・不等式・連立をまとめて振る。"""
    kind = rng.random()
    if kind < 0.2:
        return gen_ineq(rng)
    if kind < 0.35:
        return gen_sys(rng)
    if kind < 0.45:
        return gen_sys_ineq(rng)
    if kind < 0.60:
        return gen_quad_ineq(rng)
    if kind < 0.68:
        return gen_sys_quad(rng)
    v = rng.choice(["x", "x", "x", "y", "t"])
    if rng.random() < 0.45:
        a = rng.randint(-9, 9) or 2
        b = rng.randint(-9, 9)
        c = rng.randint(-9, 9)
        if rng.random() < 0.3:                       # 分数係数（分母を払う手が出る）
            return "%s%s/%d + %d = %d" % (a, v, rng.randint(2, 6), b, c)
        return "%d%s + %d = %d" % (a, v, b, c)
    a = rng.choice([1, 1, 1, 2, 3, -1])
    if rng.random() < 0.12:                           # 3 次（根から作る / 作らない）
        if rng.random() < 0.6:
            r1, r2, r3 = rng.randint(-4, 4), rng.randint(-4, 4), rng.randint(-4, 4)
            return "%s^3 + %d%s^2 + %d%s + %d = 0" % (
                v, -(r1 + r2 + r3), v, r1 * r2 + r2 * r3 + r3 * r1, v, -r1 * r2 * r3)
        return "%s^3 + %d%s + %d = 0" % (v, rng.randint(-6, 6), v, rng.randint(-9, 9))
    if rng.random() < 0.5:                            # 根から作る（因数分解できる形）
        r1, r2 = rng.randint(-6, 6), rng.randint(-6, 6)
        b = -a * (r1 + r2)
        c = a * r1 * r2
        return "%d%s^2 + %d%s + %d = 0" % (a, v, b, v, c)
    b, c = rng.randint(-9, 9), rng.randint(-9, 9)     # 無理数解や実数解なしも混ざる
    return "%d%s^2 + %d%s + %d = 0" % (a, v, b, v, c)


def cpp(exe, src):
    p = subprocess.run([exe, "solve", "--expr", src, "--steps", "--latex"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    return p.stdout.splitlines()


def py(src):
    e, err = X.parse(src)
    if err:
        return ["parse error: %s" % err]
    s = S.solve(e)
    out = []
    if not s.ok:
        return S.answer_lines(s, True)
    for i, st in enumerate(s.steps, 1):
        out.append("%d. [%s] %s" % (i, st.rule, st.note))
        out.append("   %s" % X.to_latex(st.after))
    out.extend(S.answer_lines(s, True))
    return out


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
    bad = 0
    for src in cases:
        c, p = cpp(exe, src), py(src)
        if c != p:
            print("[FAIL] %s" % src)
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
