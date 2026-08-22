"""正解表の切り出しが**字を切っていないか**を調べる（物差しそのものの検査）。

切り出しの縁にインクが乗っていれば、その字は途中で切れている可能性が高い。実測: `(2x - y)^2` の
切り出しは上付きの `2` を切っていて、**原理的に読めない行**を「モデルが外した」と数えていた。
モデルの良し悪しを決める物差しなので、ここが間違っていると全部の比較が狂う。

  python tools/check_key.py --dir test_data
  python tools/check_key.py --dir test_data --save scratch/keycrops   # 切り出しを画像で残す
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from real_eval import read_key      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="test_data")
    ap.add_argument("--key", default=os.path.join(ROOT, "tests", "real_photos.txt"))
    ap.add_argument("--band", type=int, default=4, help="縁とみなす幅（px）")
    ap.add_argument("--save", default="")
    a = ap.parse_args()

    import numpy as np
    from PIL import Image

    if not os.path.isdir(a.dir):
        print("[SKIP] %s が無い（写真はリポジトリに入れていない）" % a.dir)
        return 0
    if a.save:
        os.makedirs(a.save, exist_ok=True)

    bad = 0
    for i, (img, crop, want) in enumerate(read_key(a.key)):
        path = os.path.join(a.dir, img)
        if not os.path.exists(path):
            continue
        x0, y0, x1, y1 = [int(v) for v in crop.split(",")]
        im = Image.open(path).convert("RGB")
        x1 = min(x1, im.width)
        y1 = min(y1, im.height)
        c = np.asarray(im.crop((x0, y0, x1, y1))).astype(np.int32)
        g = (c[:, :, 0] * 30 + c[:, :, 1] * 59 + c[:, :, 2] * 11) // 100
        paper = int(np.median(g))
        ink = g < paper - 40                       # その切り出しの紙より十分暗い画素
        b = a.band
        edges = {"上": ink[:b, :], "下": ink[-b:, :], "左": ink[:, :b], "右": ink[:, -b:]}
        hit = []
        for name, m in edges.items():
            # 縁に**まとまった**インクがあるか（1 列あたり 2 画素以上が 3 本以上続く感じ）
            n = int(m.sum())
            if n >= max(8, m.shape[0] * m.shape[1] // 60):
                hit.append("%s(%d)" % (name, n))
        if hit:
            bad += 1
            print("縁に字がある  %-12s %-22s %s   %s" % (img, crop, ",".join(hit), want))
        if a.save:
            im.crop((x0, y0, x1, y1)).save(os.path.join(a.save, "%02d_%s.png" % (i, img[:-5])))
    print("縁に字がある行: %d 件（切り出しを見直す候補）" % bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
