// mathcam — このプロジェクトの CLI（C++ 側）。tools/ の Python 側と 1 対 1 に対応させる。
//
//   mathcam eval  --expr "2/3 + 1/6"          式を読んで正規形と答えを出す
//   mathcam solve --expr "x^2 - 5x + 6 = 0" [--steps] [--latex]  解く（手順つき）
//
// build: sh build/cc.sh pure/mathcam.cpp -o mathcam.exe
//        sh build/gcc.sh pure/mathcam.cpp -o mathcam.exe
#include "expr.hpp"
#include "solve.hpp"
#include <cstdio>
#include <cstring>
#include <string>
#ifdef _WIN32
#include <windows.h>
#endif

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

int main(int argc, char** argv) {
#ifdef _WIN32
  SetConsoleOutputCP(CP_UTF8);
#endif
  if (argc < 2) {
    printf("usage: mathcam <eval|solve> ...\n");
    return 1;
  }
  const std::string cmd = argv[1];
  if (cmd == "eval") return cmd_eval(argc, argv);
  if (cmd == "solve") return cmd_solve(argc, argv);
  printf("mathcam: '%s' is not implemented yet\n", cmd.c_str());
  return 1;
}
