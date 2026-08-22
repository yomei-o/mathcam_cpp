# fonts/ — 学習データを描くための数式書体

**なぜリポジトリに入れてあるか。** 実写の教科書は変数が**数式用のイタリック**で書かれている。
本文用のイタリック（Liberation Italic、Lato Italic など）とは字が違い、そこを外すと実写で
`x` が `y` に化ける（実測: 学習データの書体とマイナスの字が実物と違うだけで実写 0/12 だった）。
数式書体は環境に入っているとは限らないので、**ここに置いて `tools/make_mix.py` が最初に使う**。
これで手元・Kaggle・他人の環境で**同じ学習データが作れる**。

合計 3.8MB。すべて再配布できるライセンスで、**ライセンス文を同じディレクトリに置いてある**。

| ディレクトリ | 書体 | 出どころ | ライセンス |
|---|---|---|---|
| `katex/` | KaTeX Main（立体・太字）、KaTeX Math Italic（斜体・太斜体） | [KaTeX](https://katex.org/)（Web の数式表示で使われているもの） | MIT（`katex/LICENSE`） |
| `cm/` | Computer Modern: cmr10 / cmb10（立体）、cmmi10 / cmmib10（数式斜体） | TeX の標準書体（Julia の MathTeXEngine 同梱） | `cm/LICENCE` |
| `newcm/` | New Computer Modern: NewCM10 Regular / Italic、NewCMMath Regular | GUST（CM の後継） | GUST Font License（`newcm/LICENCE`） |
| `pagella/` | TeX Gyre Pagella: Regular / Italic / Math（Palatino 系） | GUST | GUST Font License（`pagella/LICENSE`） |
| `heros/` | TeX Gyre Heros: Regular / Italic（Helvetica 系のサンセリフ） | GUST | GUST Font License（`heros/LICENSE`） |

## 使い方

```sh
# 見つかった組を確認する（リポジトリの書体が先に来る）
python tools/make_mix.py --list

# 学習データ一式（train 36400 / val 2080）
python tools/make_mix.py --out data9
```

`--font` と `--font-italic` に直接渡すこともできる:

```sh
./mathcam.exe render --expr "3x^2 - 5x + 6 = 0" --italic --minus 2212 \
  --font fonts/katex/KaTeX_Main-Regular.ttf --font-italic fonts/katex/KaTeX_Math-Italic.ttf \
  --out out.png
```

## 気をつける点

* **数式書体でも ASCII の英字が立体のものがある**（NewCMMath-Regular、TeXGyrePagella-Math、
  STIX Two Math）。斜体が要るところには KaTeX Math Italic・cmmi10・NewCM10-Italic・
  Pagella-Italic を使う。立体の数式書体は「立体側」（数字と演算子）に使うと字形の幅が出る。
* `mathcam fontinfo --font A --font-italic B` が**必要な字が全部あるか**を報告する。
  書体を足すときは必ずこれを通す（字が無いと、その記号だけ枠のない学習データができる）。
* STIX Two Math と CMU Serif Math は Julia の artifacts にライセンス文が同梱されていなかった
  ので**入れていない**（再配布のため）。必要なら各自で置けば `make_mix.py` の候補に足せる。
