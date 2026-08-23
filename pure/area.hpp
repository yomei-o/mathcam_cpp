// 面積 — 定積分の応用（数学 II / III）。
//
//   y = x^2 と y = x で囲まれた図形の面積        -> 交点を求めて ∫(上 - 下)
//   y = x^2 - 1 と x 軸、x = 0 から 2 までの面積 -> 符号が変わるところで区切って絶対値で足す
//
// **符号が変わるところで区切る**のが要点。∫ をそのまま計算すると、x 軸より下の部分が
// 引き算になって「面積」にならない（教科書もそこを強調する）。
#pragma once
#include "expr.hpp"
#include "calc.hpp"
#include "solve.hpp"
#include <string>
#include <vector>

namespace area {

using cal::Step;
using cal::push;

struct Result {
  bool ok = false;
  std::string why;
  std::string var = "x";
  ex::E value;                    // 面積
  std::vector<ex::E> cuts;        // 区切り（交点や指定した端）
  std::vector<Step> steps;
};

// f と g で囲まれた面積（lo, hi を渡せばその範囲、渡さなければ交点のあいだ）
inline Result area(const ex::E& f, const ex::E& g, const std::string& want_var, const ex::E& lo,
                   const ex::E& hi) {
  using namespace ex;
  Result r;
  std::vector<std::string> vs;
  collect_syms(f, vs);
  collect_syms(g, vs);
  std::sort(vs.begin(), vs.end());
  vs.erase(std::unique(vs.begin(), vs.end()), vs.end());
  r.var = !want_var.empty() ? want_var : (vs.empty() ? "x" : vs[0]);
  const std::string var = r.var;
  const E d = expand(sub(f, g));                     // 差。これの符号で上下が決まる

  // 区切り: 交点（f = g の解）と、指定された端
  std::vector<E> cuts;
  const slv::Solution s = slv::solve(eq(d, num(Rat(0))), var);
  if (s.ok)
    for (const E& t : s.roots)
      if (!cal::has_var(t, var)) cuts.push_back(t);
  if (lo) cuts.push_back(lo);
  if (hi) cuts.push_back(hi);
  if (lo && hi) {                                    // 範囲の外の交点は使わない
    std::vector<E> in;
    const double a0 = approx(lo), b0 = approx(hi);
    for (const E& t : cuts) {
      const double v = approx(t);
      if (v >= a0 - 1e-12 && v <= b0 + 1e-12) in.push_back(t);
    }
    cuts = in;
  }
  std::sort(cuts.begin(), cuts.end(), [](const E& a, const E& b) { return approx(a) < approx(b); });
  cuts.erase(std::unique(cuts.begin(), cuts.end(),
                         [](const E& a, const E& b) { return equal(a, b); }),
             cuts.end());
  if (cuts.size() < 2) {
    r.why = "囲まれた範囲が決まりません（交点が足りないか、範囲の指定が要ります）";
    return r;
  }
  r.cuts = cuts;
  {
    std::string t;
    for (size_t i = 0; i < cuts.size(); ++i) { if (i) t += ", "; t += to_infix(cuts[i]); }
    push(r.steps, "区切りを決める", "交点と端で区切る: " + var + " = " + t, d, d);
  }

  // 各区間で ∫(f - g) を計算して、絶対値で足す
  std::vector<E> parts;
  for (size_t i = 0; i + 1 < cuts.size(); ++i) {
    const cal::Result ir = cal::integrate(d, var, cuts[i], cuts[i + 1]);
    if (!ir.ok) { r.why = ir.why; return r; }
    E v = simp(ir.value);
    const bool neg = approx(v) < 0;
    if (neg) v = simp(ex::neg(v));
    push(r.steps, "区間ごとに積分する",
         "∫[" + to_infix(cuts[i]) + ".." + to_infix(cuts[i + 1]) + "](上 - 下) = " +
             (neg ? "-" : "") + to_infix(v) + (neg ? "（下に出ているので符号を反転）" : ""),
         d, v);
    parts.push_back(v);
  }
  r.value = simp(add_n(parts));
  push(r.steps, "足す", "区間ごとの面積を足す", r.value, r.value);
  r.ok = true;
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  out.push_back("面積 = " + (latex ? ex::to_latex(r.value) : ex::to_infix(r.value)));
  return out;
}

}  // namespace area
