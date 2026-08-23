"""実写の写真で「読めた式」が合っているかを測る。

合成データの数字（`mathcam e2e`）だけを見ていると、実物で何が起きているか分からない。
ここは**教科書を撮った写真**に対して、切り出し 1 つずつを CLI に通し、読めた式を
正解表（tests/real_photos.txt）と**CAS で比べる**（書き方の違いは吸収し、意味が同じかだけ見る）。

  python tools/real_eval.py --dir test_data --model models/sym_det_v5.onnx
  python tools/real_eval.py --dir test_data --model models/sym_det_tb.onnx --show

写真そのものはリポジトリに入れていない（教科書は著作物）。正解表と、この測り方だけ置く。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_key(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 2)
            if len(parts) != 3:
                print("[WARN] 読めない行: %s" % line)
                continue
            rows.append((parts[0], parts[1], parts[2]))
    return rows


FRAC_CONF = [0.08]                                   # 分数線だけのしきい値（--conf-frac）


def run_cli(exe, img, crop, model, conf):
    p = subprocess.run([exe, "photo", "--img", img, "--crop", crop, "--model", model,
                        "--conf", str(conf), "--conf-frac", str(FRAC_CONF[0]), "--show-syms"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       encoding="utf-8", errors="replace")
    read, syms = "", []
    for line in p.stdout.splitlines():
        if line.startswith("読めた式: "):
            read = line[len("読めた式: "):].strip()
        elif line.startswith("  ") and len(line.split()) == 2:
            syms.append(line.split()[0])
    return read, syms, p.stdout


def same(a, b):
    """式として同じか（書き方の違いは CAS で吸収する）。"""
    ea, err_a = X.parse(a)
    eb, err_b = X.parse(b)
    if err_a or err_b:
        return False
    if ea.k == X.REL and eb.k == X.REL:
        # A = B と A - B = 0 を同じと見る（読み方の違いで移項されることがある）
        if ea.name != eb.name:
            return False
        da = X.expand(X.sub(ea.kids[0], ea.kids[1]))
        db = X.expand(X.sub(eb.kids[0], eb.kids[1]))
        return X.equal(da, db)
    return X.equal(X.expand(ea), X.expand(eb))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="test_data")
    ap.add_argument("--key", default=os.path.join(ROOT, "tests", "real_photos.txt"))
    ap.add_argument("--model", default="models/sym_det_v5.onnx")
    ap.add_argument("--conf", type=float, default=0.20)
    ap.add_argument("--conf-frac", dest="conf_frac", type=float, default=0.08)
    ap.add_argument("--exe", default="")
    ap.add_argument("--show", action="store_true", help="外したものの記号列も出す")
    a = ap.parse_args()
    FRAC_CONF[0] = a.conf_frac

    exe = a.exe
    if not exe:
        for name in ("mathcam.exe", "mathcam"):
            if os.path.exists(os.path.join(ROOT, name)):
                exe = os.path.join(ROOT, name)
                break
    if not exe or not os.path.exists(exe):
        print("[SKIP] mathcam の実行ファイルが無い（sh build/cc.sh pure/mathcam.cpp -o mathcam.exe）")
        return 0
    if not os.path.isdir(a.dir):
        print("[SKIP] %s が無い（写真はリポジトリに入れていない）" % a.dir)
        return 0

    rows = read_key(a.key)
    ok = 0
    goods = []
    for img, crop, want in rows:
        path = os.path.join(a.dir, img)
        if not os.path.exists(path):
            print("[SKIP] %s が無い" % path)
            goods.append(False)
            continue
        read, syms, _raw = run_cli(exe, path, crop, a.model, a.conf)
        good = bool(read) and same(read, want)
        goods.append(good)
        ok += 1 if good else 0
        mark = "ok  " if good else "NG  "
        print("%s%-14s %-22s 期待 %-22s 読み %s" % (mark, img, crop, want, read or "(読めない)"))
        if a.show and not good:
            print("      記号列: %s" % " ".join(syms))
    # **画像ごとの内訳も出す**（分母が違うモデル同士を比べるとき、全体だけ見ると誤読する）
    per = {}
    for img, _c, _w in rows:
        per.setdefault(img, [0, 0])
    for (img, crop, want), good in zip(rows, goods):
        per[img][1] += 1
        per[img][0] += 1 if good else 0
    print("内訳: " + " / ".join("%s %d/%d" % (k.replace(".jpeg", ""), v[0], v[1])
                                for k, v in sorted(per.items())))
    print("実写: %d / %d 正解（%.1f%%）、model=%s"
          % (ok, len(rows), 100.0 * ok / len(rows) if rows else 0.0, a.model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
