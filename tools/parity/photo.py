"""写真の道のパリティ — 同じ画像を入れたら C++ と Python が同じ記号・同じ式を出すか。

  python tools/parity/photo.py --n 20 --model models/sym_det_v4.onnx

C++ は自作の ONNX ランタイム、Python は onnxruntime。**推論の実装は違う**ので、
数値が完全一致する保証はない。ここで縛るのは
「前処理・デコード・重複除去・レイアウト解析・解き方が同じで、**読める式が同じ**」であること。
枠は 1px までのずれを許す（それ以上ずれたら前処理が違っている）。

実測（times.ttf、20 枚）: 記号の枠まで完全一致した。つまり letterbox の実装も一致している。
"""
import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X          # noqa: E402
import genexpr as G       # noqa: E402
import typeset as T       # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_out(text):
    """CLI の出力から (記号列, 読めた式) を取る（両言語で同じ書式にしてある）。"""
    syms, read = [], ""
    for line in text.splitlines():
        if line.startswith("読めた式: "):
            read = line[len("読めた式: "):].strip()
        elif line.startswith("  ") and "(" in line and ")-(" in line:
            p = line.split()
            box = p[1].strip("()").replace(")-(", ",")
            syms.append((p[0], tuple(int(v) for v in box.split(","))))
    return syms, read


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--model", default="models/sym_det_v4.onnx")
    ap.add_argument("--px", type=int, default=48)
    ap.add_argument("--font", default="")
    ap.add_argument("--exe", default="")
    ap.add_argument("--tol", type=int, default=1, help="枠のずれの許容（px）")
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
    if not os.path.exists(a.model):
        print("[SKIP] %s が無い" % a.model)
        return 0
    try:
        import onnxruntime      # noqa: F401
    except ImportError:
        print("[SKIP] onnxruntime が入っていない（pip install onnxruntime）")
        return 0

    f = T.Font(a.font)
    rng = G.Rng(a.seed)
    tmp = os.path.join(tempfile.gettempdir(), "mathcam_photo_parity.png")
    bad = box_bad = 0
    n = 0
    for _ in range(a.n):
        src = G.one(rng)
        e, err = X.parse(src)
        if err:
            continue
        img, _boxes = T.render(f, e, a.px)
        img.save(tmp)
        n += 1
        c = subprocess.run([exe, "photo", "--img", tmp, "--model", a.model, "--show-syms"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           encoding="utf-8", errors="replace").stdout
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "photo.py"),
                            "--img", tmp, "--model", a.model, "--show-syms"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           encoding="utf-8", errors="replace").stdout
        cs, cr = parse_out(c)
        ps, pr = parse_out(p)
        if cr != pr or [s[0] for s in cs] != [s[0] for s in ps]:
            print("[DIFF] %s\n   cpp: %s\n   py : %s" % (src, cr or c.strip(), pr or p.strip()))
            bad += 1
            continue
        off = max((max(abs(u - v) for u, v in zip(x[1], y[1])) for x, y in zip(cs, ps)),
                  default=0)
        if off > a.tol:
            print("[BOX ] %s 枠のずれ %dpx" % (src, off))
            box_bad += 1
    print("%d 枚を突き合わせ（model=%s）、式の不一致 %d 件、枠のずれ %d 件"
          % (n, os.path.basename(a.model), bad, box_bad))
    return 1 if (bad or box_bad) else 0


if __name__ == "__main__":
    sys.exit(main())
