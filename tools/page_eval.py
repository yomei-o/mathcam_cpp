"""**囲まずに**写真を渡して何問読めるかを測る（デモの「1問ずつ読む」ボタンの物差し）。

`tools/real_eval.py` は 1 問ずつ切り出して測る（切り出しは人がやる前提）。こちらは
`photo --auto-cells` に**画像をまるごと**渡し、出てきた式のどれかが正解表の式と
一致するかを数える。人が囲まなくても読めるか、という別の問いを測る。

  python tools/page_eval.py --dir test_data
  python tools/page_eval.py --dir test_data --model models/cand_epoch3.onnx
  python tools/page_eval.py --dir test_data --only image1.jpeg --show

正解表は tests/real_photos.txt をそのまま使う（切り出し座標は無視して、式だけ使う）。
写真そのものはリポジトリに入れていない（教科書は著作物）。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X            # noqa: E402
from real_eval import read_key, same   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_cells(exe, img, model, conf, crop="", gap=90):
    cmd = [exe, "photo", "--img", img, "--model", model, "--conf", str(conf), "--auto-cells",
           "--cell-gap", str(gap)]
    if crop:
        cmd += ["--crop", crop]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    out = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if line.startswith("読めた式: "):
            out.append(line[len("読めた式: "):].strip())
    return out, p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="test_data")
    ap.add_argument("--key", default=os.path.join(ROOT, "tests", "real_photos.txt"))
    ap.add_argument("--model", default="models/sym_det_v4.onnx")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--exe", default="")
    ap.add_argument("--only", default="", help="1 枚だけ測る")
    ap.add_argument("--crop", default="", help="その 1 枚の中の範囲（x0,y0,x1,y1）")
    ap.add_argument("--cell-gap", type=int, default=35, help="塊を切る隙間の下限（帯の高さの %）")
    ap.add_argument("--show", action="store_true", help="読めた式を全部出す")
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
    if not os.path.isdir(a.dir):
        print("[SKIP] %s が無い（写真はリポジトリに入れていない）" % a.dir)
        return 0

    rows = read_key(a.key)
    want = {}
    for img, _crop, w in rows:
        if a.only and img != a.only:
            continue
        want.setdefault(img, []).append(w)

    total_ok = total = 0
    for img, wants in sorted(want.items()):
        path = os.path.join(a.dir, img)
        if not os.path.exists(path):
            print("[SKIP] %s が無い" % path)
            continue
        got, raw = run_cells(exe, path, a.model, a.conf, a.crop, a.cell_gap)
        hit = []
        for w in wants:
            found = any(same(g, w) for g in got)
            hit.append(found)
            print("%s %-12s %s" % ("ok  " if found else "NG  ", img, w))
        if a.show:
            print("  読めた式（%d 個）:" % len(got))
            for g in got:
                print("    %s" % g)
        total_ok += sum(1 for h in hit if h)
        total += len(hit)
        print("  %s: %d / %d（塊 %d 個から）" % (img, sum(1 for h in hit if h), len(hit), len(got)))
    print("ページ渡し: %d / %d 正解（%.1f%%）、model=%s"
          % (total_ok, total, 100.0 * total_ok / total if total else 0.0, a.model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
