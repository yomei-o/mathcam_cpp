"""学習データ一式（書体を混ぜた train/val）を**1 コマンドで**作り直す。

これまで混ぜ方はその場かぎりのシェルで、リポジトリに残っていなかった。同じデータを
作り直せないと「前より良い / 悪い」が言えないので、混ぜ方をここに置く。

  python tools/make_mix.py --out data7                 # 実物（train 36400 / val 2080）
  python tools/make_mix.py --out /tmp/mix --scale 0.01 # 動作確認（1%）
  python tools/make_mix.py --list                      # 見つかった書体の組だけ出す

## 混ぜ方（なぜこの割合か）

* **書体は多いほど良い**（実写で外した原因の 1 つは字形の違い。教科書はイタリック +
  U+2212 で、それが学習データに無いだけで実写 0/12 だった）。ローマン体と斜体の組で
  持ち、見つかった順に a, b, c... と割り当てる。
* **写真に近い側（`--photo-like`）を厚くする**（実写は綺麗な絵ではない。合成 val が
  100% でも実写が 3/27 まで落ちるのを見た）。1 組の中で photo-like 1600 / 綺麗 1200。
  val は photo-like だけにする（綺麗な絵で選ぶと実写の失敗が見えない）。
* **小学校の計算（× ÷ 帯分数 中括弧）も入れる**（`--arith`。描く道が別なので、
  混ぜないとその記号がまったく出てこない）。

作る枚数は 1 組あたり train 2800 / val 160。13 組で train 36400 / val 2080（data6 と同じ）。
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# 書体の組（ローマン, 斜体）。**あるものだけ使う**ので、Linux と Windows の候補を並べておく。
# 斜体が無い書体は同じファイルを渡す（イタリックの割合が効かなくなるだけで、字形は増える）。
#
# 並びは data6（round 5）で使った 13 組と同じ。**教科書に近い書体を先に置く**
# （cmr10/cmmi10 は Computer Modern、STIX は数式用。実写で外した原因は字形の違いだった）。
# **数式書体はリポジトリに入れてある**（fonts/。ライセンス文つき、合計 3.8MB）。
# 実写の教科書は変数が**数式用のイタリック**で、本文用のイタリック（Liberation Italic など）
# とは字が違う。KaTeX の Math-Italic や cmmi10 がそれで、ここを外すと実写で x が y に化ける。
# 手元・Kaggle・他人の環境で**同じデータが作れる**ようにするため、システムの書体より先に置く。
_R = os.path.join(ROOT, "fonts")
_M = "/usr/local/lib/python3.12/dist-packages/matplotlib/mpl-data/fonts/ttf"
_L = "/usr/share/fonts/truetype/liberation"
_J = "/root/.julia/packages/MathTeXEngine/dUSrK/assets/fonts/Luciole-Math"
_A = "/root/.julia/packages/Animations/OGXDY/docs/src/fonts"
FONT_CANDIDATES = [
    # --- リポジトリに入れた数式書体（どこでも同じものが使える）
    (_R + "/katex/KaTeX_Main-Regular.ttf", _R + "/katex/KaTeX_Math-Italic.ttf"),
    (_R + "/katex/KaTeX_Main-Bold.ttf", _R + "/katex/KaTeX_Math-BoldItalic.ttf"),
    (_R + "/cm/cmr10.ttf", _R + "/cm/cmmi10.ttf"),
    (_R + "/cm/cmb10.ttf", _R + "/cm/cmmib10.ttf"),
    (_R + "/newcm/NewCM10-Regular.otf", _R + "/newcm/NewCM10-Italic.otf"),
    (_R + "/newcm/NewCMMath-Regular.otf", _R + "/newcm/NewCM10-Italic.otf"),
    (_R + "/pagella/TeXGyrePagella-Regular.otf", _R + "/pagella/TeXGyrePagella-Italic.otf"),
    (_R + "/pagella/TeXGyrePagella-Math.otf", _R + "/pagella/TeXGyrePagella-Italic.otf"),
    (_R + "/heros/TeXGyreHeros-Regular.otf", _R + "/heros/TeXGyreHeros-Italic.otf"),
    # --- 環境にあれば使う本文書体（字形の幅を出すため）
    (_M + "/cmr10.ttf", _M + "/cmmi10.ttf"),
    (_M + "/STIXGeneral.ttf", _M + "/STIXGeneralItalic.ttf"),
    (_M + "/DejaVuSerif.ttf", _M + "/DejaVuSerif-Italic.ttf"),
    (_M + "/DejaVuSerif-Bold.ttf", _M + "/DejaVuSerif-BoldItalic.ttf"),
    (_M + "/DejaVuSans.ttf", _M + "/DejaVuSans-Oblique.ttf"),
    (_L + "/LiberationSerif-Regular.ttf", _L + "/LiberationSerif-Italic.ttf"),
    (_L + "/LiberationSerif-Bold.ttf", _L + "/LiberationSerif-BoldItalic.ttf"),
    (_L + "/LiberationSans-Regular.ttf", _L + "/LiberationSans-Italic.ttf"),
    (_A + "/Lato-Regular.ttf", _A + "/Lato-Italic.ttf"),
    (_A + "/Lato-Semibold.ttf", _A + "/Lato-SemiboldItalic.ttf"),
    (_J + "/Luciole-Regular.ttf", _J + "/Luciole-Regular-Italic.ttf"),
    (_J + "/Luciole-Bold.ttf", _J + "/Luciole-Bold-Italic.ttf"),
    (_M + "/cmb10.ttf", _M + "/cmmi10.ttf"),
    # Linux で上が無いとき（Kaggle 以外）
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Italic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-BoldItalic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationMono-Italic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationMono-BoldItalic.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSansMono-Bold.ttf",
     "/usr/share/fonts/truetype/noto/NotoSansMono-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf"),
    ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
     "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    ("/usr/share/fonts/truetype/humor-sans/Humor-Sans.ttf",
     "/usr/share/fonts/truetype/humor-sans/Humor-Sans.ttf"),
    # Windows（手元で確認するとき）
    ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesi.ttf"),
    ("C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/timesbi.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/ariali.ttf"),
    ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arialbi.ttf"),
    ("C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiai.ttf"),
    ("C:/Windows/Fonts/cambria.ttc", "C:/Windows/Fonts/cambriai.ttf"),
    ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrii.ttf"),
    ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/consolai.ttf"),
    ("C:/Windows/Fonts/verdana.ttf", "C:/Windows/Fonts/verdanai.ttf"),
    ("C:/Windows/Fonts/tahoma.ttf", "C:/Windows/Fonts/tahoma.ttf"),
    ("C:/Windows/Fonts/comic.ttf", "C:/Windows/Fonts/comici.ttf"),
    ("C:/Windows/Fonts/pala.ttf", "C:/Windows/Fonts/palai.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuii.ttf"),
]

# 1 つの書体の組で作る内訳: (ブロック名, 枚数, photo_like, arith)。**枚数は data6 と同じ**に
# してある（round 5 と比べたいのは「劣化を足したかどうか」だけ。同時に割合も変えると、
# どちらが効いたのか言えなくなる）。
# ブロック名は**大文字小文字だけの違いにしない**（Windows で同じ名前になり、上書きされる）。
TRAIN_BLOCKS = [
    ("A", 900, True, False),     # 中学の式・写真寄り
    ("B", 700, False, False),    # 中学の式・綺麗（真っ白な印刷にも当てる）
    ("C", 700, True, True),      # 小学校の計算・写真寄り
    ("D", 500, False, True),     # 小学校の計算・綺麗
]
VAL_BLOCKS = [
    ("E", 90, True, False),
    ("F", 70, True, True),
]

PAIR_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def find_fonts(limit):
    out = []
    for rom, ital in FONT_CANDIDATES:
        if os.path.exists(rom):
            out.append((rom, ital if os.path.exists(ital) else rom))
        if len(out) >= limit:
            break
    return out


def find_exe(given):
    if given:
        return given
    for name in ("mathcam", "mathcam.exe"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            return p
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--exe", default="")
    ap.add_argument("--fonts", type=int, default=13, help="使う書体の組の数")
    ap.add_argument("--scale", type=float, default=1.0, help="枚数を掛ける（動作確認用）")
    ap.add_argument("--px-min", type=int, default=26)
    ap.add_argument("--px-max", type=int, default=76)
    ap.add_argument("--italic-pct", type=int, default=80)
    ap.add_argument("--minus2212-pct", type=int, default=80)
    # **数字の 1 を縦棒だけの字で描く割合。** 実写の教科書の 1 は旗も台も無い縦棒で、
    # 手元の書体はどれも旗つき。この字形が学習データに無いと、縦棒は l と読むしかない
    # （実測: `103 × 12 - 36` が `6*l - 36` になった）。ラベルは "1" のまま。
    ap.add_argument("--plain-one-pct", type=int, default=35)
    ap.add_argument("--seed-base", type=int, default=70000)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    fonts = find_fonts(a.fonts)
    if a.list or not a.out:
        for i, (rom, ital) in enumerate(fonts):
            print("%s: %s | %s" % (PAIR_LETTERS[i], rom, ital))
        print("組 %d 個" % len(fonts))
        if not a.out:
            print("（--out を渡すと作る）")
        return 0
    exe = find_exe(a.exe)
    if not exe or not os.path.exists(exe):
        print("mathcam の実行ファイルが無い（sh build/cc.sh pure/mathcam.cpp -o mathcam.exe）")
        return 1
    if not fonts:
        print("書体が 1 つも見つからない（FONT_CANDIDATES に足す）")
        return 1

    total = {"train": 0, "val": 0}
    for i, (rom, ital) in enumerate(fonts):
        for split, blocks in (("train", TRAIN_BLOCKS), ("val", VAL_BLOCKS)):
            for bi, (bl, cnt, photo, arith) in enumerate(blocks):
                n = max(1, int(round(cnt * a.scale))) if a.scale < 1.0 else cnt
                if n <= 0:
                    continue
                out_dir = os.path.join(a.out, split)
                prefix = "%s%s" % (PAIR_LETTERS[i], bl)
                seed = a.seed_base + i * 100 + bi * 10 + (0 if split == "train" else 5)
                cmd = [exe, "dataset", "--out", out_dir, "--n", str(n), "--seed", str(seed),
                       "--px-min", str(a.px_min), "--px-max", str(a.px_max),
                       "--font", rom, "--font-italic", ital, "--prefix", prefix,
                       "--italic-pct", str(a.italic_pct),
                       "--minus2212-pct", str(a.minus2212_pct),
                       "--plain-one-pct", str(a.plain_one_pct)]
                if photo:
                    cmd.append("--photo-like")
                if arith:
                    cmd.append("--arith")
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   encoding="utf-8", errors="replace")
                last = (p.stdout or "").strip().splitlines()[-1:]
                print("%s %-6s n=%-5d %s" % (split, prefix, n, last[0] if last else "(出力なし)"))
                if p.returncode != 0:
                    print("失敗した: %s" % " ".join(cmd))
                    return 1
                # exprs.txt は 1 ブロックごとに上書きされるので、名前を変えて残す
                src = os.path.join(out_dir, "exprs.txt")
                if os.path.exists(src):
                    shutil.move(src, os.path.join(out_dir, "exprs_%s.txt" % prefix))
                total[split] += n
    for split in ("train", "val"):
        d = os.path.join(a.out, split, "images")
        got = len(os.listdir(d)) if os.path.isdir(d) else 0
        print("%s: 指示 %d 枚 / 実際 %d 枚" % (split, total[split], got))
    print("書体 %d 組、out=%s" % (len(fonts), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
