// mathcam — このプロジェクトの CLI（C++ 側）。tools/ の Python 側と 1 対 1 に対応させる。
//
//   mathcam eval  --expr "2/3 + 1/6"          式を読んで正規形と答えを出す
//   mathcam solve --expr "x^2 - 5x + 6 = 0" [--steps] [--latex]  解く（手順つき）
//   mathcam render --expr "1/2 x + sqrt(2) = 0" --out out.png [--labels out.txt] [--px 48]
//   mathcam dataset --out data/train --n 2000 [--seed 1] [--px-min 32 --px-max 64]
//   mathcam parse   --labels out.txt        枠の列から式木に戻す（レイアウト解析）
//   mathcam selftest --n 500                組版 -> 解析 -> 元の式に戻るかを測る
//   mathcam photo --img x.png --model models/sym_det_v5.onnx [--steps]   写真 1 枚を端から端まで
//
// build: sh build/cc.sh pure/mathcam.cpp -o mathcam.exe
//        sh build/gcc.sh pure/mathcam.cpp -o mathcam.exe
#define STB_IMAGE_IMPLEMENTATION
#define STB_TRUETYPE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
#include "stb_image.h"
#include "expr.hpp"
#include "solve.hpp"
#include "arith.hpp"
#include "calc.hpp"
#include "seq.hpp"
#include "factor.hpp"
#include "curve.hpp"
#include "limit.hpp"
#include "area.hpp"
#include "trig.hpp"
#include "recur.hpp"
#include "circle.hpp"
#include "vector.hpp"
#include "typeset_impl.hpp"
#include "gen_expr.hpp"
#include "parse_layout.hpp"
#include "classes.hpp"
#include "pipeline.hpp"
#include "train_det.hpp"
#include "build_v8.hpp"
#include <cstdio>
#include <clocale>
#include <cstring>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#include <direct.h>
#else
#include <sys/stat.h>
#endif

// mkdir -p。生成物の親ディレクトリが無いと fopen が黙って失敗し、症状は数手あとの
// 「ファイルが無い」だけになる（姉妹リポで踏んだ落とし穴。あちらの RESUME にも記録がある）。
static void make_dir(const std::string& d) {
  std::string acc;
  for (size_t i = 0; i <= d.size(); ++i) {
    if (i == d.size() || d[i] == '/' || d[i] == (char)0x5c) {
      if (!acc.empty() && acc != "." && acc != "..") {
#ifdef _WIN32
        _mkdir(acc.c_str());
#else
        mkdir(acc.c_str(), 0755);
#endif
      }
    }
    if (i < d.size()) acc += d[i];
  }
}

static std::string arg_of(int argc, char** argv, const std::string& key, const std::string& def) {
  for (int i = 2; i + 1 < argc; ++i) if (key == argv[i]) return argv[i + 1];
  return def;
}
static bool has_flag(int argc, char** argv, const std::string& key) {
  for (int i = 2; i < argc; ++i) if (key == argv[i]) return true;
  return false;
}

// 実写に寄せた描き方の指定を作る。--italic は変数をイタリックに、--minus 2212 は
// 教科書のマイナス（長い横棒）にする。既定は今までと同じ絵（測った数字と比べられるように）。
static ts::Style style_of(int argc, char** argv) {
  ts::Style st;
  st.italic_vars = has_flag(argc, argv, "--italic");
  st.minus_cp = arg_of(argc, argv, "--minus", "hyphen") == "2212" ? 0x2212 : '-';
  st.plain_one = has_flag(argc, argv, "--plain-one");     // 1 を縦棒だけの字で描く
  return st;
}

// mathcam eval — 式を 1 つ読み、正規形・LaTeX・数値を出す。
// 数値は「厳密に閉じない式のとき」だけ意味があるので、有理数で閉じたときは出さない
// （0.6666666667 を見せると、厳密に 2/3 を保っている設計が伝わらない）。
static int cmd_eval(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const bool latex = has_flag(argc, argv, "--latex");
  const bool approx = has_flag(argc, argv, "--approx");
  if (src.empty()) {
    printf("usage: mathcam eval --expr \"2/3 + 1/6\" [--latex] [--approx]\n");
    return 1;
  }
  std::string why;
  ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  // eval は「人が期待する答えの形」を出す場所なので展開する。くくった形を保ちたい
  // 場面（因数分解の手順表示）では expand を呼ばない。
  if (!has_flag(argc, argv, "--no-expand")) e = ex::expand(e);
  printf("%s\n", ex::to_infix(e).c_str());
  // 割り切れる分数は小数でも見せる（小学校の計算は小数で答える）
  if (ex::is_num(e) && !e->num.is_int()) {
    const std::string dec = ex::to_decimal(e->num);
    if (!dec.empty()) printf("小数: %s\n", dec.c_str());
  }
  if (latex) printf("latex: %s\n", ex::to_latex(e).c_str());
  if (approx && !(e->k == ex::Kind::Num)) printf("approx: %.10g\n", ex::approx(e));
  return 0;
}

// mathcam solve — 方程式・不等式・連立を解く。--steps で「人が紙に書く手」を並べる。
// 正規化（同類項をまとめる・約分）は手順に出さない。出すと人には読めないものになる。
// 連立は "," か ";" で区切る（1 つの --expr にまとめて渡す）。
static int cmd_solve(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string var = arg_of(argc, argv, "--var", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam solve --expr \"x^2 - 5x + 6 = 0\" [--var x] [--steps] [--latex]\n"
           "       mathcam solve --expr \"3x - 5 > 1\" --steps            (不等式)\n"
           "       mathcam solve --expr \"x + y = 5, 2x - y = 1\" --steps (連立方程式)\n"
           "       mathcam solve --expr \"2x > 4, x - 1 <= 4\" --steps    (連立不等式)\n");
    return 1;
  }
  std::string why;
  ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }

  const slv::Solution s = slv::solve(e, var);
  auto show = [&](const ex::E& x) { return latex ? ex::to_latex(x) : ex::to_infix(x); };
  if (!s.ok && e->k != ex::Kind::Rel && e->k != ex::Kind::Sys) {
    // 方程式でないなら「計算問題」として、小学校の順序で 1 手ずつ計算する。
    // **関係式のときはここに来ない**（解けない方程式を黙って echo すると、
    // 「解けた」のか「読めなかった」のかが利用者にも Python 側にも分からなくなる）。
    // **畳まない木**で読み直すのが要点（ex::parse は 1.8 × 3.5 を先に畳んでしまう）
    std::string why2;
    const ex::E rawe = ex::parse_raw(src, &why2);
    // 小数で書くのは、元の式が小数で書かれていたときだけ（分数の問題で 5/8 を 0.625 と
    // 書いたら小学校の答えとしては嘘になる）
    const bool dec_ok = src.find('.') != std::string::npos;
    const ar::Result ares = why2.empty() ? ar::eval_steps(rawe, dec_ok) : ar::Result();
    if (why2.empty()) {
      // **畳めるところまで出す。** 文字が混ざっていると数にはならないが（`7 × n + 3`）、
      // 途中まで計算して見せるのが正しい。ここで諦めていたので、Python 側（tools/arith.py）
      // だけが途中結果を出していて食い違っていた（生成器に `× 文字` を入れて初めて出た）。
      if (steps)
        for (size_t i = 0; i < ares.steps.size(); ++i)
          printf("%zu. [%s] %s\n   %s\n", i + 1, ares.steps[i].rule.c_str(),
                 ares.steps[i].note.c_str(), ares.steps[i].after.c_str());
      printf("%s\n", ares.ok ? ar::to_text(ares.value, dec_ok).c_str()
                             : ex::to_infix(ex::expand(e)).c_str());
      return 0;
    }
    printf("solve: %s\n", s.why.c_str());
    return 1;
  }
  if (steps) {
    for (size_t i = 0; i < s.steps.size(); ++i) {
      const slv::Step& st = s.steps[i];
      printf("%zu. [%s] %s\n", i + 1, st.rule.c_str(), st.note.c_str());
      printf("   %s\n", show(st.after).c_str());
    }
  }
  // 答えの文言は slv::answer_lines の 1 か所だけ（Python 側も同じ関数の鏡を通る）
  for (const std::string& line : slv::answer_lines(s, latex)) printf("%s\n", line.c_str());
  return 0;
}

// 画像で持つ字（`mathcam fontdump` の出力）を重ねる。**数字と四則と括弧だけ教科書体**、
// 変数は数式書体、という組み方ができる（教科書体のファイル自体は配れないため）。
static bool load_bits_if_asked(int argc, char** argv, ts::Font& f) {
  const std::string dir = arg_of(argc, argv, "--font-bits", "");
  if (dir.empty()) return true;
  std::string why;
  if (!ts::load_bitmap_glyphs(f, dir, &why)) { printf("%s\n", why.c_str()); return false; }
  return true;
}

// mathcam fontdump — **必要な字だけを画像にして書き出す**。
//
// 教科書体のように再配布できない書体でも、字の形だけを画像にすれば学習データを作れる
// （書体ファイルは配らない）。小学校のページに要るのは数字・四則・括弧なので、既定はそこだけ。
// 出したものは `--font-bits <dir>` で組版に差し込める（他の字は今までどおり TTF から）。
static int cmd_fontdump(int argc, char** argv) {
  const std::string fontp = arg_of(argc, argv, "--font", "");
  const std::string out = arg_of(argc, argv, "--out", "");
  const int px = std::atoi(arg_of(argc, argv, "--px", "192").c_str());
  const std::string only = arg_of(argc, argv, "--chars", "");
  if (fontp.empty() || out.empty()) {
    printf("usage: mathcam fontdump --font path.ttf --out fonts/kyokasho [--px 192]\n"
           "                        [--chars 0123456789+-=().]\n"
           "  小学校の教科書に要る字（数字・四則・括弧・小数点・中括弧）を画像にする\n");
    return 1;
  }
  // 既定の字。× ÷ − は ASCII に無いので符号位置で持つ
  std::vector<int> cps;
  if (only.empty()) {
    for (int c = '0'; c <= '9'; ++c) cps.push_back(c);
    const int extra[] = {'+', '-', 0x2212, '=', '(', ')', 0x00D7, 0x00F7, '.', '{', '}'};
    for (int c : extra) cps.push_back(c);
  } else {
    // UTF-8 を符号位置に開く（× ÷ を渡せるように）
    for (size_t i = 0; i < only.size();) {
      const unsigned char c = (unsigned char)only[i];
      int cp = c, n = 1;
      if (c >= 0xF0) { cp = c & 0x07; n = 4; }
      else if (c >= 0xE0) { cp = c & 0x0F; n = 3; }
      else if (c >= 0xC0) { cp = c & 0x1F; n = 2; }
      for (int k = 1; k < n && i + k < only.size(); ++k) cp = (cp << 6) | (only[i + k] & 0x3F);
      cps.push_back(cp);
      i += n;
    }
  }
  ts::Font f;
  std::string why;
  if (!ts::load_font(f, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  make_dir(out);
  std::string meta = "# mathcam fontdump（字の形だけを画像で持つ。書体ファイルは配らない）\n";
  meta += "upem " + std::to_string(f.upem) + "\n";
  int wrote = 0;
  for (int cp : cps) {
    int adv = f.advance(cp), x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    f.bbox(cp, &x0, &y0, &x1, &y1);
    char name[64];
    std::snprintf(name, sizeof(name), "g_%04X.png", (unsigned)cp);
    int w = 0, h = 0;
    if (x1 > x0 && y1 > y0) {
      // bbox にぴったりの大きさで焼く（読む側は bbox に合わせて伸ばすだけで済む）
      const float sc = (float)px / (float)f.upem;
      w = std::max(1, (int)std::ceil((x1 - x0) * sc));
      h = std::max(1, (int)std::ceil((y1 - y0) * sc));
      std::vector<unsigned char> bm((size_t)w * h, 0);
      ts::rasterize_glyph(f, cp, bm.data(), w, h);
      if (!stbi_write_png((out + "/" + name).c_str(), w, h, 1, bm.data(), w)) {
        printf("書けません: %s/%s\n", out.c_str(), name);
        return 1;
      }
    }
    char line[256];
    std::snprintf(line, sizeof(line), "%d %d %d %d %d %d %s %d %d\n", cp, adv, x0, y0, x1, y1,
                  name, w, h);
    meta += line;
    ++wrote;
  }
  FILE* fp = fopen((out + "/metrics.txt").c_str(), "wb");
  if (!fp) { printf("書けません: %s/metrics.txt\n", out.c_str()); return 1; }
  fwrite(meta.data(), 1, meta.size(), fp);
  fclose(fp);
  printf("%s に %d 字を書いた（upem %d、%dpx で焼いた）\n", out.c_str(), wrote, f.upem, px);
  return 0;
}

// mathcam diff / integ — 微分と積分。手順つきで出す（solve と同じ作法）。
static int cmd_calc(int argc, char** argv, bool integral) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string var = arg_of(argc, argv, "--var", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  const std::string from = arg_of(argc, argv, "--from", "");
  const std::string to = arg_of(argc, argv, "--to", "");
  if (src.empty()) {
    printf("usage: mathcam diff  --expr \"x^3 + 2x\" [--var x] [--steps] [--latex]\n"
           "       mathcam integ --expr \"3x^2 + 1\" [--var x] [--from 0 --to 2] [--steps]\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  ex::E lo, hi;
  if (!from.empty() && !to.empty()) {
    lo = ex::parse(from, &why);
    if (!why.empty()) { printf("parse error(--from): %s\n", why.c_str()); return 1; }
    hi = ex::parse(to, &why);
    if (!why.empty()) { printf("parse error(--to): %s\n", why.c_str()); return 1; }
  }
  const cal::Result r = integral ? cal::integrate(e, var, lo, hi) : cal::differentiate(e, var);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : cal::answer_lines(r, latex, integral))
    printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam sum — Σ を計算する。--expr に sum(k, 1, n, k^2) と書いても、
// --var/--from/--to で分けて書いてもよい（積分の --from/--to と同じ形にそろえてある）。
static int cmd_sum(int argc, char** argv) {
  std::string src = arg_of(argc, argv, "--expr", "");
  std::string var = arg_of(argc, argv, "--var", "k");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  const std::string from = arg_of(argc, argv, "--from", "1");
  const std::string to = arg_of(argc, argv, "--to", "n");
  if (src.empty()) {
    printf("usage: mathcam sum --expr \"k^2\" [--var k] [--from 1] [--to n] [--steps] [--latex]\n"
           "       mathcam sum --expr \"sum(k, 1, n, k^2)\" [--steps]\n");
    return 1;
  }
  std::string why;
  ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  ex::E lo, hi;
  if (seqs::is_sum(e)) {                             // sum(k, 1, n, 中身) と書かれた形
    var = e->kids[0]->name;
    lo = e->kids[1];
    hi = e->kids[2];
    e = e->kids[3];
  } else {
    lo = ex::parse(from, &why);
    if (!why.empty()) { printf("parse error(--from): %s\n", why.c_str()); return 1; }
    hi = ex::parse(to, &why);
    if (!why.empty()) { printf("parse error(--to): %s\n", why.c_str()); return 1; }
  }
  const seqs::Sum r = seqs::sigma(e, var, lo, hi);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : seqs::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam seq — 項の並びから数列を見分けて、一般項と和を出す
static int cmd_seq(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--terms", "");
  const std::string var = arg_of(argc, argv, "--var", "n");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  const long long nth = std::atoll(arg_of(argc, argv, "--nth", "0").c_str());
  if (src.empty()) {
    printf("usage: mathcam seq --terms \"2, 5, 8, 11\" [--nth 10] [--steps] [--latex]\n");
    return 1;
  }
  std::vector<ex::Rat> a;
  std::string cur;
  for (size_t i = 0; i <= src.size(); ++i) {
    if (i == src.size() || src[i] == ',') {
      if (!cur.empty()) {
        std::string why;
        const ex::E v = ex::parse(cur, &why);
        if (!why.empty() || !ex::is_num(v)) {
          printf("項が数ではありません: %s\n", cur.c_str());
          return 1;
        }
        a.push_back(v->num);
      }
      cur.clear();
      continue;
    }
    cur += src[i];
  }
  seqs::Seq r = seqs::analyze(a, var);
  if (r.ok && nth > 0) {
    r.nth_i = nth;
    r.nth = ex::simp(ex::subst(r.term, var, ex::num(ex::Rat(nth))));
  }
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : seqs::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam factor — 因数分解する（展開の逆）
static int cmd_factor(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam factor --expr \"x^2 + 5x + 6\" [--steps] [--latex]\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  const fac::Result r = fac::factor(e);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : fac::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam curve — 関数を調べる（微分の応用: 接線と極値）
static int cmd_curve(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string var = arg_of(argc, argv, "--var", "");
  const std::string at = arg_of(argc, argv, "--at", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam curve --expr \"x^3 - 3x\" [--var x] [--at 1] [--steps] [--latex]\n"
           "       --at を付けると、その点の接線と法線も出す\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  ex::E a;
  if (!at.empty()) {
    a = ex::parse(at, &why);
    if (!why.empty()) { printf("parse error(--at): %s\n", why.c_str()); return 1; }
  }
  const crv::Result r = crv::curve(e, var, a);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : crv::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam limit — 極限。--to に inf / -inf も書ける
static int cmd_limit(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string var = arg_of(argc, argv, "--var", "");
  const std::string to = arg_of(argc, argv, "--to", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty() || to.empty()) {
    printf("usage: mathcam limit --expr \"(x^2 - 1)/(x - 1)\" --to 1 [--var x] [--steps]\n"
           "       --to inf / --to -inf で x -> ±無限大\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  int at_inf = 0;
  ex::E a;
  if (to == "inf" || to == "+inf") at_inf = 1;
  else if (to == "-inf") at_inf = -1;
  else {
    a = ex::parse(to, &why);
    if (!why.empty()) { printf("parse error(--to): %s\n", why.c_str()); return 1; }
  }
  const lim::Result r = lim::limit(e, var, a, at_inf);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : lim::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam area — 囲まれた面積（定積分の応用）
static int cmd_area(int argc, char** argv) {
  const std::string s1 = arg_of(argc, argv, "--expr", "");
  const std::string s2 = arg_of(argc, argv, "--and", "0");
  const std::string var = arg_of(argc, argv, "--var", "");
  const std::string from = arg_of(argc, argv, "--from", "");
  const std::string to = arg_of(argc, argv, "--to", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (s1.empty()) {
    printf("usage: mathcam area --expr \"x^2\" --and \"x\" [--steps]        (2 曲線で囲む)\n"
           "       mathcam area --expr \"x^2 - 1\" --from 0 --to 2         (x 軸との面積)\n");
    return 1;
  }
  std::string why;
  const ex::E f = ex::parse(s1, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  const ex::E g = ex::parse(s2, &why);
  if (!why.empty()) { printf("parse error(--and): %s\n", why.c_str()); return 1; }
  ex::E lo, hi;
  if (!from.empty()) {
    lo = ex::parse(from, &why);
    if (!why.empty()) { printf("parse error(--from): %s\n", why.c_str()); return 1; }
  }
  if (!to.empty()) {
    hi = ex::parse(to, &why);
    if (!why.empty()) { printf("parse error(--to): %s\n", why.c_str()); return 1; }
  }
  const area::Result r = area::area(f, g, var, lo, hi);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : area::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam trig — 三角関数の変形（加法定理・2 倍角・合成）
static int cmd_trig(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string mode = arg_of(argc, argv, "--mode", "auto");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam trig --expr \"sin(x) + sqrt(3)cos(x)\" [--mode expand|compose]\n"
           "                    [--steps] [--latex]\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  const trg::Result r = trg::transform(e, mode);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : trg::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam recur — 漸化式から一般項を出す。--next に a_(n+1) の式を a と n で書く
static int cmd_recur(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--next", "");
  const std::string a1s = arg_of(argc, argv, "--a1", "");
  const std::string var = arg_of(argc, argv, "--var", "n");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty() || a1s.empty()) {
    printf("usage: mathcam recur --next \"2a + 1\" --a1 1 [--steps] [--latex]\n"
           "       --next は a_(n+1) の式を a（= a_n）と n で書く（`a + 3` `2a` `a + n`）\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  const ex::E a1 = ex::parse(a1s, &why);
  if (!why.empty() || !ex::is_num(a1)) { printf("--a1 は数で書いてください\n"); return 1; }
  const rec::Result r = rec::solve(e, a1->num, var);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : rec::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam apart — 部分分数分解
static int cmd_apart(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string var = arg_of(argc, argv, "--var", "");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam apart --expr \"1/(x^2 - 1)\" [--var x] [--latex]\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  std::vector<std::string> vs;
  ex::collect_syms(e, vs);
  const std::string v = var.empty() ? (vs.empty() ? "x" : vs[0]) : var;
  const cal::Apart a = cal::apart(e, v);
  if (!a.ok) { printf("%s\n", a.why.c_str()); return 1; }
  const ex::E out = cal::apart_expr(a, v);
  printf("%s\n", (latex ? ex::to_latex(out) : ex::to_infix(out)).c_str());
  return 0;
}

// mathcam circle — 円の方程式（中心と半径）
static int cmd_circle(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam circle --expr \"x^2 + y^2 - 4x + 2y - 4 = 0\" [--steps] [--latex]\n");
    return 1;
  }
  std::string why;
  const ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  const cir::Result r = cir::circle(e, "", "");
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : cir::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// mathcam vec — ベクトル（内積・大きさ・なす角・平行と垂直）
static std::vector<ex::E> parse_vec(const std::string& s, std::string& why) {
  std::vector<ex::E> v;
  std::string cur;
  for (size_t i = 0; i <= s.size(); ++i) {
    if (i == s.size() || s[i] == ',') {
      if (!cur.empty()) {
        std::string w;
        const ex::E e = ex::parse(cur, &w);
        if (!w.empty()) { why = w; return {}; }
        v.push_back(e);
      }
      cur.clear();
      continue;
    }
    cur += s[i];
  }
  return v;
}

static int cmd_vec(int argc, char** argv) {
  const std::string sa = arg_of(argc, argv, "--a", "");
  const std::string sb = arg_of(argc, argv, "--b", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (sa.empty() || sb.empty()) {
    printf("usage: mathcam vec --a \"1, 2\" --b \"3, 4\" [--steps] [--latex]\n");
    return 1;
  }
  std::string why;
  const std::vector<ex::E> a = parse_vec(sa, why);
  if (!why.empty()) { printf("parse error(--a): %s\n", why.c_str()); return 1; }
  const std::vector<ex::E> b = parse_vec(sb, why);
  if (!why.empty()) { printf("parse error(--b): %s\n", why.c_str()); return 1; }
  const vec::Result r = vec::analyze(a, b);
  if (steps)
    for (size_t i = 0; i < r.steps.size(); ++i)
      printf("%zu. [%s] %s\n   %s\n", i + 1, r.steps[i].rule.c_str(), r.steps[i].note.c_str(),
             (latex ? ex::to_latex(r.steps[i].after) : ex::to_infix(r.steps[i].after)).c_str());
  for (const std::string& line : vec::answer_lines(r, latex)) printf("%s\n", line.c_str());
  return r.ok ? 0 : 1;
}

// ---------------------------------------------------------------- 検出器を C++ で学習する
//
// **これが両言語対等性の最後の穴だった**。今までは検出器だけ Python（Ultralytics）でしか
// 学習できず、「C++ と Python で同じことができる」が検出器に限って嘘になっていた。
//
// 中身は姉妹リポ（yolo_lpr_cpp）から持ってきた pure/train_det.hpp。要点は
// **ONNX をその場で学習する**こと: Ultralytics の書き出したグラフには、頭の 6 本の Conv
// （box は [B,4*reg_max,H,W]、cls は [B,nc,H,W]）が普通のノードとして残っている。その手前で
// 止めて損失をつなげば、backward が全部の重みに届く。もう 1 つのアーキテクチャ定義は要らない。

static double e2e_rate(const onx::Graph& g, const ts::Font& font, const ts::Font* font_i,
                       const ts::Style& st, int n, uint64_t seed, int px_min, int px_max,
                       int imgsz, float conf);

// mathcam train-det --gradcheck — 損失の勾配を数値微分と突き合わせる
static int cmd_train_det_gradcheck(int argc, char** argv) {
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "7").c_str(), nullptr, 10);
  const int imgsz = 64, B = 2, nc = 3, reg = 16;
  const int64_t hw[3] = {8, 4, 2};
  Rng rng(seed);
  auto randn = [&]() {                                   // Box-Muller（この repo の splitmix64 から）
    const double u1 = std::max(1e-12, rng.unit()), u2 = rng.unit();
    return (float)(std::sqrt(-2 * std::log(u1)) * std::cos(6.283185307179586 * u2));
  };
  std::vector<Tensor> bx, cs;
  std::vector<float> strides;
  for (int l = 0; l < 3; ++l) {
    Tensor b = make_tensor({B, 4 * reg, hw[l], hw[l]}, true);
    Tensor c = make_tensor({B, nc, hw[l], hw[l]}, true);
    for (float& v : b->data) v = randn();
    for (float& v : c->data) v = randn() - 2.f;          // スコアは低いところから始まる（実物と同じ）
    bx.push_back(b);
    cs.push_back(c);
    strides.push_back((float)imgsz / (float)hw[l]);
  }
  std::vector<std::vector<std::array<float, 5>>> gts(B);
  gts[0].push_back({0, 6, 10, 40, 30});
  gts[0].push_back({2, 30, 34, 60, 52});
  gts[1].push_back({1, 2, 2, 20, 14});
  det::LossCfg cfg;
  det::LossOut rep;
  Tensor loss = det::v8_loss(bx, cs, strides, gts, cfg, &rep);
  backward(loss);
  printf("gradcheck: loss %.6f (box %.4f cls %.4f dfl %.4f, fg %d)\n", rep.total, rep.box, rep.cls,
         rep.dfl, rep.fg);
  auto num_grad = [&](Tensor t, int64_t i, float h) {
    const float keep = t->data[i];
    det::LossOut r1, r2;
    t->data[i] = keep + h;
    Tensor l1 = det::v8_loss(bx, cs, strides, gts, cfg, &r1);
    t->data[i] = keep - h;
    Tensor l2 = det::v8_loss(bx, cs, strides, gts, cfg, &r2);
    t->data[i] = keep;
    const float d = (l1->data[0] - l2->data[0]) / (2 * h);
    free_graph(l1);
    free_graph(l2);
    return d;
  };
  double worst = 0, worst_a = 0, worst_n = 0;
  int checked = 0, skipped = 0;
  for (int k = 0; k < 3; ++k)
    for (int which = 0; which < 2; ++which) {
      Tensor t = which ? cs[k] : bx[k];
      for (int sm = 0; sm < 25; ++sm) {
        const int64_t i = (int64_t)rng.below((uint64_t)t->numel());
        const float a = t->grad[i];
        float n = num_grad(t, i, 1e-2f);
        // **割り当てが切り替わる点での差分商は意味がない**（損失は区分的に滑らかなだけ）。
        // 食い違ったら 1/10 の幅で取り直し、それでも合わなければ「段差をまたいだ」と見なす。
        double rel = std::fabs(a - n) / std::max(1e-4f, std::max(std::fabs(a), std::fabs(n)));
        if (rel > 1e-2) {
          const float n2 = num_grad(t, i, 1e-3f);
          const double rel2 = std::fabs(a - n2) / std::max(1e-4f, std::max(std::fabs(a), std::fabs(n2)));
          if (rel2 < rel) { rel = rel2; n = n2; }
          if (rel > 1e-2) { ++skipped; continue; }
        }
        ++checked;
        if (rel > worst) { worst = rel; worst_a = a; worst_n = n; }
      }
    }
  free_graph(loss);
  printf("gradcheck: %d 点、最悪の相対誤差 %.3e（解析 %.6f / 数値 %.6f）\n", checked, worst,
         worst_a, worst_n);
  if (skipped) printf("gradcheck: %d 点は割り当ての段差の上にいたので比べていない\n", skipped);
  printf("gradcheck: %s\n", worst < 1e-2 ? "PASS" : "FAIL");
  return worst < 1e-2 ? 0 : 1;
}

// mathcam build-det — まっさらな yolov8n の ONNX を書く（PyTorch を通さずに作る）
static int cmd_build_det(int argc, char** argv) {
  const std::string out = arg_of(argc, argv, "--out", "");
  v8b::Cfg cfg;
  cfg.nc = std::atoi(arg_of(argc, argv, "--nc", "39").c_str());
  cfg.imgsz = std::atoi(arg_of(argc, argv, "--imgsz", "640").c_str());
  cfg.width = atof(arg_of(argc, argv, "--width", "0.25").c_str());
  cfg.depth = atof(arg_of(argc, argv, "--depth", "0.33").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1234").c_str(), nullptr, 10);
  if (out.empty()) {
    printf("usage: mathcam build-det --out models/fresh.onnx [--nc 39] [--imgsz 640]\n"
           "                        [--width 0.25] [--depth 0.33] [--seed 1234] [--fuse-bn]\n");
    return 1;
  }
  onx::Graph g = v8b::build(cfg, seed);
  size_t np = 0;
  for (const onx::Tensor64& i : g.init_f) np += i.data.size();
  if (has_flag(argc, argv, "--fuse-bn")) {
    int fused = 0;
    g = v8b::fuse_bn(g, &fused);
    printf("BatchNormalization を %d 個たたみ込んだ（推論の形）\n", fused);
  }
  onx::save_onnx(g, out);
  printf("wrote %s: %zu ノード、%zu パラメータ（nc %d, imgsz %d）\n", out.c_str(), g.nodes.size(),
         np, cfg.nc, cfg.imgsz);
  return 0;
}

// mathcam train-det — 検出器を C++ で学習する（ONNX をその場で更新する）
static int cmd_train_det(int argc, char** argv) {
  if (has_flag(argc, argv, "--gradcheck")) return cmd_train_det_gradcheck(argc, argv);
  const std::string onnx_in = arg_of(argc, argv, "--init", "models/sym_det_v5.onnx");
  const std::string data = arg_of(argc, argv, "--data", "");
  const std::string out = arg_of(argc, argv, "--export", "");
  const std::string fixture = arg_of(argc, argv, "--dump-fixture", "");
  const std::string optim = arg_of(argc, argv, "--optim", "sgd");
  int imgsz = std::atoi(arg_of(argc, argv, "--imgsz", "0").c_str());
  int steps = std::atoi(arg_of(argc, argv, "--steps", "20").c_str());
  const int epochs = std::atoi(arg_of(argc, argv, "--epochs", "0").c_str());
  const int batch = std::atoi(arg_of(argc, argv, "--batch", "2").c_str());
  const int limit = std::atoi(arg_of(argc, argv, "--limit", "0").c_str());
  const float lr0 = (float)atof(arg_of(argc, argv, "--lr", optim == "sgd" ? "0.002" : "1e-4").c_str());
  const float lrf = (float)atof(arg_of(argc, argv, "--lrf", "0.01").c_str());
  const float momentum = (float)atof(arg_of(argc, argv, "--momentum", "0.937").c_str());
  const float warm_mom = (float)atof(arg_of(argc, argv, "--warmup-momentum", "0.8").c_str());
  const float wd = (float)atof(arg_of(argc, argv, "--weight-decay", "0.0005").c_str());
  const float ema_decay = (float)atof(arg_of(argc, argv, "--ema-decay", "0.9999").c_str());
  const float close_mosaic = (float)atof(arg_of(argc, argv, "--close-mosaic", "0.1").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1234").c_str(), nullptr, 10);
  const float clip = (float)atof(arg_of(argc, argv, "--clip", "10.0").c_str());   // ultralytics と同じ
  const int val_every = std::atoi(arg_of(argc, argv, "--val-every", "0").c_str());
  const int val_n = std::atoi(arg_of(argc, argv, "--val-n", "40").c_str());
  const std::string out_best = arg_of(argc, argv, "--export-best", "");
  const bool cos_lr = has_flag(argc, argv, "--cos-lr");
  const bool no_aug = has_flag(argc, argv, "--no-aug");
  const bool no_ema = has_flag(argc, argv, "--no-ema");
  const bool dump_loss = has_flag(argc, argv, "--dump-loss");
  if (data.empty()) {
    printf("usage: mathcam train-det --data <dir with images/ labels/> [--init models/sym_det_v5.onnx]\n"
           "                        [--export out.onnx] [--steps 20] [--batch 2] [--imgsz 640]\n"
           "                        [--optim sgd|adam] [--lr 0.002] [--no-aug] [--cos-lr]\n"
           "       mathcam train-det --gradcheck        （損失の勾配を数値微分と突き合わせる）\n");
    return 1;
  }
  det::AugCfg aug;
  aug.mosaic = (float)atof(arg_of(argc, argv, "--mosaic", "1.0").c_str());
  aug.fliplr = (float)atof(arg_of(argc, argv, "--fliplr", "0.0").c_str());   // 数式は左右反転しない
  aug.degrees = (float)atof(arg_of(argc, argv, "--degrees", "3.0").c_str());
  aug.translate = (float)atof(arg_of(argc, argv, "--translate", "0.1").c_str());
  aug.scale = (float)atof(arg_of(argc, argv, "--scale", "0.4").c_str());
  aug.hsv_h = (float)atof(arg_of(argc, argv, "--hsv-h", "0.015").c_str());
  aug.hsv_s = (float)atof(arg_of(argc, argv, "--hsv-s", "0.4").c_str());
  aug.hsv_v = (float)atof(arg_of(argc, argv, "--hsv-v", "0.4").c_str());

  std::vector<det::Item> items = det::read_yolo(data);
  if (limit > 0 && (int)items.size() > limit) items.resize((size_t)limit);
  if (items.empty()) { printf("%s/images に画像がありません\n", data.c_str()); return 1; }
  size_t nbox = 0;
  for (const det::Item& it : items) nbox += it.boxes.size();
  const int per_epoch = std::max(1, (int)((items.size() + batch - 1) / batch));
  if (epochs > 0) steps = epochs * per_epoch;
  int warmup = std::atoi(arg_of(argc, argv, "--warmup", "-1").c_str());
  if (warmup < 0) warmup = std::min(std::max(100, 3 * per_epoch), std::max(1, steps / 5));
  const int mosaic_off_at = close_mosaic > 1.f ? steps - (int)close_mosaic
                                               : steps - (int)(close_mosaic * steps);

  onx::Graph g = onx::load_onnx(onnx_in);
  if (g.nodes.empty()) { printf("%s が読めません\n", onnx_in.c_str()); return 1; }
  det::HeadNames hn;
  std::string why;
  if (!det::find_v8_heads(g, hn, &why)) { printf("%s: %s\n", onnx_in.c_str(), why.c_str()); return 1; }
  if (imgsz <= 0) {
    for (const onx::ValueInfo& v : g.inputs)
      if (v.dims.size() == 4 && v.dims[3] > 0) imgsz = (int)v.dims[3];
    if (imgsz <= 0) imgsz = 640;
  }
  // 損失につながるのは頭の 6 本の Conv だけなので、その手前までを学習する
  // （DFL の射影とデコード部は書き出されたままで動かさない）
  std::set<std::string> needed(hn.box.begin(), hn.box.end());
  needed.insert(hn.cls.begin(), hn.cls.end());
  onx::Trainable t = onx::make_trainable(g, false, needed);
  int bn_nodes = 0;
  for (const onx::Node& n : g.nodes)
    if (n.op_type == "BatchNormalization") ++bn_nodes;
  const bool bn_train = bn_nodes > 0 && !has_flag(argc, argv, "--freeze-bn");

  if (!dump_loss) {
    printf("%s: 学習する tensor %zu 個、パラメータ %zu 個\n", onnx_in.c_str(), t.params.size(),
           onx::param_count(t));
    printf("head: box %s ...（%zu 段）\n", hn.box[0].c_str(), hn.box.size());
    printf("data: 画像 %zu 枚、枠 %zu 個、imgsz %d、batch %d（%d/epoch）、%d step\n", items.size(),
           nbox, imgsz, batch, per_epoch, steps);
    printf("optim: %s lr %g -> %g（%s）、warmup %d、clip %g、EMA %s、BN %s\n", optim.c_str(), lr0,
           lr0 * lrf, cos_lr ? "cosine" : "linear", warmup, clip, no_ema ? "off" : "on",
           bn_nodes ? (bn_train ? "学習する" : "止める") : "無し（畳み込み済み）");
  }

  const bool use_sgd = optim != "adam";
  Ema ema(t.params, ema_decay);
  SGD sgd(t.params, lr0, momentum, wd, true);
  Adam adam(t.params, lr0, 0.9f, 0.999f, 1e-8f, wd, true);

  // 検証（--val-every）。**端から端までの正解率**で測る。合成の式を毎回同じ種で作るので、
  // step をまたいで比べられる
  ts::Font vfont;
  bool have_vfont = false;
  const ts::Style vst = style_of(argc, argv);
  if (val_every > 0 || !out_best.empty()) {
    std::string vw;
    have_vfont = ts::load_font(vfont, arg_of(argc, argv, "--font", ""), &vw);
    if (!have_vfont) printf("検証は使えません（フォントが読めない: %s）\n", vw.c_str());
  }
  std::map<std::string, std::vector<float>> best_snap;
  double best_rate = -1.0;
  int best_step = 0;
  const auto snapshot = [&]() {
    std::map<std::string, std::vector<float>> m;
    for (const auto& kv : t.init) m[kv.first] = kv.second->data;
    return m;
  };
  const auto restore = [&](const std::map<std::string, std::vector<float>>& m) {
    for (const auto& kv : m) {
      auto it = t.init.find(kv.first);
      if (it != t.init.end()) it->second->data = kv.second;
    }
  };
  const auto validate = [&](int step) {
    if (!have_vfont) return;
    if (!no_ema) ema.swap();
    onx::write_back(t);
    const double rate = e2e_rate(t.g, vfont, nullptr, vst, val_n, 12345, 28, 72, imgsz, 0.20f);
    printf("  val @%d: 端から端まで %.1f%%（%d 件）%s\n", step, 100.0 * rate, val_n,
           rate > best_rate ? "  <- best" : "");
    if (rate > best_rate) {
      best_rate = rate;
      best_step = step;
      best_snap = snapshot();                        // EMA を入れ替えた状態で覚える
    }
    if (!no_ema) ema.swap();
    fflush(stdout);
  };

  Rng rng(seed);
  det::LossCfg cfg;
  double first = 0, last = 0;

  for (int step = 0; step < steps; ++step) {
    const float x = (float)step / (float)std::max(1, steps);
    float lr = cos_lr ? lr0 * (lrf + (1 - lrf) * 0.5f * (1 + std::cos(3.14159265358979f * x)))
                      : lr0 * ((1 - x) * (1 - lrf) + lrf);
    float mom = momentum;
    if (step < warmup) {
      const float w = (float)(step + 1) / (float)warmup;
      lr *= w;
      mom = warm_mom + (momentum - warm_mom) * w;
    }
    sgd.lr = lr;
    sgd.momentum = mom;
    adam.lr = lr;
    std::vector<int> idx;
    if ((int)items.size() <= batch)
      for (size_t i = 0; i < items.size(); ++i) idx.push_back((int)i);
    else
      for (int b = 0; b < batch; ++b) idx.push_back((int)rng.below((uint64_t)items.size()));
    det::Batch ba = no_aug ? det::make_batch(items, idx, imgsz)
                           : det::make_batch_aug(items, idx, imgsz, rng, aug, step < mosaic_off_at);
    det::LossOut rep;
    std::vector<Tensor> bxs, css;
    Tensor loss = det::forward_loss(t, hn, ba.x, ba.gts, imgsz, cfg, &rep, &bxs, &css, bn_train);
    if (use_sgd) sgd.zero_grad(); else adam.zero_grad();
    backward(loss);
    const float gnorm = clip_grad_norm(t.params, clip);
    if (step == 0) first = rep.total;
    last = rep.total;
    if (dump_loss) printf("%d %.6f %.6f %.6f %.6f\n", step, rep.total, rep.box, rep.cls, rep.dfl);
    else printf("step %d: loss %.4f (box %.4f cls %.4f dfl %.4f) fg %d lr %.2e |g| %.1f%s\n", step,
                rep.total, rep.box, rep.cls, rep.dfl, rep.fg, lr, gnorm,
                (clip > 0 && gnorm > clip) ? " (clip)" : "");
    fflush(stdout);
    if (!fixture.empty() && step == 0) {
      // step 0 の頭の出力・正解枠・損失・勾配。Python 側（tools/parity/train_det.py）が
      // **同じ数**を ultralytics の v8DetectionLoss に食わせて突き合わせる
      FILE* f = fopen(fixture.c_str(), "wb");
      if (f) {
        auto wi = [&](int32_t v) { fwrite(&v, 4, 1, f); };
        fwrite("MCAMDET1", 1, 8, f);
        wi((int32_t)bxs.size());
        wi((int32_t)bxs[0]->shape[0]);
        wi((int32_t)css[0]->shape[1]);
        wi((int32_t)(bxs[0]->shape[1] / 4));
        wi((int32_t)imgsz);
        for (size_t l = 0; l < bxs.size(); ++l) wi((int32_t)bxs[l]->shape[2]);
        for (const Tensor& b : bxs) fwrite(b->data.data(), 4, (size_t)b->numel(), f);
        for (const Tensor& c : css) fwrite(c->data.data(), 4, (size_t)c->numel(), f);
        int32_t ngt = 0;
        for (const auto& v : ba.gts) ngt += (int32_t)v.size();
        wi(ngt);
        for (size_t b = 0; b < ba.gts.size(); ++b)
          for (const auto& q : ba.gts[b]) { wi((int32_t)b); fwrite(q.data(), 4, 5, f); }
        const float parts[4] = {rep.total, rep.box, rep.cls, rep.dfl};
        fwrite(parts, 4, 4, f);
        for (const Tensor& b : bxs) fwrite(b->grad.data(), 4, (size_t)b->numel(), f);
        for (const Tensor& c : css) fwrite(c->grad.data(), 4, (size_t)c->numel(), f);
        fclose(f);
        printf("wrote %s（step 0 の頭の出力・正解枠・損失・勾配）\n", fixture.c_str());
      }
    }
    if (use_sgd) sgd.step(); else adam.step();
    if (!no_ema) ema.update();
    free_graph(loss);
    if (val_every > 0 && (step + 1) % val_every == 0) validate(step + 1);
  }
  if (have_vfont && (val_every <= 0 || steps % val_every != 0)) validate(steps);   // 最後に 1 回
  if (!dump_loss) printf("loss %.4f -> %.4f（%d step）\n", first, last, steps);
  if (!out_best.empty() && !best_snap.empty()) {
    const std::map<std::string, std::vector<float>> live = snapshot();
    restore(best_snap);
    onx::write_back(t);
    onx::save_onnx(t.g, out_best);
    printf("wrote %s（いちばん良かった step %d、端から端まで %.1f%%）\n", out_best.c_str(),
           best_step, 100.0 * best_rate);
    restore(live);
  }
  if (!out.empty()) {
    if (!no_ema) ema.swap();
    onx::write_back(t);
    onx::save_onnx(t.g, out);
    if (!no_ema) ema.swap();
    printf("wrote %s%s\n", out.c_str(), no_ema ? "" : "（EMA の重み）");
  }
  return 0;
}

// mathcam render — 式を組版して画像にする。--labels で記号ごとの正解枠も書く。
// これが認識器の学習データ生成器になる（人手のアノテーションより正確な枠が、組版の副産物
// として得られる）。同じ組版を手順表示の描画にも使う。
static int cmd_render(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string out = arg_of(argc, argv, "--out", "");
  const std::string labels = arg_of(argc, argv, "--labels", "");
  const std::string fontp = arg_of(argc, argv, "--font", "");
  const std::string fontip = arg_of(argc, argv, "--font-italic", "");
  const int px = std::atoi(arg_of(argc, argv, "--px", "48").c_str());
  const ts::Style st = style_of(argc, argv);
  if (src.empty() || (out.empty() && labels.empty())) {
    printf("usage: mathcam render --expr \"1/2 x = 3\" --out out.png [--labels out.txt]\n"
           "                      [--px 48] [--font path.ttf] [--font-italic path.ttf]\n"
           "                      [--italic] [--minus 2212]\n");
    return 1;
  }
  std::string why;
  // --arith は「書かれたとおりに描く」ので、式として読めなくてもよい
  // （プリントの「… = □」は右辺が空で、CAS には読めない）
  const bool arith_mode = has_flag(argc, argv, "--arith");
  ex::E e = ex::parse(src, &why);
  if (!why.empty() && !arith_mode) { printf("parse error: %s\n", why.c_str()); return 1; }

  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  if (!load_bits_if_asked(argc, argv, font)) return 1;
  const bool has_i = st.italic_vars && ts::load_font(font_i, fontip, nullptr, true);
  // ÷ や帯分数は正規形で消えるので、木を経由しない道で描く
  const ts::Rendered R = arith_mode
                             ? ts::render_arith(font, has_i ? &font_i : nullptr, src, px, st)
                             : ts::render(font, has_i ? &font_i : nullptr, e, px, st);
  if (!out.empty()) {
    if (!stbi_write_png(out.c_str(), R.w, R.h, 1, R.gray.data(), R.w)) {
      printf("cannot write %s\n", out.c_str());
      return 1;
    }
    printf("wrote %s (%dx%d, %zu 記号, upem %d)\n", out.c_str(), R.w, R.h, R.cls.size(),
           font.upem);
  }
  if (!labels.empty()) {
    FILE* fp = fopen(labels.c_str(), "wb");
    if (!fp) { printf("cannot write %s\n", labels.c_str()); return 1; }
    // 1 行 1 記号: クラス x0 y0 x1 y1（画素、y は下向き）
    fprintf(fp, "# %s\n# image %d %d\n", src.c_str(), R.w, R.h);
    for (size_t i = 0; i < R.cls.size(); ++i)
      fprintf(fp, "%s %d %d %d %d\n", R.cls[i].c_str(), R.box[i * 4], R.box[i * 4 + 1],
              R.box[i * 4 + 2], R.box[i * 4 + 3]);
    fclose(fp);
    printf("wrote %s\n", labels.c_str());
  }
  return 0;
}

// mathcam dataset — 認識器の学習データを作る。式を乱数で作り、組版して、画像と正解枠を書く。
// 乱数は splitmix64 なので、同じ種なら Python 側（tools/dataset.py）と**同じ式列**になる。
static int cmd_dataset(int argc, char** argv) {
  const std::string dir = arg_of(argc, argv, "--out", "");
  const int n = std::atoi(arg_of(argc, argv, "--n", "100").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1").c_str(), nullptr, 10);
  const int px_min = std::atoi(arg_of(argc, argv, "--px-min", "32").c_str());
  const int px_max = std::atoi(arg_of(argc, argv, "--px-max", "64").c_str());
  const std::string fontp = arg_of(argc, argv, "--font", "");
  const std::string fontip = arg_of(argc, argv, "--font-italic", "");
  const std::string prefix = arg_of(argc, argv, "--prefix", "");
  // 実写に寄せるための混ぜ具合（0..100 の百分率）。**教科書は変数がイタリックで
  // マイナスが U+2212**（実測: どちらも学習データに無く、本物の写真で x が y に化けた）。
  const int ital_pct = std::atoi(arg_of(argc, argv, "--italic-pct", "50").c_str());
  const int minus_pct = std::atoi(arg_of(argc, argv, "--minus2212-pct", "50").c_str());
  // 数字の 1 を「縦棒だけ」の字で描く割合。実写の教科書の 1 は旗の無い縦棒で、
  // 手元の書体はどれも旗つき。この字形が学習データに無いと、縦棒は l と読むしかない
  const int one_pct = std::atoi(arg_of(argc, argv, "--plain-one-pct", "0").c_str());
  const bool no_img = has_flag(argc, argv, "--no-images");   // 枠だけ作る（パリティ確認用）
  const bool photo_like = has_flag(argc, argv, "--photo-like");
  // 小学校の計算（× ÷ 小数点 帯分数 中括弧）を作るモード。**描く道が別**（木を経由しない）
  const bool arith_mode = has_flag(argc, argv, "--arith");
  if (dir.empty()) {
    printf("usage: mathcam dataset --out data/train --n 2000 [--seed 1] [--px-min 32]\n"
           "                       [--px-max 64] [--font path.ttf] [--font-italic path.ttf]\n"
           "                       [--italic-pct 50] [--minus2212-pct 50] [--prefix a]\n"
           "                       [--no-images]\n"
           "  書体を混ぜるには、フォントを変えて別の --seed --prefix で同じ dir に足す\n");
    return 1;
  }
  std::string why;
  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  if (!load_bits_if_asked(argc, argv, font)) return 1;
  const bool has_i = ital_pct > 0 && ts::load_font(font_i, fontip, nullptr, true);
  if (ital_pct > 0 && !has_i)
    printf("イタリックの書体が見つからないので立体だけで作る（--font-italic で渡す）\n");

  make_dir(dir + "/images");
  make_dir(dir + "/labels");
  FILE* ex = fopen((dir + "/exprs.txt").c_str(), "wb");
  // **クラス表は pure/classes.hpp だけ。** ここに写しを置いていたせいで、クラスを足しても
  // データセットのラベルからは落ちていた（× ÷ を描いた画像に、その枠が無いデータが 24,200 枚
  // できた。学習すれば「その字は無視しろ」と教えることになる）。
  const std::vector<std::string>& kClasses = cls::all();
  FILE* cf = fopen((dir + "/classes.txt").c_str(), "wb");
  for (const std::string& c : kClasses) fprintf(cf, "%s\n", c.c_str());
  fclose(cf);

  Rng rng(seed);
  int made = 0, skipped = 0, dropped = 0;
  for (int i = 0; i < n; ++i) {
    // 乱数を使う順番は**固定**する（1 つの式の中で 2 回呼ぶと C++ の評価順が不定になり、
    // Python 側と食い違う。この落とし穴は前に踏んで RESUME に書いてある）
    const std::string src = arith_mode ? gx::arith(rng) : gx::one(rng);
    const int px = (int)(px_min + (int)rng.below((uint64_t)(px_max - px_min + 1)));
    const bool use_ital = (int)rng.below(100) < ital_pct;
    const bool use_2212 = (int)rng.below(100) < minus_pct;
    const bool plain_one = (int)rng.below(100) < one_pct;
    // 紙と字の明るさ・ぼけ。写真は真っ黒と真っ白ではない（実測: 紙 225 / 字 60 前後）
    const int paper = photo_like ? (int)(215 + rng.below(41)) : 255;   // 215..255
    const int ink = photo_like ? (int)(20 + rng.below(71)) : 0;        // 20..90
    const int blur = photo_like ? (int)rng.below(2) : 0;
    // 写真に近づけるための劣化（**引く順番は Python 側と同じ**にする）。
    // 紙の明暗ムラ・粒子・JPEG のにじみは実写に必ずあるもので、これが無いと学習が
    // 「綺麗な絵」に合わせてしまう（実測: 学習が進むほど実写が悪くなった）。
    const int grad = photo_like ? (int)rng.below(26) : 0;        // 端から端で 0..25 の明暗差
    const int grad_dir = photo_like ? (int)rng.below(4) : 0;     // 左右・上下のどちら向きか
    const int noise = photo_like ? (int)rng.below(9) : 0;        // 粒子の振れ幅 0..8
    const uint64_t nseed = photo_like ? rng.next() : 0;          // 粒子の種
    const int jpeg_q = photo_like ? (int)(55 + rng.below(38)) : 0;   // 55..92
    const bool as_jpeg = photo_like && (int)rng.below(2) == 0;
    std::string err;
    ex::E e = ex::parse(src, &err);
    if (!err.empty()) { ++skipped; continue; }        // 生成器が壊れた式を出したら捨てる
    ts::Style st;
    st.italic_vars = use_ital && has_i;
    st.minus_cp = use_2212 ? 0x2212 : '-';
    st.plain_one = plain_one;
    st.paper = paper;
    st.ink = ink;
    st.blur = blur;
    ts::Rendered R =        // 紙のムラや粒子を足すので const にしない
        arith_mode ? ts::render_arith(font, st.italic_vars ? &font_i : nullptr, src, px, st)
                   : ts::render(font, st.italic_vars ? &font_i : nullptr, e, px, st);
    char stem[40];
    snprintf(stem, sizeof stem, "%s%06d", prefix.c_str(), made);
    if (!no_img) {
      // 紙の明暗ムラと粒子を足す（実写にはどちらもある）。ラベルは変わらない
      if (photo_like && (grad > 0 || noise > 0)) {
        Rng nr(nseed);
        for (int y = 0; y < R.h; ++y)
          for (int x = 0; x < R.w; ++x) {
            const int t = grad_dir == 0   ? x * grad / std::max(1, R.w)
                          : grad_dir == 1 ? (R.w - x) * grad / std::max(1, R.w)
                          : grad_dir == 2 ? y * grad / std::max(1, R.h)
                                          : (R.h - y) * grad / std::max(1, R.h);
            const int n = noise ? (int)nr.below((uint64_t)(noise * 2 + 1)) - noise : 0;
            int v = (int)R.gray[(size_t)y * R.w + x] - t + n;
            R.gray[(size_t)y * R.w + x] = (unsigned char)std::max(0, std::min(255, v));
          }
      }
      // **半分は JPEG で書く**（実写は必ず JPEG のにじみが乗っている）
      const std::string ip = dir + "/images/" + stem + (as_jpeg ? ".jpg" : ".png");
      const int okw = as_jpeg
                          ? stbi_write_jpg(ip.c_str(), R.w, R.h, 1, R.gray.data(), jpeg_q)
                          : stbi_write_png(ip.c_str(), R.w, R.h, 1, R.gray.data(), R.w);
      if (!okw) {
        printf("cannot write %s\n", ip.c_str());
        return 1;
      }
    }
    // YOLO 形式（クラス番号と、中心・幅・高さを 0..1 に正規化）
    FILE* lf = fopen((dir + "/labels/" + stem + ".txt").c_str(), "wb");
    for (size_t k = 0; k < R.cls.size(); ++k) {
      const int id = cls::id_of(R.cls[k]);
      // **落とした記号は数えて最後に出す。** 黙って落とすと「絵にはあるのにラベルが無い」
      // データができ、学習は「その字は無視しろ」を覚える（実際に 24,200 枚作ってしまった）
      if (id < 0) { ++dropped; continue; }
      const double x0 = R.box[k * 4], y0 = R.box[k * 4 + 1];
      const double x1 = R.box[k * 4 + 2], y1 = R.box[k * 4 + 3];
      fprintf(lf, "%d %.6f %.6f %.6f %.6f\n", id, (x0 + x1) / 2 / R.w, (y0 + y1) / 2 / R.h,
              (x1 - x0) / R.w, (y1 - y0) / R.h);
    }
    fclose(lf);
    if (ex) fprintf(ex, "%s%s%d%s%s\n", stem, "	", px, "	", src.c_str());
    ++made;
  }
  if (ex) fclose(ex);
  if (dropped)
    printf("**クラス表に無い記号を %d 個落とした**（classes.hpp に足すか、描き方を直す）\n",
           dropped);
  printf("%s に %d 件（捨てた式 %d 件、px %d..%d、font upem %d）\n", dir.c_str(), made,
         skipped, px_min, px_max, font.upem);
  return 0;
}

// mathcam genexpr — 学習用の式を乱数で出すだけ（Python 側と式列が一致するかの確認用）。
// --state を付けると各式のあとの乱数の内部状態も出す（ずれた場所を特定するため）。
static int cmd_genexpr(int argc, char** argv) {
  const int n = std::atoi(arg_of(argc, argv, "--n", "10").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1").c_str(), nullptr, 10);
  const bool st = has_flag(argc, argv, "--state");
  const bool arith_mode = has_flag(argc, argv, "--arith");
  Rng r(seed);
  for (int i = 0; i < n; ++i) {
    const std::string e = arith_mode ? gx::arith(r) : gx::one(r);
    if (st) printf("%llu\t%s\n", (unsigned long long)r.s, e.c_str());
    else printf("%s\n", e.c_str());
  }
  return 0;
}

// mathcam parse — 記号の枠の列（render --labels の出力形式）から式木に戻す。
static int cmd_parse(int argc, char** argv) {
  const std::string lp = arg_of(argc, argv, "--labels", "");
  if (lp.empty()) { printf("usage: mathcam parse --labels out.txt\n"); return 1; }
  FILE* f = fopen(lp.c_str(), "rb");
  if (!f) { printf("cannot read %s\n", lp.c_str()); return 1; }
  std::vector<pl::Sym> syms;
  char line[512];
  while (fgets(line, sizeof line, f)) {
    if (line[0] == '#' || line[0] == 0 || line[0] == 10) continue;
    char cls[64] = {0};
    int a = 0, b = 0, c = 0, d = 0;
    if (sscanf(line, "%63s %d %d %d %d", cls, &a, &b, &c, &d) == 5) {
      pl::Sym s;
      s.cls = cls; s.x0 = a; s.y0 = b; s.x1 = c; s.y1 = d;
      s.base_y = d;   // 単独の記号はベースライン ≒ 箱の下端
      syms.push_back(s);
    }
  }
  fclose(f);
  const pl::Result r = pl::parse(syms);
  if (!r.ok) { printf("parse failed: %s\n", r.why.c_str()); return 1; }
  printf("%s\n", r.text.c_str());
  // --steps を付けると、計算問題として 1 手ずつ計算する（検出器なしで手順を試せる）
  if (has_flag(argc, argv, "--steps")) {
    bool dec_ok = false;
    for (const pl::Sym& s : syms)
      if (s.cls == "dot") dec_ok = true;
    const pl::Result rr = pl::parse_raw(syms);
    if (rr.ok) {
      const ar::Result ares = ar::eval_steps(rr.e, dec_ok);
      for (size_t i = 0; i < ares.steps.size(); ++i)
        printf("%zu. [%s] %s\n   %s\n", i + 1, ares.steps[i].rule.c_str(),
               ares.steps[i].note.c_str(), ares.steps[i].after.c_str());
      if (ares.ok) printf("答え: %s\n", ar::to_text(ares.value, dec_ok).c_str());
    }
  }
  return 0;
}

// mathcam selftest — 組版 -> レイアウト解析 -> 元の式に戻るか。**検出器なしで測れる**ので、
// 解析器の正解率をここで詰めてから GPU に行く（検出器の誤りと解析器の誤りを混ぜないため）。
static int cmd_selftest(int argc, char** argv) {
  const int n = std::atoi(arg_of(argc, argv, "--n", "200").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1").c_str(), nullptr, 10);
  const int px = std::atoi(arg_of(argc, argv, "--px", "48").c_str());
  const std::string fontp = arg_of(argc, argv, "--font", "");
  const std::string fontip = arg_of(argc, argv, "--font-italic", "");
  const ts::Style st = style_of(argc, argv);
  const bool show = has_flag(argc, argv, "--show-fail");
  const bool arith_mode = has_flag(argc, argv, "--arith");
  std::string why;
  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  if (!load_bits_if_asked(argc, argv, font)) return 1;
  const bool has_i = st.italic_vars && ts::load_font(font_i, fontip, nullptr, true);

  Rng rng(seed);
  int ok = 0, bad = 0, skipped = 0, shown = 0;
  for (int i = 0; i < n; ++i) {
    const std::string src = arith_mode ? gx::arith(rng) : gx::one(rng);
    ex::E e = ex::parse(src, &why);
    if (!why.empty()) { ++skipped; continue; }
    // 分母が 0 になる式（生成器が y - y を作ることがある）は比べても意味がないので捨てる
    {
      bool degenerate = false;
      std::vector<ex::E> stack{e};
      while (!stack.empty()) {
        const ex::E t = stack.back();
        stack.pop_back();
        if (t->k == ex::Kind::Pow && ex::is_num(t->kids[0]) && t->kids[0]->num.is_zero() &&
            ex::is_num(t->kids[1]) && t->kids[1]->num.neg())
          degenerate = true;
        for (const ex::E& c : t->kids) stack.push_back(c);
      }
      if (degenerate) { ++skipped; continue; }
    }
    // --arith は「書かれたとおりに描く」道（÷ と帯分数は正規形で消えるので木を経由しない）
    const ts::Rendered R =
        arith_mode ? ts::render_arith(font, has_i ? &font_i : nullptr, src, px, st)
                   : ts::render(font, has_i ? &font_i : nullptr, e, px, st);
    std::vector<pl::Sym> syms;
    for (size_t k = 0; k < R.cls.size(); ++k) {
      pl::Sym s;
      s.cls = R.cls[k];
      s.x0 = R.box[k * 4]; s.y0 = R.box[k * 4 + 1];
      s.x1 = R.box[k * 4 + 2]; s.y1 = R.box[k * 4 + 3];
      s.base_y = s.y1;
      syms.push_back(s);
    }
    const pl::Result r = pl::parse(syms);
    // 比べるのは**正規形**（見た目が違っても同じ式なら正解）
    const bool same = r.ok && ex::equal(ex::expand(r.e), ex::expand(e));
    if (same) ++ok;
    else {
      ++bad;
      if (show && shown++ < 12)
        printf("  NG  %-32s -> %s\n", src.c_str(),
               r.ok ? r.text.c_str() : ("(" + r.why + ")").c_str());
    }
  }
  printf("組版 -> 解析: %d / %d 正解（%.1f%%）、捨てた式 %d\n", ok, ok + bad,
         (ok + bad) ? 100.0 * ok / (ok + bad) : 0.0, skipped);
  return 0;
}

// mathcam fontinfo — フォントの実寸を出す。組版がずれたときに「思っている値か」を確かめる用。
static int cmd_fontinfo(int argc, char** argv) {
  const std::string fontp = arg_of(argc, argv, "--font", "");
  std::string why;
  ts::Font f;
  if (!ts::load_font(f, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  printf("upem=%d ascent=%d descent=%d\n", f.upem, f.ascent, f.descent);
  const std::string dump = arg_of(argc, argv, "--layout", "");
  if (!dump.empty()) {
    std::string w2;
    ex::E e = ex::parse(dump, &w2);
    const ts::P pp = ts::present(e);
    const ts::Layout L = ts::lay(f, nullptr, pp, 1, 1);
    printf("row: w=%d asc=%d desc=%d  items=%zu\n", L.box.w, L.box.asc, L.box.desc,
           L.items.size());
    for (const ts::Item& it : L.items)
      printf("  cls=%-5s cp=%-5d x=%-6d y=%-6d bbox=(%d,%d,%d,%d) scale=%d/%d\n",
             it.cls.c_str(), it.cp, it.x, it.y, it.x0, it.y0, it.x1, it.y1, it.scale_num,
             it.scale_den);
    return 0;
  }
  // **書体に字が無いと、絵は空白でラベルだけ正しいデータができる**（学習を静かに壊す）。
  // 学習データを作る前に、要る字が全部あるかを見る。advance と枠が両方 0 なら無いと判断する。
  const std::string fontip = arg_of(argc, argv, "--font-italic", "");
  ts::Font fi;
  const bool has_i = ts::load_font(fi, fontip, nullptr, true);
  static const int kNeedRoman[] = {'0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                                   '+', '-', '=', '(', ')', 0x221A, 0x2212};
  static const int kNeedItalic[] = {'x', 'y', 't', 'a', 'b', 'c', 'n',
                                    's', 'i', 'o', 'l', 'e', 'g', 'p', 'q', 'r'};
  int missing = 0;
  auto check = [&](const ts::Font& fo, const char* label, const int* cps, size_t n) {
    printf("%s (upem %d):", label, fo.upem);
    for (size_t i = 0; i < n; ++i) {
      int x0, y0, x1, y1;
      fo.bbox(cps[i], &x0, &y0, &x1, &y1);
      const bool have = fo.advance(cps[i]) != 0 || x1 != x0 || y1 != y0;
      if (!have) { printf(" [欠 U+%04X]", cps[i]); ++missing; }
    }
    printf(" %s\n", missing ? "" : "全部ある");
  };
  check(f, "立体", kNeedRoman, sizeof kNeedRoman / sizeof kNeedRoman[0]);
  if (has_i) check(fi, "イタリック", kNeedItalic, sizeof kNeedItalic / sizeof kNeedItalic[0]);
  else printf("イタリック: 読めなかった（--font-italic で渡す）\n");
  const char* cs = "72x+";
  for (const char* c = cs; *c; ++c) {
    int x0, y0, x1, y1;
    f.bbox(*c, &x0, &y0, &x1, &y1);
    printf("%c advance=%d bbox=(%d,%d,%d,%d)\n", *c, f.advance(*c), x0, y0, x1, y1);
  }
  if (missing) { printf("**この書体は学習データに使えない**（%d 字欠け）\n", missing); return 1; }
  return 0;
}

// mathcam photo — **端から端まで**。画像 -> 記号検出（自作ランタイム）-> レイアウト解析 ->
// 式木 -> solve -> 手順。推論ライブラリは使わない（pure/onnx_run.hpp）。
// mathcam e2e — 端から端までの正解率。式を作る -> 組版 -> **検出** -> 解析 -> 元の式と比べる。
// selftest（組版 -> 解析）との差が、検出器のぶんの損失になる。
// 端から端まで（組版 -> 検出 -> レイアウト解析 -> 式）の正解率。学習中の検証にも使う。
// **同じ種で同じ式を作る**ので、step が進んでも比べているものは変わらない。
static double e2e_rate(const onx::Graph& g, const ts::Font& font, const ts::Font* font_i,
                       const ts::Style& st, int n, uint64_t seed, int px_min, int px_max,
                       int imgsz, float conf) {
  Rng rng(seed);
  int ok = 0, tried = 0;
  std::string why;
  for (int i = 0; i < n; ++i) {
    const std::string src = gx::one(rng);
    const int px = px_min + (int)rng.below((uint64_t)(px_max - px_min + 1));
    const ex::E e = ex::parse(src, &why);
    if (!why.empty()) { why.clear(); continue; }
    const ts::Rendered R = ts::render(font, font_i, e, px, st);
    std::vector<unsigned char> rgb((size_t)R.w * R.h * 3);
    for (size_t k = 0; k < (size_t)R.w * R.h; ++k)
      rgb[k * 3] = rgb[k * 3 + 1] = rgb[k * 3 + 2] = R.gray[k];
    const pipeln::Detected d =
        pipeln::detect_syms(g, rgb.data(), R.w, R.h, imgsz, conf, 0.45f, BoxFmt::CXCYWH);
    const pl::Result r = pl::parse(d.syms);
    ++tried;
    if (r.ok && ex::equal(ex::expand(r.e), ex::expand(e))) ++ok;
  }
  return tried ? (double)ok / tried : 0.0;
}

static int cmd_e2e(int argc, char** argv) {
  const int n = std::atoi(arg_of(argc, argv, "--n", "50").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1").c_str(), nullptr, 10);
  const int px_min = std::atoi(arg_of(argc, argv, "--px-min", "28").c_str());
  const int px_max = std::atoi(arg_of(argc, argv, "--px-max", "72").c_str());
  const std::string model_p = arg_of(argc, argv, "--model", "models/sym_det_v5.onnx");
  const std::string fontp = arg_of(argc, argv, "--font", "");
  const int imgsz = std::atoi(arg_of(argc, argv, "--imgsz", "640").c_str());
  const float conf = (float)atof(arg_of(argc, argv, "--conf", "0.20").c_str());
  const bool show = has_flag(argc, argv, "--show-fail");
  const std::string fontip = arg_of(argc, argv, "--font-italic", "");
  const ts::Style st = style_of(argc, argv);
  std::string why;
  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  if (!load_bits_if_asked(argc, argv, font)) return 1;
  const bool has_i = st.italic_vars && ts::load_font(font_i, fontip, nullptr, true);
  const bool arith_mode = has_flag(argc, argv, "--arith");   // 小学校の計算で測る
  onx::Graph g = onx::load_onnx(model_p);
  if (g.nodes.empty()) { printf("cannot read %s\n", model_p.c_str()); return 1; }

  Rng rng(seed);
  int ok = 0, bad = 0, shown = 0, skipped = 0;
  for (int i = 0; i < n; ++i) {
    const std::string src = arith_mode ? gx::arith(rng) : gx::one(rng);
    const int px = px_min + (int)rng.below((uint64_t)(px_max - px_min + 1));
    ex::E e = ex::parse(src, &why);
    if (!why.empty()) { ++skipped; continue; }
    const ts::Rendered R =
        arith_mode ? ts::render_arith(font, has_i ? &font_i : nullptr, src, px, st)
                   : ts::render(font, has_i ? &font_i : nullptr, e, px, st);
    // 灰色 1ch を RGB に広げる（検出器は 3ch を期待する）
    std::vector<unsigned char> rgb((size_t)R.w * R.h * 3);
    for (size_t k = 0; k < (size_t)R.w * R.h; ++k) {
      rgb[k * 3] = rgb[k * 3 + 1] = rgb[k * 3 + 2] = R.gray[k];
    }
    const pipeln::Detected d = pipeln::detect_syms(g, rgb.data(), R.w, R.h, imgsz, conf, 0.45f, BoxFmt::CXCYWH);
    const pl::Result r = pl::parse(d.syms);
    const bool same = r.ok && ex::equal(ex::expand(r.e), ex::expand(e));
    if (same) ++ok;
    else {
      ++bad;
      if (show && shown++ < 12)
        printf("  NG  px=%-3d %-30s -> %s\n", px, src.c_str(),
               r.ok ? r.text.c_str() : ("(" + r.why + ")").c_str());
    }
  }
  printf("端から端まで: %d / %d 正解（%.1f%%）、捨てた式 %d\n", ok, ok + bad,
         (ok + bad) ? 100.0 * ok / (ok + bad) : 0.0, skipped);
  return 0;
}

// mathcam rgba — 画像を生の RGBA で吐く。WASM のテスト（wasm/test_node.js）が
// **ブラウザと同じ画素**を渡せるようにするため。
static int cmd_rgba(int argc, char** argv) {
  const std::string img = arg_of(argc, argv, "--img", "");
  const std::string out = arg_of(argc, argv, "--out", "");
  if (img.empty() || out.empty()) {
    printf("usage: mathcam rgba --img <file> --out <file.rgba>\n");
    return 1;
  }
  int w = 0, h = 0, ch = 0;
  unsigned char* px = stbi_load(img.c_str(), &w, &h, &ch, 4);
  if (!px) { printf("cannot read %s\n", img.c_str()); return 1; }
  FILE* f = fopen(out.c_str(), "wb");
  if (!f) { stbi_image_free(px); printf("cannot write %s\n", out.c_str()); return 1; }
  fwrite(px, 1, (size_t)w * h * 4, f);
  fclose(f);
  printf("wrote %s (%dx%d RGBA)\n", out.c_str(), w, h);
  stbi_image_free(px);
  return 0;
}

static int cmd_photo(int argc, char** argv) {
  const std::string img_p = arg_of(argc, argv, "--img", "");
  const std::string model_p = arg_of(argc, argv, "--model", "models/sym_det_v5.onnx");
  const int imgsz = std::atoi(arg_of(argc, argv, "--imgsz", "640").c_str());
  const float conf = (float)atof(arg_of(argc, argv, "--conf", "0.20").c_str());
  const float nms = (float)atof(arg_of(argc, argv, "--nms", "0.45").c_str());
  const bool steps = has_flag(argc, argv, "--steps");
  const bool show_syms = has_flag(argc, argv, "--show-syms");
  // 箱の形は export 依存。Ultralytics の素の export は cxcywh（姉妹リポの記録）
  const BoxFmt fmt = arg_of(argc, argv, "--fmt", "cxcywh") == "xyxy" ? BoxFmt::XYXY
                                                                    : BoxFmt::CXCYWH;
  // 実写のページには式が何本も載っている。1 本を切り出して渡せるようにする
  // （デモでも「読みたい式を囲む」操作が要る。ページ全体を 640 に縮めると字が潰れる）。
  const std::string crop = arg_of(argc, argv, "--crop", "");
  const std::string save_crop = arg_of(argc, argv, "--save-crop", "");
  if (img_p.empty()) {
    printf("usage: mathcam photo --img x.png [--model models/sym_det_v5.onnx] [--steps]\n"
           "                     [--crop x0,y0,x1,y1] [--save-crop crop.png] [--conf 0.20]\n");
    return 1;
  }
  int w = 0, h = 0, ch = 0;
  unsigned char* px = stbi_load(img_p.c_str(), &w, &h, &ch, 3);
  if (!px) { printf("cannot read %s\n", img_p.c_str()); return 1; }
  std::vector<unsigned char> cropped;
  if (!crop.empty()) {
    int x0 = 0, y0 = 0, x1 = w, y1 = h;
    if (sscanf(crop.c_str(), "%d,%d,%d,%d", &x0, &y0, &x1, &y1) != 4) {
      printf("--crop は x0,y0,x1,y1 の形で渡す\n");
      stbi_image_free(px);
      return 1;
    }
    x0 = std::max(0, std::min(x0, w - 1));
    y0 = std::max(0, std::min(y0, h - 1));
    x1 = std::max(x0 + 1, std::min(x1, w));
    y1 = std::max(y0 + 1, std::min(y1, h));
    const int cw = x1 - x0, cah = y1 - y0;
    cropped.resize((size_t)cw * cah * 3);
    for (int y = 0; y < cah; ++y)
      memcpy(&cropped[(size_t)y * cw * 3], px + ((size_t)(y + y0) * w + x0) * 3,
             (size_t)cw * 3);
    stbi_image_free(px);
    px = cropped.data();
    w = cw;
    h = cah;
    printf("切り出し: %dx%d\n", w, h);
    if (!save_crop.empty()) stbi_write_png(save_crop.c_str(), w, h, 3, px, w * 3);
  } else {
    // **画素はこの関数の終わりまで生かす。** 検出の直後に解放していたので、そのあとで
    // 画素を読む --show-bands / --auto-lines が解放済みを触っていた（出力が 1 行も出ず、
    // 終了コードだけ 0 に見える壊れ方。--crop を付けたときだけ動くので気付きにくい）。
    cropped.assign(px, px + (size_t)w * h * 3);
    stbi_image_free(px);
    px = cropped.data();
  }
  // 試して**やめた**こと: 推論の前にコントラストを伸ばして白紙・黒字に寄せる。
  // 実写の紙 225 / 字 60 は学習データの範囲（紙 215..255 / 字 20..90）に既に入っていて、
  // 伸ばすと紙の地合いが字に変わるだけだった（実測: 9 記号のはずが 62 記号検出された）。
  onx::Graph g = onx::load_onnx(model_p);
  if (g.nodes.empty()) {
    printf("cannot read %s\n", model_p.c_str());
    return 1;
  }
  // e2e と WASM と同じ 1 本を通す（pure/pipeline.hpp）
  const pipeln::Detected det = pipeln::detect_syms(g, px, w, h, imgsz, conf, nms, fmt);
  const std::vector<pl::Sym>& syms = det.syms;
  printf("%zu 記号を検出\n", syms.size());
  if (show_syms) {
    std::vector<pl::Sym> sorted = syms;
    std::sort(sorted.begin(), sorted.end(), pl::by_x);
    for (const pl::Sym& sm : sorted)
      printf("  %-5s (%d,%d)-(%d,%d)\n", sm.cls.c_str(), sm.x0, sm.y0, sm.x1, sm.y1);
  }
  // 1 式ずつ解いて出す。--lines を付けると囲んだ範囲の**行を全部**読む
  // （教科書のページは 1 問ずつ切るのが面倒なので）
  // 計算問題（方程式でない）のときは、小学校の順序で 1 手ずつ計算して見せる。
  // **畳まない木で読み直す**のが要点（畳んだ木からは「どこを先に計算したか」が消える）。
  // 小数で書くかどうかは、小数点の字が検出されたかで決める。
  auto arith_of = [&](const std::vector<pl::Sym>& sy, bool& dec_ok) {
    dec_ok = false;
    for (const pl::Sym& s : sy)
      if (s.cls == "dot") dec_ok = true;
    const pl::Result rr = pl::parse_raw(sy);
    if (!rr.ok) return ar::Result();
    return ar::eval_steps(rr.e, dec_ok);
  };
  auto show_one = [&](const pl::Result& r, const char* prefix,
                      const std::vector<pl::Sym>* sy) {
    if (!r.ok) { printf("%sレイアウト解析に失敗: %s\n", prefix, r.why.c_str()); return; }
    // **計算問題は「書かれたとおり」を見せる**。畳んだ木を印字すると 1.8 × 3.5 - … が
    // 「261/10」（＝答えの数）になり、読めた式の欄に答えが出ているように見える
    std::string shown = r.text;
    std::vector<std::string> vs0;
    ex::collect_syms(r.e, vs0);
    if (sy && vs0.empty() && r.e->k != ex::Kind::Rel && r.e->k != ex::Kind::Sys) {
      bool dec2 = false;
      for (const pl::Sym& s2 : *sy)
        if (s2.cls == "dot") dec2 = true;
      const pl::Result rr2 = pl::parse_raw(*sy);
      if (rr2.ok) shown = ar::to_text(rr2.e, dec2);
    }
    printf("%s読めた式: %s\n", prefix, shown.c_str());
    slv::Solution sol = slv::solve(r.e);
    // **数だけの等式は計算問題として扱う**（プリントの「… = □」。四角が別の字として拾われて
    // `= 0` に見えることがあり、そのまま解くと「解なし（矛盾）」になってしまう）
    if (sol.ok && (sol.kind == "contradiction" || sol.kind == "identity") &&
        r.e->k == ex::Kind::Rel) {
      std::vector<std::string> sy2;
      ex::collect_syms(r.e, sy2);
      if (sy2.empty()) sol.ok = false;
    }
    if (!sol.ok) {
      // 方程式でなければ、計算問題として 1 手ずつ計算する
      bool dec_ok = false;
      const ar::Result ares = sy ? arith_of(*sy, dec_ok) : ar::Result();
      if (ares.ok && steps)
        for (size_t i = 0; i < ares.steps.size(); ++i)
          printf("%s%zu. [%s] %s\n%s   %s\n", prefix, i + 1, ares.steps[i].rule.c_str(),
                 ares.steps[i].note.c_str(), prefix, ares.steps[i].after.c_str());
      printf("%s答え: %s\n", prefix,
             ares.ok ? ar::to_text(ares.value, dec_ok).c_str()
                     : ex::to_infix(ex::expand(ar::calc_side(r.e))).c_str());
      // **文字が混ざる式は「因数分解せよ」のことが多い**（高校でいちばん多い問い方）。
      // 分けられたときだけ足す（分けられないなら黙る）
      if (!vs0.empty()) {
        const fac::Result fr = fac::factor(r.e);
        if (fr.ok && fr.changed)
          printf("%s因数分解: %s\n", prefix, ex::to_infix(fr.value).c_str());
      }
      return;
    }
    if (steps)
      for (size_t i = 0; i < sol.steps.size(); ++i)
        printf("%s%zu. [%s] %s\n%s   %s\n", prefix, i + 1, sol.steps[i].rule.c_str(),
               sol.steps[i].note.c_str(), prefix,
               ex::to_infix(sol.steps[i].after).c_str());
    for (const std::string& line : slv::answer_lines(sol)) printf("%s%s\n", prefix, line.c_str());
  };

  if (has_flag(argc, argv, "--show-bands")) {
    const std::vector<std::pair<int, int>> bs = pipeln::ink_bands(px, w, h, 4);
    printf("%zu 帯\n", bs.size());
    for (size_t i = 0; i < bs.size(); ++i)
      printf("  %zu: y %d..%d（高さ %d）\n", i + 1, bs[i].first, bs[i].second,
             bs[i].second - bs[i].first);
  }
  if (has_flag(argc, argv, "--auto-cells")) {
    // **2 段で読む**（行の帯で位置を取り、塊ごとに元画像から読み直す）。ページや欄を
    // まるごと渡しても 1 問ずつの精度が出るのが狙い
    // 塊を切る隙間の下限（帯の高さに対する %）。教科書の「(1)」と式の間隔で決まる
    const int gap_pct = std::atoi(arg_of(argc, argv, "--cell-gap", "35").c_str());
    const int merge_pct = std::atoi(arg_of(argc, argv, "--band-merge", "25").c_str());
    const std::vector<pipeln::Cell> cs =
        pipeln::detect_by_cells(g, px, w, h, imgsz, conf, nms, fmt, gap_pct, merge_pct);
    printf("%zu 塊（2 段で検出）\n", cs.size());
    for (const pipeln::Cell& c0 : cs)
     // 読めない塊は横の隙間で割って読み直す（答え欄の四角が問題の隙間を埋めるため）
     for (const pl::Piece& c : pl::parse_or_split(c0.syms)) {
      const pl::Result cr = c.r;
      // 問題番号（「(1)」など）は出さない。**記号の数でも縛る**（小学校の計算は値が数に
      // なるので、「数になったら番号」とだけ書くと式そのものが消える。実測: s6.png が消えた）
      if (cr.ok && ex::is_num(cr.e) && c.syms.size() <= 4) continue;
      if (!cr.ok && c.syms.size() < 3) continue;
      printf("--- (%d,%d)-(%d,%d)  %zu 記号 ---\n", c.x0, c.y0, c.x1, c.y1, c.syms.size());
      if (show_syms) {
        std::vector<pl::Sym> sorted2 = c.syms;
        std::sort(sorted2.begin(), sorted2.end(), pl::by_x);
        for (const pl::Sym& sm : sorted2)
          printf("  %-5s (%d,%d)-(%d,%d)\n", sm.cls.c_str(), sm.x0, sm.y0, sm.x1, sm.y1);
      }
      show_one(cr, "  ", &c.syms);
    }
    return 0;
  }
  if (has_flag(argc, argv, "--auto-lines")) {
    // **インクの射影で行に切ってから、行ごとに検出する**（広く囲んでも字が縮まない）
    const std::vector<std::vector<pl::Sym>> ls =
        pipeln::detect_by_lines(g, px, w, h, imgsz, conf, nms, fmt);
    printf("%zu 行（行ごとに検出）\n", ls.size());
    for (size_t i = 0; i < ls.size(); ++i) {
      // **1 行の中を横の隙間で区切る。** 教科書の 1 行には問題番号と 2 問が並ぶので、
      // まとめて 1 式として読ませても壊れるだけ（実測: 「演算子の両側が空です」）
      const std::vector<std::vector<pl::Sym>> cells = pl::split_cells(ls[i]);
      printf("--- %zu 行目（%zu 記号、%zu 塊）---\n", i + 1, ls[i].size(), cells.size());
      for (const std::vector<pl::Sym>& cell : cells) {
        const pl::Result cr = pl::parse(cell);
        // 問題番号（「(1)」など、ただの数になる塊）は出さない
        if (cr.ok && ex::is_num(cr.e)) continue;
        if (!cr.ok && cell.size() < 3) continue;
        if (show_syms) {
          std::vector<pl::Sym> sorted2 = cell;
          std::sort(sorted2.begin(), sorted2.end(), pl::by_x);
          for (const pl::Sym& sm : sorted2)
            printf("  %-5s (%d,%d)-(%d,%d)\n", sm.cls.c_str(), sm.x0, sm.y0, sm.x1, sm.y1);
        }
        show_one(cr, "  ", &cell);
      }
    }
    return 0;
  }
  if (has_flag(argc, argv, "--lines")) {
    const std::vector<pl::Result> rs = pl::parse_lines(syms);
    printf("%zu 行\n", rs.size());
    for (size_t i = 0; i < rs.size(); ++i) {
      printf("--- %zu 行目 ---\n", i + 1);
      show_one(rs[i], "", nullptr);
    }
    return 0;
  }
  const pl::Result r = pl::parse(syms);
  if (!r.ok) { printf("レイアウト解析に失敗: %s\n", r.why.c_str()); return 1; }
  show_one(r, "", &syms);
  return 0;
}


// mathcam rawdump — 畳まない木を見る（小学校の手順が出ないときの原因調べ）
static void dump_raw(const ex::E& e, int depth) {
  std::string pad(depth * 2, ' ');
  const char* kind = e->k == ex::Kind::Num ? "Num"
                     : e->k == ex::Kind::Sym ? "Sym"
                     : e->k == ex::Kind::Add ? "Add"
                     : e->k == ex::Kind::Mul ? "Mul"
                     : e->k == ex::Kind::Pow ? "Pow"
                     : e->k == ex::Kind::Fn  ? "Fn"
                     : e->k == ex::Kind::Rel ? "Rel" : "Sys";
  printf("%s%s %s %s\n", pad.c_str(), kind, e->name.c_str(),
         e->k == ex::Kind::Num ? e->num.str().c_str() : "");
  for (const ex::E& c : e->kids) dump_raw(c, depth + 1);
}

static int cmd_rawdump(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  std::string why;
  const ex::E e = ex::parse_raw(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }
  dump_raw(e, 0);
  printf("text: %s\n", ar::to_text(e).c_str());
  const ar::Result r = ar::eval_steps(e);
  printf("ok=%d steps=%zu value=%s\n", (int)r.ok, r.steps.size(),
         r.value ? ar::to_text(r.value).c_str() : "(none)");
  return 0;
}

int main(int argc, char** argv) {
#ifdef _WIN32
  SetConsoleOutputCP(CP_UTF8);
  // **CRT も UTF-8 にする。** argv を UTF-8 に直すだけだと、日本語の入ったパスを
  // fopen に渡したときに開けなくなる（実測: 一時ディレクトリに日本語が入っていて書けなかった）。
  setlocale(LC_ALL, ".UTF8");
  // **Windows の argv は ANSI（ここでは cp932）で届く。** UTF-8 に直してから使う。
  // 直さないと `--expr "3.7 × 2"` の × が UTF-8 として読めず「余分な文字」になる
  // （実測。パーサは UTF-8 のバイト列を見ている）。
  std::vector<std::string> utf8_args;
  std::vector<char*> utf8_argv;
  {
    int wargc = 0;
    LPWSTR* wargv = CommandLineToArgvW(GetCommandLineW(), &wargc);
    if (wargv && wargc == argc) {
      for (int i = 0; i < wargc; ++i) {
        const int n = WideCharToMultiByte(CP_UTF8, 0, wargv[i], -1, nullptr, 0, nullptr, nullptr);
        std::string s((size_t)(n > 0 ? n - 1 : 0), 0);
        if (n > 1) WideCharToMultiByte(CP_UTF8, 0, wargv[i], -1, &s[0], n, nullptr, nullptr);
        utf8_args.push_back(s);
      }
      for (std::string& s : utf8_args) utf8_argv.push_back(&s[0]);
      argv = utf8_argv.data();
    }
    if (wargv) LocalFree(wargv);
  }
#endif
  if (argc < 2) {
    printf("usage: mathcam <eval|solve|diff|integ|sum|seq|factor|curve|limit|area|trig|recur|apart|circle|vec|train-det|build-det|render|dataset|parse|selftest|photo> ...\n");
    return 1;
  }
  const std::string cmd = argv[1];
  if (cmd == "eval") return cmd_eval(argc, argv);
  if (cmd == "rawdump") return cmd_rawdump(argc, argv);
  if (cmd == "solve") return cmd_solve(argc, argv);
  if (cmd == "diff") return cmd_calc(argc, argv, false);
  if (cmd == "integ") return cmd_calc(argc, argv, true);
  if (cmd == "sum") return cmd_sum(argc, argv);
  if (cmd == "seq") return cmd_seq(argc, argv);
  if (cmd == "factor") return cmd_factor(argc, argv);
  if (cmd == "curve") return cmd_curve(argc, argv);
  if (cmd == "limit") return cmd_limit(argc, argv);
  if (cmd == "area") return cmd_area(argc, argv);
  if (cmd == "trig") return cmd_trig(argc, argv);
  if (cmd == "recur") return cmd_recur(argc, argv);
  if (cmd == "apart") return cmd_apart(argc, argv);
  if (cmd == "circle") return cmd_circle(argc, argv);
  if (cmd == "vec") return cmd_vec(argc, argv);
  if (cmd == "train-det") return cmd_train_det(argc, argv);
  if (cmd == "build-det") return cmd_build_det(argc, argv);
  if (cmd == "render") return cmd_render(argc, argv);
  if (cmd == "dataset") return cmd_dataset(argc, argv);
  if (cmd == "genexpr") return cmd_genexpr(argc, argv);
  if (cmd == "parse") return cmd_parse(argc, argv);
  if (cmd == "selftest") return cmd_selftest(argc, argv);
  if (cmd == "fontinfo") return cmd_fontinfo(argc, argv);
  if (cmd == "fontdump") return cmd_fontdump(argc, argv);
  if (cmd == "photo") return cmd_photo(argc, argv);
  if (cmd == "rgba") return cmd_rgba(argc, argv);
  if (cmd == "e2e") return cmd_e2e(argc, argv);
  printf("mathcam: '%s' is not implemented yet\n", cmd.c_str());
  return 1;
}
