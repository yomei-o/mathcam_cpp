"""組版のパリティ — 同じ式を組んだら C++ と Python が同じ枠を出すか。

  python tools/parity/typeset.py                 # 固定 + 乱数
  python tools/parity/typeset.py --n 400 --px 40

**枠（記号のクラスと画素の矩形）と画像サイズを厳密に比べる。** そこが学習データの正解であり、
認識側との契約だから。絵の画素は比べない（C++ は stb_truetype、Python は FreeType で塗り方が
違う。一致させるには片方のラスタライザを移植することになり、得られるのは「同じ絵」だけ）。

あわせて、正解として使えるかの不変条件も見る:
  * 枠が画像の中に収まっている
  * 幅・高さが 1 画素以上ある
  * 記号の数が両実装で同じ
"""
import argparse
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X          # noqa: E402
import typeset as T       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIXED = [
    "2/3 + 1/6", "x^2 - 5x + 6 = 0", "1/2 x + sqrt(2) = 3/4", "(x+1)/(x-2) = 5",
    "sqrt(x^2 + 1)/3 - 2/(x+1) = 0", "x^3 + 2x^2 - x + 7", "-x + 4 = 1",
    "sqrt(2)", "2^10", "(x+1)^3", "1/(2x)", "x/(y+1)", "sin(x) + cos(x)",
    "3x^2/4 = 1/2", "-3/4", "x^(1/2) + x^2", "ln(x)/x", "2(x+1)(x-1)",
]


def gen(rng, depth=0):
    if depth >= 2 or rng.random() < 0.3:
        r = rng.random()
        if r < 0.5:
            return str(rng.randint(-9, 99))
        if r < 0.65:
            return "%d/%d" % (rng.randint(1, 9), rng.randint(2, 9))
        return rng.choice(["x", "y", "t"])
    op = rng.choice(["+", "-", "*", "/", "^", "sqrt", "paren", "eq"])
    a = gen(rng, depth + 1)
    if op == "sqrt":
        return "sqrt(%s)" % a
    if op == "paren":
        return "(%s)" % a
    b = gen(rng, depth + 1)
    if op == "^":
        return "(%s)^%s" % (a, rng.choice(["2", "3", "(1/2)"]))
    if op == "eq":
        return "%s = %s" % (a, b)
    return "(%s) %s (%s)" % (a, op, b)


def cpp_labels(exe, src, px, font):
    tmp = os.path.join(ROOT, "scratch", "_parity_labels.txt")
    cmd = [exe, "render", "--expr", src, "--labels", tmp, "--px", str(px)]
    if font:
        cmd += ["--font", font]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0 or not os.path.exists(tmp):
        return None, (p.stdout or "").strip()
    with open(tmp, encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f if ln.strip()]
    os.remove(tmp)
    return lines, ""


def py_labels(f, src, px):
    e, err = X.parse(src)
    if err:
        return None, "parse error: %s" % err
    w, h, boxes, _draw = T.layout_boxes(f, e, px)
    lines = ["# %s" % src, "# image %d %d" % (w, h)]
    for cls, x0, y0, x1, y1 in boxes:
        lines.append("%s %d %d %d %d" % (cls, x0, y0, x1, y1))
    return lines, ""


def check_invariants(lines):
    """正解として使えるかの最低条件。ここが崩れた学習データは黙って精度を下げる。"""
    w = h = 0
    bad = []
    for ln in lines:
        if ln.startswith("# image"):
            _, _, w, h = ln.split()
            w, h = int(w), int(h)
            continue
        if ln.startswith("#"):
            continue
        cls, x0, y0, x1, y1 = ln.split()
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        if x1 <= x0 or y1 <= y0:
            bad.append("%s の枠が潰れている (%d,%d,%d,%d)" % (cls, x0, y0, x1, y1))
        if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
            bad.append("%s の枠が画像の外 (%d,%d,%d,%d) / 画像 %dx%d" % (cls, x0, y0, x1, y1, w, h))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--px", type=int, default=48)
    ap.add_argument("--font", default="")
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
    try:
        f = T.Font(a.font)
    except SystemExit as e:
        print("[SKIP] %s" % e)
        return 0
    # C++ 側が同じフォントを選ぶように、見つけたパスを明示的に渡す
    font_path = a.font or f.path

    rng = random.Random(a.seed)
    cases = list(FIXED) + [gen(rng) for _ in range(a.n)]
    bad = 0
    inv = 0
    for src in cases:
        c, cerr = cpp_labels(exe, src, a.px, font_path)
        p, perr = py_labels(f, src, a.px)
        if c is None or p is None:
            if (c is None) != (p is None):
                print("[FAIL] 片方だけ失敗: %s（cpp:%s / py:%s）" % (src, cerr, perr))
                bad += 1
            continue
        if c != p:
            print("[FAIL] %s" % src)
            for i in range(max(len(c), len(p))):
                cl = c[i] if i < len(c) else "-"
                pl = p[i] if i < len(p) else "-"
                if cl != pl:
                    print("   cpp: %s" % cl)
                    print("   py : %s" % pl)
            bad += 1
            continue
        v = check_invariants(c)
        if v:
            print("[FAIL] 不変条件: %s" % src)
            for m in v[:3]:
                print("   %s" % m)
            inv += 1
        elif a.verbose:
            print("  ok  %-30s %s" % (src, c[1]))
    print("%d 件を突き合わせ（固定 %d + 乱数 %d、px=%d、font=%s）、不一致 %d 件、不変条件違反 %d 件"
          % (len(cases), len(FIXED), a.n, a.px, os.path.basename(font_path), bad, inv))
    return 1 if (bad or inv) else 0


if __name__ == "__main__":
    sys.exit(main())
