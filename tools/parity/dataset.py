"""データセットのパリティ — 同じ種なら、C++ と Python が同じ学習データを作るか。

  python tools/parity/dataset.py            # 40 件
  python tools/parity/dataset.py --n 200

比べるもの:
  * `exprs.txt`（式と px の列）。乱数は splitmix64 で、引く順序（式 → px）も揃えてある
  * `labels/*.txt`（YOLO 形式の全行）。ここが学習の正解そのもの
  * `classes.txt`（クラスの並び。ずれると学習と推論で番号が食い違う）

絵の画素は比べない（C++ は stb_truetype、Python は FreeType。理由は tools/typeset.py の冒頭）。
だから既定では `--no-images` で作る。絵まで作りたいときは `--images` を付ける。

これが通ることの意味: **学習データの生成を Python 側でやっても C++ 側でやっても同じ**。
片方しか動かない環境（Kaggle には C++ を持ち込めるが、手元では Python が楽）でも同じ結果になる。
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dataset as D       # noqa: E402
import typeset as T       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read(path):
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip() for ln in f]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--px-min", dest="px_min", type=int, default=32)
    ap.add_argument("--px-max", dest="px_max", type=int, default=64)
    ap.add_argument("--font", default="")
    ap.add_argument("--images", action="store_true", help="絵も作る（比較はしない）")
    ap.add_argument("--exe", default="")
    ap.add_argument("--keep", action="store_true")
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
        font = T.Font(a.font)
    except SystemExit as e:
        print("[SKIP] %s" % e)
        return 0
    font_path = a.font or font.path

    cdir = os.path.join(ROOT, "scratch", "_parity_ds_cpp")
    pdir = os.path.join(ROOT, "scratch", "_parity_ds_py")
    for d in (cdir, pdir):
        shutil.rmtree(d, ignore_errors=True)

    cmd = [exe, "dataset", "--out", cdir, "--n", str(a.n), "--seed", str(a.seed),
           "--px-min", str(a.px_min), "--px-max", str(a.px_max), "--font", font_path]
    if not a.images:
        cmd.append("--no-images")
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("[FAIL] C++ 側が失敗: %s" % p.stdout.strip())
        return 1
    D.build(pdir, a.n, a.seed, a.px_min, a.px_max, font_path, no_images=not a.images)

    bad = 0
    for name in ("exprs.txt", "classes.txt"):
        c, q = read(os.path.join(cdir, name)), read(os.path.join(pdir, name))
        if c != q:
            print("[FAIL] %s が違う" % name)
            for i in range(max(len(c), len(q))):
                cl = c[i] if i < len(c) else "-"
                ql = q[i] if i < len(q) else "-"
                if cl != ql:
                    print("   cpp: %s" % cl)
                    print("   py : %s" % ql)
                    break
            bad += 1

    clabels = sorted(os.listdir(os.path.join(cdir, "labels")))
    plabels = sorted(os.listdir(os.path.join(pdir, "labels")))
    if clabels != plabels:
        print("[FAIL] ラベルファイルの数が違う（cpp %d / py %d）" % (len(clabels), len(plabels)))
        bad += 1
    else:
        diff = 0
        for name in clabels:
            c = read(os.path.join(cdir, "labels", name))
            q = read(os.path.join(pdir, "labels", name))
            if c != q:
                if diff < 2:
                    print("[FAIL] labels/%s" % name)
                    for i in range(max(len(c), len(q))):
                        cl = c[i] if i < len(c) else "-"
                        ql = q[i] if i < len(q) else "-"
                        if cl != ql:
                            print("   cpp: %s" % cl)
                            print("   py : %s" % ql)
                            break
                diff += 1
        if diff:
            print("[FAIL] ラベルが %d / %d 件で違う" % (diff, len(clabels)))
            bad += 1

    if not a.keep:
        for d in (cdir, pdir):
            shutil.rmtree(d, ignore_errors=True)
    print("%d 件のデータセットを突き合わせ（seed %d、px %d..%d、font %s）: %s"
          % (a.n, a.seed, a.px_min, a.px_max, os.path.basename(font_path),
             "一致" if bad == 0 else "%d 項目が不一致" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
