// mathcam — このプロジェクトの CLI（C++ 側）。tools/ の Python 側と 1 対 1 に対応させる。
//
//   mathcam eval  --expr "2/3 + 1/6"          式を読んで正規形と答えを出す
//   mathcam eval  --expr "x^2 - 5x + 6 = 0" --steps   手順つきで解く（実装は次の段）
//
// build: sh build/cc.sh pure/mathcam.cpp -o mathcam.exe
//        sh build/gcc.sh pure/mathcam.cpp -o mathcam.exe
#include "expr.hpp"
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

int main(int argc, char** argv) {
#ifdef _WIN32
  SetConsoleOutputCP(CP_UTF8);
#endif
  if (argc < 2) {
    printf("usage: mathcam <eval> ...\n");
    return 1;
  }
  const std::string cmd = argv[1];
  if (cmd == "eval") return cmd_eval(argc, argv);
  printf("mathcam: '%s' is not implemented yet\n", cmd.c_str());
  return 1;
}
