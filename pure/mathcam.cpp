// mathcam — このプロジェクトの CLI（C++ 側）。tools/ の Python 側と 1 対 1 に対応させる。
//
//   mathcam eval  --expr "2/3 + 1/6"          式を読んで正規形と答えを出す
//   mathcam solve --expr "x^2 - 5x + 6 = 0" [--steps] [--latex]  解く（手順つき）
//   mathcam render --expr "1/2 x + sqrt(2) = 0" --out out.png [--labels out.txt] [--px 48]
//   mathcam dataset --out data/train --n 2000 [--seed 1] [--px-min 32 --px-max 64]
//
// build: sh build/cc.sh pure/mathcam.cpp -o mathcam.exe
//        sh build/gcc.sh pure/mathcam.cpp -o mathcam.exe
#define STB_TRUETYPE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"
#include "expr.hpp"
#include "solve.hpp"
#include "typeset_impl.hpp"
#include "gen_expr.hpp"
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

// mathcam solve — 方程式を解く。--steps で「人が紙に書く手」を並べる。
// 正規化（同類項をまとめる・約分）は手順に出さない。出すと人には読めないものになる。
static int cmd_solve(int argc, char** argv) {
  const std::string src = arg_of(argc, argv, "--expr", "");
  const std::string var = arg_of(argc, argv, "--var", "");
  const bool steps = has_flag(argc, argv, "--steps");
  const bool latex = has_flag(argc, argv, "--latex");
  if (src.empty()) {
    printf("usage: mathcam solve --expr \"x^2 - 5x + 6 = 0\" [--var x] [--steps] [--latex]\n");
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
  if (s.kind == "identity") { printf("すべての値で成り立つ\n"); return 0; }
  if (s.kind == "contradiction") { printf("解なし（矛盾）\n"); return 0; }
  if (s.roots.empty()) { printf("実数解なし\n"); return 0; }
  for (size_t i = 0; i < s.roots.size(); ++i)
    printf("%s = %s\n", s.var.c_str(), show(s.roots[i]).c_str());
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
  const int px = std::atoi(arg_of(argc, argv, "--px", "48").c_str());
  if (src.empty() || (out.empty() && labels.empty())) {
    printf("usage: mathcam render --expr \"1/2 x = 3\" --out out.png [--labels out.txt]\n"
           "                      [--px 48] [--font path.ttf]\n");
    return 1;
  }
  std::string why;
  ex::E e = ex::parse(src, &why);
  if (!why.empty()) { printf("parse error: %s\n", why.c_str()); return 1; }

  ts::Font font;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }
  const ts::Rendered R = ts::render(font, e, px);
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
  const bool no_img = has_flag(argc, argv, "--no-images");   // 枠だけ作る（パリティ確認用）
  if (dir.empty()) {
    printf("usage: mathcam dataset --out data/train --n 2000 [--seed 1] [--px-min 32]\n"
           "                       [--px-max 64] [--font path.ttf] [--no-images]\n");
    return 1;
  }
  std::string why;
  ts::Font font;
  if (!ts::load_font(font, fontp, &why)) { printf("%s\n", why.c_str()); return 1; }

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
    const std::string src = gx::one(rng);
    const int px = (int)(px_min + (int)rng.below((uint64_t)(px_max - px_min + 1)));
    std::string err;
    ex::E e = ex::parse(src, &err);
    if (!err.empty()) { ++skipped; continue; }        // 生成器が壊れた式を出したら捨てる
    const ts::Rendered R = ts::render(font, e, px);
    char stem[32];
    snprintf(stem, sizeof stem, "%06d", made);
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

int main(int argc, char** argv) {
#ifdef _WIN32
  SetConsoleOutputCP(CP_UTF8);
#endif
  if (argc < 2) {
    printf("usage: mathcam <eval|solve|render|dataset> ...\n");
    return 1;
  }
  const std::string cmd = argv[1];
  if (cmd == "eval") return cmd_eval(argc, argv);
  if (cmd == "solve") return cmd_solve(argc, argv);
  if (cmd == "render") return cmd_render(argc, argv);
  if (cmd == "dataset") return cmd_dataset(argc, argv);
  if (cmd == "genexpr") return cmd_genexpr(argc, argv);
  printf("mathcam: '%s' is not implemented yet\n", cmd.c_str());
  return 1;
}
