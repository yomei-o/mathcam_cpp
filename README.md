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
| ① 認識 | 写真 → 記号の検出 → **2 次元レイアウト解析** → 式木 | 合成データは通る（検出 mAP50 0.99、レイアウト解析 100%、**数式書体での端から端まで 92.5%（中学）/ 95.0%（小学校）**）。**実写の教科書は 32 問中 31 問**（始まりは 0 / 12。下の「実写はなぜ落ちたか」）。囲まずにページを渡す道は 19 / 32 |
| ② 計算 | 式木を書き換えて答えを出す（厳密有理数の CAS） | **高校の全範囲に手が届く**（方程式・不等式・因数分解・三角関数・指数対数・数列と Σ・微分積分・極限・面積・複素数解・絶対値・場合の数。両言語 + パリティ 11 スイート） |
| ③ 手順 | 「名前のついた書き換え」を並べて見せる | **完了**（移項・分母を払う・因数分解・解の公式・加減法・代入法・共通範囲・積の微分・合成関数・Σ の公式…） |

**①より②を先に作る。** 理由は、②が決める式木が認識側の出力契約になるからで、
先に認識を作ると「何に向けて認識するのか」が決まらない。②はデータもモデルも要らないので
初日からテストできる。

## 方針（最初のゴール）

* **印刷数式から**始める（教科書・プリント・画面）。学習データは**自作の数式組版で無限に合成**でき、
  記号ごとの正解枠が副産物として得られる。手書き（CROHME）は後段。
* 数学の範囲は **四則・分数・累乗根・一次方程式・二次方程式・一次不等式・連立方程式・連立不等式**
  （中学レベル）から始めて、いまは**高校の教科書に出る形**まで来た（下の一覧）。
  最初からそのつもりで CAS を作ってある（関数を式木に持つ、
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
python tools/parity/expr.py   --n 900  # 正規形・LaTeX・往復不変（印字したものを読み直せるか）
python tools/parity/solve.py  --n 200  # 手順の全行（規則名・説明・各段の式）と答え
python tools/parity/calc.py   --n 200  # 微分・積分（手順つき）
python tools/parity/seq.py    --n 200  # 数列と Σ（手順つき）
python tools/parity/factor.py --n 200  # 因数分解（答えが元の式と等しいかも見る）
python tools/parity/curve.py  --n 200  # 接線・極値・平方完成
python tools/parity/limit.py  --n 200  # 極限
python tools/parity/area.py   --n 150  # 面積
python tools/parity/trig.py   --n 200  # 三角関数の変形（加法定理・2 倍角・合成）
python tools/parity/recur.py  --n 200  # 漸化式（一般項を必ず検算する）
python tools/parity/circle.py --n 200  # 円の方程式（中心と半径）
python tools/parity/layout.py --n 300  # 枠 -> 式（レイアウト解析）と、組版 -> 解析の往復
python tools/parity/photo.py  --n 20   # 写真 1 枚の道（自作ランタイム vs onnxruntime）
```

不等式と連立も同じ 1 本で解ける（`,` か `;` で区切る）:

```sh
./mathcam.exe solve --expr "3x - 5 > 1" --steps            # x > 2
./mathcam.exe solve --expr "-2x + 1 >= 7" --steps          # 負の数で割るので向きが変わる
./mathcam.exe solve --expr "x + y = 5, 2x - y = 1" --steps  # 加減法 -> 代入
./mathcam.exe solve --expr "y = 2x - 1, 3x + y = 9" --steps # 代入法
./mathcam.exe solve --expr "2x > 4, x - 1 <= 4" --steps     # 共通範囲 2 < x <= 5
./mathcam.exe solve --expr "x^2 - 5x + 6 > 0" --steps       # x < 2 または x > 3
./mathcam.exe solve --expr "x^2 - 9 >= 0, x^2 - 25 <= 0"    # -5 <= x <= -3 または 3 <= x <= 5
```

微分・積分（`pure/calc.hpp`）と、数列・Σ（`pure/seq.hpp`）も同じ作法（手順つき・両言語一致）:

```sh
./mathcam.exe diff  --expr "x^3 + 2x" --steps               # 3x^2 + 2
./mathcam.exe diff  --expr "x sin(x)" --steps               # 積の微分
./mathcam.exe integ --expr "(2x + 1)^3" --steps             # (2x + 1)^4/8 + C（展開しない）
./mathcam.exe integ --expr "3x^2 + 1" --from 0 --to 2       # 定積分 F(2) - F(0) = 10

./mathcam.exe sum --expr "3k^2 - k" --steps                 # (n + 1)*n^2
./mathcam.exe sum --expr "k^2" --from 5 --to 10             # 355
./mathcam.exe sum --expr "sum(k, 1, n, 2^(k-1))"            # 2^(n) - 1（等比数列の和）
./mathcam.exe seq --terms "1, 2, 4, 7, 11" --steps          # 階差数列 -> a_n = (n^2 - n + 2)/2
./mathcam.exe seq --terms "3, 6, 12, 24" --nth 8            # 等比数列 -> 第 8 項 384
./mathcam.exe recur --next "2a + 1" --a1 1 --steps          # 漸化式 -> a_n = 2^n - 1（特性方程式）
./mathcam.exe recur --next "a + n" --a1 1                   # 階差型 -> a_n = (n^2 - n + 2)/2
```

高校の残りもだいたい同じ 1 本で通る:

```sh
# 因数分解（数学 I）
./mathcam.exe factor --expr "x^2 + 5x + 6"          # (x + 2)(x + 3)
./mathcam.exe factor --expr "6x^2y + 9xy^2"         # 3xy(2x + 3y)
./mathcam.exe factor --expr "x^3 - 6x^2 + 11x - 6"  # (x - 1)(x - 2)(x - 3)（因数定理）

# 三角関数・指数対数（数学 II）
./mathcam.exe eval  --expr "sin(pi/6) + cos(pi/3)"  # 1（特別角は厳密な値）
./mathcam.exe eval  --expr "log(2, 8) + log(4, 8)"  # 9/2
./mathcam.exe solve --expr "sin(x) = 1/2"           # x = pi/6, 5pi/6（0 <= x < 2pi）
./mathcam.exe solve --expr "2^(x+1) = 4^x"          # x = 1
./mathcam.exe solve --expr "log(2,x) + log(2,x-2) = 3"   # x = 4（真数条件で -2 を捨てる）
./mathcam.exe trig  --expr "sin(x) + sqrt(3)cos(x)"  # 2 sin(x + pi/3)（合成）
./mathcam.exe trig  --expr "sin(2x)"                 # 2 sin(x) cos(x)（2 倍角）

# 高次方程式・複素数・絶対値
./mathcam.exe solve --expr "x^3 + 1 = 0"            # x = -1, 1/2 ± (sqrt(3)/2)i
./mathcam.exe solve --expr "|x - 1| < 2"            # -1 < x < 3

# 微分の応用・極限・面積（数学 II / III）
./mathcam.exe curve --expr "x^2 - 4x + 1"           # 平方完成・頂点・軸・最小値
./mathcam.exe curve --expr "x^3 - 3x" --at 2        # 接線 y = 9x - 16、極大・極小
./mathcam.exe limit --expr "(x^2 - 1)/(x - 1)" --to 1    # 2（0/0 を約分する）
./mathcam.exe limit --expr "(2x^2 + 1)/(x^2 - x)" --to inf   # 2（最高次で割る）
./mathcam.exe area  --expr "x^2" --and "x"          # 1/6（交点を求めて ∫(上 - 下)）
./mathcam.exe apart --expr "1/(x^2 - 1)"            # 部分分数分解 -> 1/(2(x-1)) - 1/(2(x+1))
./mathcam.exe integ --expr "1/(x^2 - 1)"            # 分けてから積分 -> log の和

# 図形と方程式（数学 II）
./mathcam.exe circle --expr "x^2 + y^2 - 4x + 2y - 4 = 0"   # 中心 (2, -1)、半径 3

# 場合の数（数学 A）
./mathcam.exe eval --expr "C(10, 3) + 5!"           # 240
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

## 実写はなぜ落ちたか（測って分かったこと）

合成データでは 95〜98% 読めるのに、**教科書を撮った写真は 12 問すべて外した**。
原因は写真の難しさではなく、**学習データの「書き方」が実物と違う**ことだった。

| 何を変えたか（式も枠も同じ、描き方だけ） | 端から端まで |
|---|---|
| 今までの書き方（Liberation 立体 + ASCII ハイフン） | 95.0% |
| 教科書の書き方（イタリック + U+2212 のマイナス） | **33.3%** |

* U+2212（長い横棒）のマイナスは**検出器が 1 つも取れない**。conf を 0.01 まで下げて初めて出る。
* イタリックの `x` は Times italic なら読めるが、教科書の Computer Modern だと `y` に化ける。
* 対策は組版器側: `--italic` と `--minus 2212`、データセットは `--italic-pct` /
  `--minus2212-pct` / `--prefix`（書体を変えて同じ dir に足せる）。書体は
  cmr10 + cmmi10（TeX の Computer Modern）、STIXGeneral(+Italic)、DejaVu、Liberation を混ぜる。
* **数式書体はリポジトリに入れた**（`fonts/`、3.8MB、ライセンス文つき）。実写の変数は
  数式用のイタリック（KaTeX Math Italic や cmmi10）で、本文用のイタリックとは字が違う。
  `tools/make_mix.py` がこれを最初に使うので、**どこでも同じ学習データが作れる**。
* 実写の測り方は `tests/real_photos.txt`（正解表）と `tools/real_eval.py`。
  **写真はリポジトリに入れない**（教科書は著作物）ので、手元に置いて測る。
  囲まずに 1 枚渡す道は `tools/page_eval.py`（`photo --auto-cells` を測る。別の問い）。

### 実写の写真 1 枚から出た手順（小学校の計算のページ）

`mathcam photo --img <写真> --crop 460,155,1420,250 --steps` の実際の出力:

```
23 記号を検出
読めた式: 261/10
1. [かっこの中を計算] 1.8 × 3.5 = 6.3      -> (6.3 - (10.2 - 6.8)) × 9
2. [かっこの中を計算] 10.2 - 6.8 = 3.4     -> (6.3 - 3.4) × 9
3. [たし算・ひき算] 6.3 - 3.4 = 2.9        -> 2.9 × 9
4. [かけ算・わり算を先に] 2.9 × 9 = 26.1   -> 26.1
答え: 26.1
```

写真は教科書なのでリポジトリに入れていない。**手順の順序（かっこ → かけ算・わり算 →
たし算・ひき算）は小学校の書き方**で、`pure/arith.hpp` が畳まない木を内側から 1 手ずつ
畳んで作る。ブラウザでも同じ関数を通る。

### そこから何をして上がったか（実測値つき）

| 手 | 実写 27 問 |
|---|---|
| 学習データを教科書の書き方に（イタリック + U+2212、書体 13 組） | 0 → 18 |
| **括弧と数字の取り違えを構造で直す**（背が高くて細ければ括弧）+ 上付き判定を締める | 18 → 19 |
| **合成データを写真に近づける**（紙の明暗ムラ・粒子・JPEG のにじみ） | 19 → 20（image1 は 12/12、小学校のページも 2/2） |
| 答え欄の四角が `÷` として検出される件（相手のいない演算子を落とす） | 20 → 21 |
| 同じ字に大小 2 つの箱が出る件（**入れ子の箱**も重複として落とす。IoU では残る） | 21 → 22 |
| 正解表を 27 → 32 問に増やす（測っていなかった問題と「縦棒の 1」の例を足す） | 25 / 32 |
| **正解表の切り出しが 4 行も字を切っていた**（上付きの 2 や行の下端。`tools/check_key.py` で発見） | 29 / 32 |
| **教科書体の数字を画像で持って学習**（実物の `1` は旗も台も無い縦棒。`fonts/kyokasho`） | 30 / 32（小学校のページは 6 問全部） |
| 相手のいない括弧を端から落とす（紙の端が中括弧として拾われていた） | **31 / 32（96.9%）** |

学習の側で分かったいちばん大事なこと: **合成の val では実写の失敗が見えない**。
劣化なしのデータで 18 epoch 回すと mAP50 は 0.993 のままなのに、実写は
6 → 5 → 5 → 8 → 3 件と落ちていく。だから途中の重みを残して**実写で選ぶ**
（`--save-period` と `scratch/pick_checkpoint.py`）。劣化ありのデータだと epoch 0 で
すでに 19、epoch 3 で 20 と、始まりから違う。

```sh
python tools/real_eval.py --dir test_data --model models/sym_det_v5.onnx --show
```

## 小学校の計算（× ÷ 小数点 帯分数 中括弧）

写真のうち 2 枚は小学校のプリントだった（`{1.8 × 3.5 - (10.2 - 6.8)} × 9`、
`2 5/8 × 4/7 - (5 1/3 - 1/2) ÷ 5`）。ここで分かったのは、**CAS の木からは小学校の書き方を
描けない**ということ: `0.96 ÷ 1.2` は正規形にすると `4/5` に畳まれて ÷ が消え、`2 5/8` は
`21/8` になる。そこで「書かれたとおりに描く」道を別に持つ。

```sh
# 記法: frac(a,b) は縦の分数、mixed(w,a,b) は帯分数、× ÷ ( ) { } と小数はそのまま
./mathcam.exe render --expr "mixed(2,5,8) × frac(4,7) - (mixed(5,1,3) - frac(1,2)) ÷ 5"                      --arith --out q.png --px 56
./mathcam.exe eval   --expr "mixed(2,5,8) × frac(4,7) - (mixed(5,1,3) - frac(1,2)) ÷ 5"  # 8/15
./mathcam.exe selftest --n 300 --arith     # 描いて読み戻して値が一致するか（300/300）
./mathcam.exe dataset --out data/train --n 5000 --arith --photo-like

# 手順も出る（かっこの中 -> かけ算・わり算 -> たし算・ひき算、帯分数は仮分数に直す）
./mathcam.exe solve --expr "{1.8 × 3.5 - (10.2 - 6.8)} × 9" --steps
#   1. [かっこの中を計算] 1.8 × 3.5 = 6.3      (6.3 - (10.2 - 6.8)) × 9
#   ...
#   4. [かけ算・わり算を先に] 2.9 × 9 = 26.1   26.1
python tools/arith.py --expr "{1.8 × 3.5 - (10.2 - 6.8)} × 9"   # Python 側も同じ手順
python tools/parity/arith.py --n 200                            # 手順の全行を突き合わせる
```

* **絵と値の出どころは 1 つのテキスト**。絵は `ts::present_arith` が作り、値は同じ文字列を
  `ex::parse` に通す（`frac` / `mixed` は割り算と足し算に畳む）。
* クラス表の末尾に `times / div / dot / brace_l / brace_r` を足した。**末尾に足すので既存モデルと
  番号は互換**だが、検出されるようにするには 39 クラスで学習し直す必要がある。
* プリントの「… = □」は右辺が空。**= の右が空なら左だけの式として読む**ようにした。
* 手順を出すには**畳まない木**が要る（CAS は読んだ時点で計算してしまうので、どこを先に
  計算したかが消える）。`ex::parse_raw` / `pl::parse_raw` がそれを作り、`pure/arith.hpp` が
  内側から 1 手ずつ畳む。**小数で書くのは元の式が小数のときだけ**（分数の問題で `5/8` を
  `0.625` と書いたら小学校の答えとしては嘘）。

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

`fonts/` に入れてある**数式書体は第三者のもの**で、それぞれのライセンスに従う
（ライセンス文を同じディレクトリに置いてある。詳しくは [fonts/README.md](fonts/README.md)）:

| 書体 | ライセンス |
|---|---|
| KaTeX Main / KaTeX Math Italic | MIT |
| Computer Modern（cmr10 / cmmi10 / cmb10 / cmmib10） | `fonts/cm/LICENCE` |
| New Computer Modern（NewCM10 / NewCMMath） | GUST Font License |
| TeX Gyre Pagella / Heros | GUST Font License |

`models/sym_det_v5.onnx` は自前の合成データだけで学習したもの（BSD-3-Clause）。
`test_data/` の教科書の写真は**入れていない**（著作物）。
