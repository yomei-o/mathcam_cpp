"""レイアウト解析のパリティ — 同じ枠の列を入れたら C++ と Python が同じ式を返すか。

  python tools/parity/layout.py --n 300
  python tools/parity/layout.py --n 300 --seed 7 --verbose

やり方: 乱数の式を組版して**枠だけ**を出し（`mathcam dataset --no-images` と同じ道）、
その枠を両方の解析器に食わせて、返る式（中置の文字列）を突き合わせる。
さらに**元の式に戻るか**も見る（組版 -> 解析の往復。C++ の `mathcam selftest` と同じ検査を
Python 側にも掛ける）。ここが合っていないと、認識の後半を Python で検算できない。
"""
import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X            # noqa: E402
import genexpr as G         # noqa: E402
import typeset as T         # noqa: E402
import parse_layout as PL    # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def cpp_parse(exe, path):
    p = subprocess.run([exe, "parse", "--labels", path], stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    return p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--px", type=int, default=48)
    ap.add_argument("--font", default="")
    ap.add_argument("--font-italic", dest="font_italic", default="")
    ap.add_argument("--italic", action="store_true")
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

    f = T.Font(a.font)
    fi = None
    st = T.Style()
    if a.italic:
        fi = T.Font(a.font_italic, italic=True)
        st = T.Style(italic_vars=True, minus_cp=0x2212)

    rng = G.Rng(a.seed)
    diff = round_bad = 0
    checked = 0
    tmp = os.path.join(tempfile.gettempdir(), "mathcam_layout_parity.txt")
    for _ in range(a.n):
        src = G.one(rng)
        e, err = X.parse(src)
        if err:
            continue
        _w, _h, boxes, _draw = T.layout_boxes(f, e, a.px, fi, st)
        with open(tmp, "w", encoding="utf-8") as fp:
            fp.write("# %s\n" % src)
            for cls, x0, y0, x1, y1 in boxes:
                fp.write("%s %d %d %d %d\n" % (cls, x0, y0, x1, y1))
        checked += 1

        syms = PL.read_labels(tmp)
        ok, got, text, why = PL.parse(syms)
        c_text = cpp_parse(exe, tmp)
        py_text = text if ok else ("parse failed: %s" % why)
        if py_text != c_text:
            print("[DIFF] %s" % src)
            print("   cpp: %s" % c_text)
            print("   py : %s" % py_text)
            diff += 1
            continue
        # 往復: 組版して解析したら元の式に戻るか（両言語で同じ判定になるはず）
        if not ok or not X.equal(got, e):
            print("[ROUND] %s -> %s" % (src, py_text))
            round_bad += 1
        elif a.verbose:
            print("  ok  %-30s -> %s" % (src, text))

    print("%d 件を突き合わせ（px=%d, font=%s%s）、不一致 %d 件、往復で戻らない %d 件"
          % (checked, a.px, os.path.basename(f.path), "+italic" if a.italic else "",
             diff, round_bad))
    return 1 if (diff or round_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
