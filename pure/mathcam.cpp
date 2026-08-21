// mathcam — このプロジェクトの CLI（C++ 側）。tools/ の Python 側と 1 対 1 に対応させる。
//
//   mathcam eval  --expr "2/3 + 1/6"          式を読んで正規形と答えを出す
//   mathcam solve --expr "x^2 - 5x + 6 = 0" [--steps] [--latex]  解く（手順つき）
//   mathcam render --expr "1/2 x + sqrt(2) = 0" --out out.png [--labels out.txt] [--px 48]
//   mathcam dataset --out data/train --n 2000 [--seed 1] [--px-min 32 --px-max 64]
//   mathcam parse   --labels out.txt        枠の列から式木に戻す（レイアウト解析）
//   mathcam selftest --n 500                組版 -> 解析 -> 元の式に戻るかを測る
//   mathcam photo --img x.png --model models/sym_det.onnx [--steps]   写真 1 枚を端から端まで
//
// build: sh build/cc.sh pure/mathcam.cpp -o mathcam.exe
//        sh build/gcc.sh pure/mathcam.cpp -o mathcam.exe
#define STB_IMAGE_IMPLEMENTATION
#define STB_TRUETYPE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
#include "expr.hpp"
#include "solve.hpp"
#include "typeset_impl.hpp"
#include "gen_expr.hpp"
#include "parse_layout.hpp"
#include "classes.hpp"
#include "pipeline.hpp"
#include "stb_image.h"
#include <cstdio>
#include <cstring>
#include <string>
#ifdef _WIN32
#include <windows.h>
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
  if (!s.ok) { printf("solve: %s\n", s.why.c_str()); return 1; }
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
  ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }

  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  const bool has_i = st.italic_vars && ts::load_font(font_i, fontip, nullptr, true);
  const ts::Rendered R = ts::render(font, has_i ? &font_i : nullptr, e, px, st);
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
  const bool no_img = has_flag(argc, argv, "--no-images");   // 枠だけ作る（パリティ確認用）
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
  const bool has_i = ital_pct > 0 && ts::load_font(font_i, fontip, nullptr, true);
  if (ital_pct > 0 && !has_i)
    printf("イタリックの書体が見つからないので立体だけで作る（--font-italic で渡す）\n");

  make_dir(dir + "/images");
  make_dir(dir + "/labels");
  FILE* ex = fopen((dir + "/exprs.txt").c_str(), "wb");
  // クラスの並びは固定しておく（学習と推論で番号がずれないように）
  static const char* kClasses[] = {"0","1","2","3","4","5","6","7","8","9",
                                   "+","-","=","(",")","sqrt","frac",
                                   "x","y","t","a","b","c","n",
                                   "s","i","o","l","e","g","p","q","r","t2"};
  FILE* cf = fopen((dir + "/classes.txt").c_str(), "wb");
  for (const char* c : kClasses) fprintf(cf, "%s\n", c);
  fclose(cf);

  Rng rng(seed);
  int made = 0, skipped = 0;
  for (int i = 0; i < n; ++i) {
    // 乱数を使う順番は**固定**する（1 つの式の中で 2 回呼ぶと C++ の評価順が不定になり、
    // Python 側と食い違う。この落とし穴は前に踏んで RESUME に書いてある）
    const std::string src = gx::one(rng);
    const int px = (int)(px_min + (int)rng.below((uint64_t)(px_max - px_min + 1)));
    const bool use_ital = (int)rng.below(100) < ital_pct;
    const bool use_2212 = (int)rng.below(100) < minus_pct;
    std::string err;
    ex::E e = ex::parse(src, &err);
    if (!err.empty()) { ++skipped; continue; }        // 生成器が壊れた式を出したら捨てる
    ts::Style st;
    st.italic_vars = use_ital && has_i;
    st.minus_cp = use_2212 ? 0x2212 : '-';
    const ts::Rendered R = ts::render(font, st.italic_vars ? &font_i : nullptr, e, px, st);
    char stem[40];
    snprintf(stem, sizeof stem, "%s%06d", prefix.c_str(), made);
    if (!no_img) {
      const std::string ip = dir + "/images/" + stem + ".png";
      if (!stbi_write_png(ip.c_str(), R.w, R.h, 1, R.gray.data(), R.w)) {
        printf("cannot write %s\n", ip.c_str());
        return 1;
      }
    }
    // YOLO 形式（クラス番号と、中心・幅・高さを 0..1 に正規化）
    FILE* lf = fopen((dir + "/labels/" + stem + ".txt").c_str(), "wb");
    for (size_t k = 0; k < R.cls.size(); ++k) {
      int id = -1;
      for (int c = 0; c < (int)(sizeof kClasses / sizeof kClasses[0]); ++c)
        if (R.cls[k] == kClasses[c]) { id = c; break; }
      if (id < 0) continue;                            // クラス表に無い記号は落とす
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
  Rng r(seed);
  for (int i = 0; i < n; ++i) {
    const std::string e = gx::one(r);
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
  std::string why;
  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  const bool has_i = st.italic_vars && ts::load_font(font_i, fontip, nullptr, true);

  Rng rng(seed);
  int ok = 0, bad = 0, skipped = 0, shown = 0;
  for (int i = 0; i < n; ++i) {
    const std::string src = gx::one(rng);
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
    const ts::Rendered R = ts::render(font, has_i ? &font_i : nullptr, e, px, st);
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
static int cmd_e2e(int argc, char** argv) {
  const int n = std::atoi(arg_of(argc, argv, "--n", "50").c_str());
  const uint64_t seed = strtoull(arg_of(argc, argv, "--seed", "1").c_str(), nullptr, 10);
  const int px_min = std::atoi(arg_of(argc, argv, "--px-min", "28").c_str());
  const int px_max = std::atoi(arg_of(argc, argv, "--px-max", "72").c_str());
  const std::string model_p = arg_of(argc, argv, "--model", "models/sym_det.onnx");
  const std::string fontp = arg_of(argc, argv, "--font", "");
  const int imgsz = std::atoi(arg_of(argc, argv, "--imgsz", "640").c_str());
  const float conf = (float)atof(arg_of(argc, argv, "--conf", "0.25").c_str());
  const bool show = has_flag(argc, argv, "--show-fail");
  const std::string fontip = arg_of(argc, argv, "--font-italic", "");
  const ts::Style st = style_of(argc, argv);
  std::string why;
  ts::Font font, font_i;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  const bool has_i = st.italic_vars && ts::load_font(font_i, fontip, nullptr, true);
  onx::Graph g = onx::load_onnx(model_p);
  if (g.nodes.empty()) { printf("cannot read %s\n", model_p.c_str()); return 1; }

  Rng rng(seed);
  int ok = 0, bad = 0, shown = 0, skipped = 0;
  for (int i = 0; i < n; ++i) {
    const std::string src = gx::one(rng);
    const int px = px_min + (int)rng.below((uint64_t)(px_max - px_min + 1));
    ex::E e = ex::parse(src, &why);
    if (!why.empty()) { ++skipped; continue; }
    const ts::Rendered R = ts::render(font, has_i ? &font_i : nullptr, e, px, st);
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
  const std::string model_p = arg_of(argc, argv, "--model", "models/sym_det.onnx");
  const int imgsz = std::atoi(arg_of(argc, argv, "--imgsz", "640").c_str());
  const float conf = (float)atof(arg_of(argc, argv, "--conf", "0.25").c_str());
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
    printf("usage: mathcam photo --img x.png [--model models/sym_det.onnx] [--steps]\n"
           "                     [--crop x0,y0,x1,y1] [--save-crop crop.png] [--conf 0.25]\n");
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
  }
  onx::Graph g = onx::load_onnx(model_p);
  if (g.nodes.empty()) { printf("cannot read %s\n", model_p.c_str()); stbi_image_free(px); return 1; }
  // e2e と WASM と同じ 1 本を通す（pure/pipeline.hpp）
  const pipeln::Detected det = pipeln::detect_syms(g, px, w, h, imgsz, conf, nms, fmt);
  if (cropped.empty()) stbi_image_free(px);      // 切り出し時は cropped の持ち物なので触らない
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
  auto show_one = [&](const pl::Result& r, const char* prefix) {
    if (!r.ok) { printf("%sレイアウト解析に失敗: %s\n", prefix, r.why.c_str()); return; }
    printf("%s読めた式: %s\n", prefix, r.text.c_str());
    const slv::Solution sol = slv::solve(r.e);
    if (!sol.ok) {
      // 方程式でなければ、値を計算して出す（計算問題として扱う）
      printf("%s答え: %s\n", prefix, ex::to_infix(ex::expand(r.e)).c_str());
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
  if (has_flag(argc, argv, "--auto-lines")) {
    // **インクの射影で行に切ってから、行ごとに検出する**（広く囲んでも字が縮まない）
    const std::vector<std::vector<pl::Sym>> ls =
        pipeln::detect_by_lines(g, px, w, h, imgsz, conf, nms, fmt);
    printf("%zu 行（行ごとに検出）\n", ls.size());
    for (size_t i = 0; i < ls.size(); ++i) {
      printf("--- %zu 行目（%zu 記号）---\n", i + 1, ls[i].size());
      if (show_syms) {
        std::vector<pl::Sym> sorted2 = ls[i];
        std::sort(sorted2.begin(), sorted2.end(), pl::by_x);
        for (const pl::Sym& sm : sorted2)
          printf("  %-5s (%d,%d)-(%d,%d)\n", sm.cls.c_str(), sm.x0, sm.y0, sm.x1, sm.y1);
      }
      show_one(pl::parse(ls[i]), "");
    }
    return 0;
  }
  if (has_flag(argc, argv, "--lines")) {
    const std::vector<pl::Result> rs = pl::parse_lines(syms);
    printf("%zu 行\n", rs.size());
    for (size_t i = 0; i < rs.size(); ++i) {
      printf("--- %zu 行目 ---\n", i + 1);
      show_one(rs[i], "");
    }
    return 0;
  }
  const pl::Result r = pl::parse(syms);
  if (!r.ok) { printf("レイアウト解析に失敗: %s\n", r.why.c_str()); return 1; }
  show_one(r, "");
  return 0;
}

int main(int argc, char** argv) {
#ifdef _WIN32
  SetConsoleOutputCP(CP_UTF8);
#endif
  if (argc < 2) {
    printf("usage: mathcam <eval|solve|render|dataset|parse|selftest|photo> ...\n");
    return 1;
  }
  const std::string cmd = argv[1];
  if (cmd == "eval") return cmd_eval(argc, argv);
  if (cmd == "solve") return cmd_solve(argc, argv);
  if (cmd == "render") return cmd_render(argc, argv);
  if (cmd == "dataset") return cmd_dataset(argc, argv);
  if (cmd == "genexpr") return cmd_genexpr(argc, argv);
  if (cmd == "parse") return cmd_parse(argc, argv);
  if (cmd == "selftest") return cmd_selftest(argc, argv);
  if (cmd == "fontinfo") return cmd_fontinfo(argc, argv);
  if (cmd == "photo") return cmd_photo(argc, argv);
  if (cmd == "rgba") return cmd_rgba(argc, argv);
  if (cmd == "e2e") return cmd_e2e(argc, argv);
  printf("mathcam: '%s' is not implemented yet\n", cmd.c_str());
  return 1;
}
