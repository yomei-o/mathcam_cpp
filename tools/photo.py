"""写真 1 枚を端から端まで（Python 側）— pure/pipeline.hpp + photo の鏡。

  python tools/photo.py --img q.png --model models/sym_det.onnx --steps
  python tools/photo.py --img test_data/image1.jpeg --crop 1180,480,1540,570 --show-syms

C++ 側は自作の ONNX ランタイム、こちらは onnxruntime を使う（**推論の実装を合わせるのが
目的ではない**。前処理・後処理・レイアウト解析・解き方が同じであることを確かめるのが目的で、
そこが両言語で一致していれば、認識の結果を Python で検算できる）。

前処理で外せない点（C++ 側と同じ理由・同じ数式で書く）:

  * letterbox は**双線形**、余白は 114/255、画素の中心を合わせる（cv2.resize と同じ規約）。
    最近傍にすると学習時と別物になり、端から端までが 72.5% に落ちる（実測）。
  * 箱は **cxcywh（入力画素）**、スコアは**既に sigmoid 済み**（Ultralytics の素の export）。
  * NMS の後に**クラスを無視した重複除去**（同じ字に 5 と 3 が残って "53" と読む）。
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X              # noqa: E402
import solve as S             # noqa: E402
import parse_layout as PL     # noqa: E402
import arith as AR            # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# クラスの並びは pure/classes.hpp が唯一の正。ここは写しなので、**モデルの出力数と
# 突き合わせて確かめる**（ずれると症状は「たまに変な式になる」だけで原因に辿り着けない）
CLASSES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
           "+", "-", "=", "(", ")", "sqrt", "frac",
           "x", "y", "t", "a", "b", "c", "n",
           "s", "i", "o", "l", "e", "g", "p", "q", "r", "t2",
           "times", "div", "dot", "brace_l", "brace_r"]


def letterbox(img, imgsz):
    """(1,3,imgsz,imgsz) の float32 と (scale, padx, pady) を返す。"""
    import numpy as np
    h, w = img.shape[:2]
    sc = min(imgsz / w, imgsz / h)
    nw, nh = int(w * sc), int(h * sc)
    padx, pady = (imgsz - nw) // 2, (imgsz - nh) // 2
    out = np.full((imgsz, imgsz, 3), 114.0, dtype=np.float32)
    # 画素の中心を合わせた双線形（cv2.resize と同じ規約）
    ys = (np.arange(nh, dtype=np.float32) + 0.5) / sc - 0.5
    xs = (np.arange(nw, dtype=np.float32) + 0.5) / sc - 0.5
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    ty = (ys - y0)[:, None, None]
    tx = (xs - x0)[None, :, None]
    y0c = np.clip(y0, 0, h - 1)
    x0c = np.clip(x0, 0, w - 1)
    y1c = np.clip(y0 + 1, 0, h - 1)
    x1c = np.clip(x0 + 1, 0, w - 1)
    f = img.astype(np.float32)
    p00 = f[y0c[:, None], x0c[None, :]]
    p10 = f[y0c[:, None], x1c[None, :]]
    p01 = f[y1c[:, None], x0c[None, :]]
    p11 = f[y1c[:, None], x1c[None, :]]
    top = p00 + (p10 - p00) * tx
    bot = p01 + (p11 - p01) * tx
    out[pady:pady + nh, padx:padx + nw] = top + (bot - top) * ty
    x = (out / 255.0).transpose(2, 0, 1)[None]
    return x.astype("float32"), sc, padx, pady


def nms_agnostic(dets, iou_thr=0.5):
    """クラスを無視した重複除去（スコアの高い順に残す）。"""
    keep = []
    for d in sorted(dets, key=lambda t: -t[5]):
        dup = False
        for k in keep:
            ix0, iy0 = max(d[1], k[1]), max(d[2], k[2])
            ix1, iy1 = min(d[3], k[3]), min(d[4], k[4])
            iw, ih = ix1 - ix0, iy1 - iy0
            if iw <= 0 or ih <= 0:
                continue
            inter = iw * ih
            ua = (d[3] - d[1]) * (d[4] - d[2]) + (k[3] - k[1]) * (k[4] - k[2]) - inter
            if ua > 0 and inter / ua > iou_thr:
                dup = True
                break
        if not dup:
            keep.append(d)
    return keep


def detect_syms(sess, img, imgsz=640, conf=0.25, nms=0.45):
    """画像（HxWx3 uint8）-> pl.Sym の列。C++ の pipeln::detect_syms と同じ道。"""
    import numpy as np
    x, sc, padx, pady = letterbox(img, imgsz)
    raw = sess.run(None, {sess.get_inputs()[0].name: x})[0]      # (1, 4+nc, N)
    a = raw[0]
    nc = a.shape[0] - 4
    if nc > len(CLASSES):
        raise SystemExit("モデルは %d クラスだが CLASSES は %d 個しかない（classes.hpp と揃える）"
                         % (nc, len(CLASSES)))
    cx, cy, ww, hh = a[0], a[1], a[2], a[3]
    scores = a[4:4 + nc]
    cls = np.argmax(scores, axis=0)
    best = scores[cls, np.arange(scores.shape[1])]                # 既に sigmoid 済み
    sel = best >= conf
    x1 = cx - ww / 2
    y1 = cy - hh / 2
    x2 = cx + ww / 2
    y2 = cy + hh / 2
    dets = []
    for i in np.nonzero(sel)[0]:
        dets.append((int(cls[i]), float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i]),
                     float(best[i])))
    # クラスごとの NMS（Ultralytics と同じ）→ そのあとクラスを無視した重複除去
    per = {}
    for d in dets:
        per.setdefault(d[0], []).append(d)
    kept = []
    for c, ds in per.items():
        kept.extend(nms_agnostic(ds, nms))
    kept = nms_agnostic(kept, 0.5)
    syms = []
    for c, bx0, by0, bx1, by1, _s in kept:
        sx0 = int((bx0 - padx) / sc)
        sy0 = int((by0 - pady) / sc)
        sx1 = int((bx1 - padx) / sc)
        sy1 = int((by1 - pady) / sc)
        if sx1 <= sx0 or sy1 <= sy0:
            continue
        name = CLASSES[c] if 0 <= c < len(CLASSES) else "?"
        syms.append(PL.Sym(name, sx0, sy0, sx1, sy1, sy1))
    syms.sort(key=lambda s: s.x0)
    return syms


def load_image(path, crop=""):
    from PIL import Image
    import numpy as np
    im = Image.open(path)
    im = im.convert("RGB")
    if crop:
        x0, y0, x1, y1 = [int(v) for v in crop.split(",")]
        im = im.crop((x0, y0, x1, y1))
    return np.asarray(im)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--model", default="models/sym_det.onnx")
    ap.add_argument("--crop", default="", help="x0,y0,x1,y1（実写のページから 1 式だけ取る）")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--nms", type=float, default=0.45)
    ap.add_argument("--steps", action="store_true")
    ap.add_argument("--show-syms", dest="show_syms", action="store_true")
    a = ap.parse_args()

    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime が入っていません: pip install onnxruntime")
        return 2
    if not os.path.exists(a.model):
        print("モデルが無い: %s" % a.model)
        return 1

    img = load_image(a.img, a.crop)
    sess = ort.InferenceSession(a.model, providers=["CPUExecutionProvider"])
    syms = detect_syms(sess, img, a.imgsz, a.conf, a.nms)
    print("%d 記号を検出" % len(syms))
    if a.show_syms:
        for s in syms:
            print("  %-5s (%d,%d)-(%d,%d)" % (s.cls, s.x0, s.y0, s.x1, s.y1))

    ok, e, text, why = PL.parse(syms)
    if not ok:
        print("レイアウト解析に失敗: %s" % why)
        return 1
    print("読めた式: %s" % text)

    sol = S.solve(e)
    if not sol.ok:
        # 方程式でなければ計算問題として、小学校の順序で 1 手ずつ計算する
        dec_ok = any(s.cls == "dot" for s in syms)
        ok2, raw_e, _t, _w = PL.parse(syms, raw=True)
        ares = AR.eval_steps(raw_e, dec_ok) if ok2 else None
        if ares is not None and ares.ok:
            if a.steps:
                for i, st in enumerate(ares.steps, 1):
                    print("%d. [%s] %s" % (i, st.rule, st.note))
                    print("   %s" % st.after)
            print("答え: %s" % AR.to_text(ares.value, dec_ok))
            return 0
        v = X.expand(e)
        print("答え: %s" % X.to_infix(v))
        if X.is_num(v) and not v.num.is_int():
            dec = X.to_decimal(v.num)
            if dec:
                print("小数: %s" % dec)
        return 0
    if a.steps:
        for i, st in enumerate(sol.steps, 1):
            print("%d. [%s] %s" % (i, st.rule, st.note))
            print("   %s" % X.to_infix(st.after))
    for line in S.answer_lines(sol):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
