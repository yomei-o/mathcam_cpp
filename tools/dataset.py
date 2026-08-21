"""認識器の学習データを作る（Python 側）— `mathcam dataset` の鏡。

乱数の引き方まで C++ と同じにしてある（式 → px の順に引く）。だから**同じ種なら、どちらで
作っても同じ式・同じ px・同じ枠**になる。`tools/parity/dataset.py` がそれを突き合わせる。
絵の画素だけは一致しない（ラスタライザが違う。理由は tools/typeset.py の冒頭）。

  python tools/dataset.py --out data/train --n 2000 --seed 1
  python tools/dataset.py --out data/val   --n 200  --seed 2 --no-images
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X          # noqa: E402
import genexpr as G       # noqa: E402
import typeset as T       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# クラスの並びは固定（学習と推論で番号がずれないように）。C++ 側の kClasses と同じ順序。
CLASSES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
           "+", "-", "=", "(", ")", "sqrt", "frac",
           "x", "y", "t", "a", "b", "c", "n",
           "s", "i", "o", "l", "e", "g", "p", "q", "r", "t2"]


def build(out_dir, n, seed, px_min, px_max, font_path="", no_images=False,
          font_italic="", italic_pct=50, minus2212_pct=50, prefix=""):
    f = T.Font(font_path)
    fi = None
    if italic_pct > 0:
        try:
            fi = T.Font(font_italic, italic=True)
        except SystemExit:
            print("イタリックの書体が見つからないので立体だけで作る（--font-italic で渡す）")
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "labels"), exist_ok=True)
    with open(os.path.join(out_dir, "classes.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(CLASSES) + "\n")

    r = G.Rng(seed)
    made = skipped = 0
    ex_lines = []
    for _ in range(n):
        # 乱数を引く順番は C++ と 1 対 1（順序が違うと同じ種でも別のデータになる）
        src = G.one(r)
        px = px_min + r.below(px_max - px_min + 1)
        use_ital = r.below(100) < italic_pct
        use_2212 = r.below(100) < minus2212_pct
        e, err = X.parse(src)
        if err:
            skipped += 1
            continue
        st = T.Style(italic_vars=(use_ital and fi is not None),
                     minus_cp=(0x2212 if use_2212 else ord("-")))
        fi_use = fi if st.italic_vars else None
        stem = "%s%06d" % (prefix, made)
        if no_images:
            w, h, boxes, _ = T.layout_boxes(f, e, px, fi_use, st)
        else:
            img, boxes = T.render(f, e, px, fi_use, st)
            img.save(os.path.join(out_dir, "images", stem + ".png"))
            w, h = img.width, img.height
        with open(os.path.join(out_dir, "labels", stem + ".txt"), "w", encoding="utf-8") as fp:
            for cls, x0, y0, x1, y1 in boxes:
                if cls not in CLASSES:
                    continue                            # クラス表に無い記号は落とす
                cid = CLASSES.index(cls)
                fp.write("%d %.6f %.6f %.6f %.6f\n"
                         % (cid, (x0 + x1) / 2 / w, (y0 + y1) / 2 / h,
                            (x1 - x0) / w, (y1 - y0) / h))
        ex_lines.append("%s\t%d\t%s" % (stem, px, src))
        made += 1
    with open(os.path.join(out_dir, "exprs.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(ex_lines) + ("\n" if ex_lines else ""))
    return made, skipped, f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--px-min", dest="px_min", type=int, default=32)
    ap.add_argument("--px-max", dest="px_max", type=int, default=64)
    ap.add_argument("--font-italic", dest="font_italic", default="")
    ap.add_argument("--italic-pct", dest="italic_pct", type=int, default=50)
    ap.add_argument("--minus2212-pct", dest="minus2212_pct", type=int, default=50)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--font", default="")
    ap.add_argument("--no-images", dest="no_images", action="store_true",
                    help="枠だけ作る（パリティ確認や、絵が要らない検算のため）")
    a = ap.parse_args()
    made, skipped, f = build(a.out, a.n, a.seed, a.px_min, a.px_max, a.font, a.no_images,
                             a.font_italic, a.italic_pct, a.minus2212_pct, a.prefix)
    print("%s に %d 件（捨てた式 %d 件、px %d..%d、font upem %d）"
          % (a.out, made, skipped, a.px_min, a.px_max, f.upem))
    return 0


if __name__ == "__main__":
    sys.exit(main())
