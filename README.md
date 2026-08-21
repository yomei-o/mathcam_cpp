# mathcam_cpp — 数式の写真から、答えと解き方を出す（C++ と Python の両方で）

Photomath のようなものを、**認識も計算も自前**で作る。姉妹リポ
（[crowd_cpp](https://github.com/yomei-o/crowd_cpp) /
[yolo_lpr_cpp](https://github.com/yomei-o/yolo_lpr_cpp)）と同じ設計方針:
自作エンジン＋自作 ONNX ランタイム、**学習も推論も評価も両言語**、パリティはテストで縛る、
成果物は全段 ONNX、最後は WASM でブラウザに載せる。

進捗・実測値・落とし穴・次の一手は **[RESUME.md](RESUME.md)**。

## 何を作るのか（3 つの独立した仕事）

| 部品 | 中身 | 状態 |
|---|---|---|
| ① 認識 | 写真 → 記号の検出 → **2 次元レイアウト解析** → 式木 | **合成データで完了**（検出 mAP50 0.9939、レイアウト解析 100%、端から端まで 98.3%）。実写は未検証 |
| ② 計算 | 式木を書き換えて答えを出す（厳密有理数の CAS） | **一次・二次方程式まで完了**（両言語 + パリティ） |
| ③ 手順 | 「名前のついた書き換え」を並べて見せる | **完了**（移項・分母を払う・因数分解・解の公式…） |

**①より②を先に作る。** 理由は、②が決める式木が認識側の出力契約になるからで、
先に認識を作ると「何に向けて認識するのか」が決まらない。②はデータもモデルも要らないので
初日からテストできる。

## 方針（最初のゴール）

* **印刷数式から**始める（教科書・プリント・画面）。学習データは**自作の数式組版で無限に合成**でき、
  記号ごとの正解枠が副産物として得られる。手書き（CROHME）は後段。
* 数学の範囲は **四則・分数・累乗根・一次方程式・二次方程式**まで。
  **微分積分も最終目標**なので、CAS は最初からそれ用に作る（関数を式木に持つ、
  簡約を書き換え規則の表にする、正規形を厳密有理数で持つ）。
* **手順表示は最初から。** 後付けは作り直しになる。

## いま動くもの

```sh
sh build/cc.sh pure/mathcam.cpp -o mathcam.exe     # MSVC（vcvars 不要）
sh build/gcc.sh pure/mathcam.cpp -o mathcam.exe    # mingw / g++

./mathcam.exe eval --expr "2/3 + 1/6"              # -> 5/6      （厳密有理数）
./mathcam.exe eval --expr "2(x+1) - 3x"            # -> -x + 2   （展開して同類項）
./mathcam.exe eval --expr "(x+2)(x-3)"             # -> x^2 - x - 6
./mathcam.exe eval --expr "(x+2)(x-3)" --no-expand # -> (x - 3)*(x + 2)
./mathcam.exe eval --expr "sqrt(9/4)"              # -> 3/2      （完全冪は畳む）
./mathcam.exe eval --expr "8^(1/3)"                # -> 2
./mathcam.exe eval --expr "x^2 - 5x + 6 = 0"       # -> x^2 - 5*x + 6 = 0（次数の降順で表示）
./mathcam.exe eval --expr "1/2 x + 1/3 x" --latex  # -> 5/6*x    / latex: \frac{5}{6} x
./mathcam.exe eval --expr "sqrt(8)"                # -> 2*sqrt(2)（根号の中の平方因数を外に出す）

./mathcam.exe solve --expr "x^2 - 5x + 6 = 0" --steps
#   1. [因数分解] 左辺を積の形にする
#      (x - 3)*(x - 2) = 0
#   2. [積が 0] 積が 0 になるのは、どちらかの因数が 0 のとき: x - 3 = 0 または x - 2 = 0
#   x = 3
#   x = 2

./mathcam.exe solve --expr "x/2 + x/3 = 5" --steps  # 移項→分母を払う→移項→両辺を割る→x = 6
./mathcam.exe solve --expr "3x^2 + 5x - 2 = 0" --steps  # (3*x - 1)*(x + 2) = 0
./mathcam.exe solve --expr "x^2 + x = 1" --steps    # 解の公式→x = 1/2*(sqrt(5) - 1)（厳密なまま）
```

Python 側も同じことができる（`python tools/expr.py --expr ...` /
`python tools/solve.py --expr ... --steps`）。**両実装の一致はテストで縛る**:

```sh
python tools/parity/expr.py  --n 900   # 正規形・LaTeX・往復不変（印字したものを読み直せるか）
python tools/parity/solve.py --n 200   # 手順の全行（規則名・説明・各段の式）と答え
```

## 写真から解く（① 認識）

```sh
# 組版器でお手本の画像を作って、それを写真として読ませる
./mathcam.exe render --expr "x^2 - 5x + 6 = 0" --out q.png --px 56
./mathcam.exe photo --img q.png --steps --show-syms
#   9 記号を検出
#     x (12,40)-(41,66) / 2 (42,13)-(59,40) / - ... （--show-syms のとき枠も出す）
#   読めた式: x^2 - 5*x + 6 = 0
#   1. [因数分解] 左辺を積の形にする   (x - 3)*(x - 2) = 0
#   2. [積が 0] ...                    x = 3 / x = 2

./mathcam.exe selftest --n 200      # 組版 -> 解析 の往復（レイアウト解析の正解率）
./mathcam.exe e2e --n 120           # 検出 -> 解析 -> solve（端から端まで）
```

検出器の学習は Python（Ultralytics）:

```sh
./mathcam.exe dataset --out data/train --n 20000   # 合成データ。外部データセットは要らない
python tools/train_det.py --data data --epochs 40 --imgsz 640   # GPU
python tools/train_det.py --export-only --weights runs/.../best.pt  # NMS なしで ONNX
```

**写真の道は 1 本だけ**（`pure/pipeline.hpp`）。CLI と WASM が同じ関数を通る。
前処理を 2 か所に書くと、片方だけ直して「ブラウザだと精度が出ない」という状態になる。

## ブラウザで動かす（WASM デモ）

**公開版: https://yomei-o.github.io/mathcam_cpp/wasm/**

```sh
sh build/emcc.sh wasm/mathcam_wasm.cpp -o wasm/mathcam.js
python -m http.server 8000          # -> http://127.0.0.1:8000/wasm/
node wasm/test_node.js              # ブラウザ抜きの検査（サンプルを解いて答え合わせ）
```

サンプル画像 5 枚（**このリポジトリの組版器で描いたもの**なので画像のライセンス問題がない）、
ファイル選択、カメラ 1 枚撮り、検出枠の重ね描き、手順表示。1 枚 1.3〜2.7 秒（自作ランタイム）。
推論は Worker で回す（UI スレッドでやると固まって「壊れている」ように見える）。

## 設計で決めたこと（理由つき）

* **数は厳密有理数**（int64 の分子・分母、既約）。`1/3` を `0.333` にしたら手順表示が嘘になる。
  `double` は最後の表示だけ。
* **Add と Mul は可変長**で、正規形は**全順序でソート**する。そうすると「同じ式か」が
  構造の一致で判定でき、`x + 1` と `1 + x` が同一になる。
* **式木は不変**（`shared_ptr<const Node>`）。手順表示は各段の木を保持するので、
  破壊的更新だと過去の段が壊れる。
* **展開（分配法則）は正規形に入れない。** `(x+1)^100` で爆発するし、「くくった形」を保ちたい
  場面（因数分解の手順）で邪魔になる。必要なところで `expand` を明示的に呼ぶ。
* **正規化は手順に出さない。** 手順に出すのは solve が選んだ規則（「両辺から 3 を引く」
  「解の公式」）だけ。正規化の 1 手 1 手を見せると人間には読めない。
* **印字は読み直せる形にする。** `2^1/2` と書くと自分のパーサで `(2^1)/2` に読めてしまうので、
  分数指数は括弧か `sqrt()` で出す（`parse(to_infix(e)) == e` を不変条件として縛る）。
* **表示順序と正規順序は別物。** 内部は決定的な全順序、表示は次数の降順（人は
  `x^2 - 5x + 6` の順で書く）。

## ライセンス

自前コードは BSD-3-Clause。`pure/` のエンジンは姉妹リポから移植（同じ作者・BSD-3-Clause）。
