// 記号のクラス表。**ここが唯一の正**（学習データの番号と推論の番号がずれたら、症状は
// 「たまに変な式になる」だけで、原因に辿り着くのに時間がかかる）。
//
// 並びを変えるときは、学習済みモデルも作り直すこと。追加は末尾に足すだけなら既存モデルと
// 互換（番号が動かない）。
#pragma once
#include <string>
#include <vector>

namespace cls {

inline const std::vector<std::string>& all() {
  static const std::vector<std::string> v = {
      "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
      "+", "-", "=", "(", ")", "sqrt", "frac",
      "x", "y", "t", "a", "b", "c", "n",
      "s", "i", "o", "l", "e", "g", "p", "q", "r", "t2",
      // 小学校の計算を読むために足したもの（**末尾に足す**ので既存モデルと番号は互換。
      // ただし新しいクラスを使うデータで学習し直さないと、検出はされない）。
      // times = ×、div = ÷、dot = 小数点、brace_l / brace_r = { }
      "times", "div", "dot", "brace_l", "brace_r"};
  return v;
}

inline int id_of(const std::string& name) {
  const std::vector<std::string>& v = all();
  for (size_t i = 0; i < v.size(); ++i)
    if (v[i] == name) return (int)i;
  return -1;
}

inline const std::string& name_of(int id) {
  static const std::string unknown = "?";
  const std::vector<std::string>& v = all();
  return (id >= 0 && id < (int)v.size()) ? v[(size_t)id] : unknown;
}

}  // namespace cls
