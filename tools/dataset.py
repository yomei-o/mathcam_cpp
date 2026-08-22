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
# **pure/classes.hpp と同じ並び。** ここが食い違うと、絵にはあるのにラベルが無いデータが
# できて、学習は「その字は無視しろ」を覚える（実際に 24,200 枚作ってしまった）。
# tools/parity/dataset.py が並びの一致も見る。
CLASSES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
           "+", "-", "=", "(", ")", "sqrt", "frac",
           "x", "y", "t", "a", "b", "c", "n",
           "s", "i", "o", "l", "e", "g", "p", "q", "r", "t2",
           "times", "div", "dot", "brace_l", "brace_r"]


def degrade(img, grad, grad_dir, noise, nseed):
    """紙の明暗ムラと粒子を足す（実写にはどちらもある）。ラベルは変わらない。

    画素は C++ 側と一致させない（ラスタライザが違うので元から一致しない）。合わせるのは
    **枠**だけ（tools/parity/dataset.py がそれを見る）。
    """
    import genexpr as G
    px = img.load()
    w, h = img.width, img.height
    nr = G.Rng(nseed)
    for y in range(h):
        for x in range(w):
            if grad_dir == 0:
                t = x * grad // max(1, w)
            elif grad_dir == 1:
                t = (w - x) * grad // max(1, w)
            elif grad_dir == 2:
                t = y * grad // max(1, h)
            else:
                t = (h - y) * grad // max(1, h)
            n = (int(nr.below(noise * 2 + 1)) - noise) if noise else 0
            px[x, y] = max(0, min(255, px[x, y] - t + n))
    return img


def build(out_dir, n, seed, px_min, px_max, font_path="", no_images=False,
          font_italic="", italic_pct=50, minus2212_pct=50, one_pct=0, prefix="",
          photo_like=False, font_bits="",
          arith=False):
    f = T.Font(font_path)
    if font_bits:
        f.load_bits(font_bits)
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
    made = skipped = dropped = 0
    ex_lines = []
    for _ in range(n):
        # 乱数を引く順番は C++ と 1 対 1（順序が違うと同じ種でも別のデータになる）
        src = G.arith(r) if arith else G.one(r)
        px = px_min + r.below(px_max - px_min + 1)
        use_ital = r.below(100) < italic_pct
        use_2212 = r.below(100) < minus2212_pct
        # 数字の 1 を「縦棒だけ」の字で描く（C++ と同じ順で引く）
        plain_one = r.below(100) < one_pct
        # 紙と字の明るさ・ぼけ（C++ と同じ順序・同じ範囲で引く）
        paper = int(215 + r.below(41)) if photo_like else 255
        ink = int(20 + r.below(71)) if photo_like else 0
        blur = int(r.below(2)) if photo_like else 0
        # 写真に近づけるための劣化（**引く順番は C++ と同じ**）
        grad = int(r.below(26)) if photo_like else 0       # 端から端で 0..25 の明暗差
        grad_dir = int(r.below(4)) if photo_like else 0
        noise = int(r.below(9)) if photo_like else 0       # 粒子の振れ幅 0..8
        nseed = r.next() if photo_like else 0
        jpeg_q = int(55 + r.below(38)) if photo_like else 0
        as_jpeg = bool(photo_like and r.below(2) == 0)
        e, err = X.parse(src)
        if err:
            skipped += 1
            continue
        st = T.Style(italic_vars=(use_ital and fi is not None),
                     minus_cp=(0x2212 if use_2212 else ord("-")), plain_one=plain_one,
                     ink=ink, paper=paper, blur=blur)
        fi_use = fi if st.italic_vars else None
        stem = "%s%06d" % (prefix, made)
        if no_images:
            w, h, boxes, _ = (T.layout_boxes_arith(f, src, px, fi_use, st) if arith
                              else T.layout_boxes(f, e, px, fi_use, st))
        else:
            img, boxes = (T.render_arith(f, src, px, fi_use, st) if arith
                          else T.render(f, e, px, fi_use, st))
            if photo_like and (grad > 0 or noise > 0):
                img = degrade(img, grad, grad_dir, noise, nseed)
            # **半分は JPEG で書く**（実写は必ず JPEG のにじみが乗っている）
            name = stem + (".jpg" if as_jpeg else ".png")
            if as_jpeg:
                img.save(os.path.join(out_dir, "images", name), quality=jpeg_q)
            else:
                img.save(os.path.join(out_dir, "images", name))
            w, h = img.width, img.height
        with open(os.path.join(out_dir, "labels", stem + ".txt"), "w", encoding="utf-8") as fp:
            for cls, x0, y0, x1, y1 in boxes:
                if cls not in CLASSES:
                    dropped += 1                        # 黙って落とさず数える
                    continue
                cid = CLASSES.index(cls)
                fp.write("%d %.6f %.6f %.6f %.6f\n"
                         % (cid, (x0 + x1) / 2 / w, (y0 + y1) / 2 / h,
                            (x1 - x0) / w, (y1 - y0) / h))
        ex_lines.append("%s\t%d\t%s" % (stem, px, src))
        made += 1
    with open(os.path.join(out_dir, "exprs.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(ex_lines) + ("\n" if ex_lines else ""))
    if dropped:
        print("**クラス表に無い記号を %d 個落とした**（classes.hpp に足すか、描き方を直す）"
              % dropped)
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
    ap.add_argument("--font-bits", dest="font_bits", default="",
                    help="画像で持つ字のディレクトリ（mathcam fontdump の出力）")
    ap.add_argument("--plain-one-pct", dest="one_pct", type=int, default=0,
                    help="数字の 1 を縦棒だけの字で描く割合（実写の教科書の 1 はそれ）")
    ap.add_argument("--prefix", default="")
    ap.add_argument("--photo-like", dest="photo_like", action="store_true",
                    help="紙と字の明るさを振り、たまにぼかす（写真に寄せる）")
    ap.add_argument("--arith", action="store_true",
                    help="小学校の計算（× ÷ 小数点 帯分数 中括弧）を作る")
    ap.add_argument("--font", default="")
    ap.add_argument("--no-images", dest="no_images", action="store_true",
                    help="枠だけ作る（パリティ確認や、絵が要らない検算のため）")
    a = ap.parse_args()
    made, skipped, f = build(a.out, a.n, a.seed, a.px_min, a.px_max, a.font, a.no_images,
                             a.font_italic, a.italic_pct, a.minus2212_pct, a.one_pct, a.prefix,
                             a.photo_like, a.font_bits, a.arith)
    print("%s に %d 件（捨てた式 %d 件、px %d..%d、font upem %d）"
          % (a.out, made, skipped, a.px_min, a.px_max, f.upem))
    return 0


if __name__ == "__main__":
    sys.exit(main())
