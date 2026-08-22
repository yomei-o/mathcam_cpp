"""デモのサンプル画像（wasm/samples/s1..s7.png）を作り直す。

**リポジトリの数式書体で描く**（KaTeX Main + KaTeX Math Italic、マイナスは U+2212）。
学習データと同じ字形になり、実物の教科書にも近い。画像は自前の組版器で描いたものなので
ライセンスの問題がない（教科書の写真は入れられない）。

  python tools/make_samples.py            # 作り直す
  python tools/make_samples.py --check    # 読み直して式が合うかだけ見る
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROMAN = os.path.join(ROOT, "fonts", "katex", "KaTeX_Main-Regular.ttf")
ITALIC = os.path.join(ROOT, "fonts", "katex", "KaTeX_Math-Italic.ttf")

# (ファイル名, 式, 小学校の書き方か, px)
SAMPLES = [
    ("s1.png", "x^2 - 5x + 6 = 0", False, 56),
    ("s2.png", "5x/6 = 5", False, 56),
    ("s3.png", "(x + 1)^2", False, 56),
    ("s4.png", "x^2 + x = 1", False, 56),
    ("s5.png", "3x^2 + 5x - 2 = 0", False, 56),
    ("s6.png", "{1.8 × 3.5 - (10.2 - 6.8)} × 9", True, 52),
    ("s7.png", "mixed(2,5,8) × frac(4,7) - (mixed(5,1,3) - frac(1,2)) ÷ 5", True, 52),
]


def exe():
    for name in ("mathcam.exe", "mathcam"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            return p
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--model", default=os.path.join("models", "sym_det_v4.onnx"))
    a = ap.parse_args()
    mc = exe()
    if not mc:
        print("mathcam の実行ファイルが無い")
        return 1

    for name, src, arith, px in SAMPLES:
        out = os.path.join(ROOT, "wasm", "samples", name)
        if not a.check:
            cmd = [mc, "render", "--expr", src, "--out", out, "--px", str(px),
                   "--font", ROMAN, "--font-italic", ITALIC, "--italic", "--minus", "2212"]
            if arith:
                cmd.append("--arith")
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               encoding="utf-8", errors="replace")
            print("%-8s %s" % (name, (p.stdout or "").strip().splitlines()[-1:]))
            if p.returncode != 0:
                return 1
        # **描いたら読み直す**（絵だけ作って満足すると、デモで読めないものが並ぶ）
        p2 = subprocess.run([mc, "photo", "--img", out, "--model", a.model],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            encoding="utf-8", errors="replace")
        read = ""
        for line in (p2.stdout or "").splitlines():
            if line.startswith("読めた式: "):
                read = line[len("読めた式: "):].strip()
        print("    読み直し: %s" % (read or "(読めない)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
