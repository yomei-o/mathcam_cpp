// 関数を調べる — 微分の応用（数学 II / III）。接線と極値。
//
// calc.hpp（微分）と solve.hpp（方程式）を組み合わせるだけだが、**教科書の問い方**に
// そろえるのがここの仕事:
//
//   f(x) = x^3 - 3x の極値を求めよ        -> f'(x) = 3x^2 - 3、f'=0 の解で増減を調べる
//   y = x^2 の x = 1 における接線を求めよ  -> y = f'(1)(x - 1) + f(1) = 2x - 1
//
// 極大・極小の判定は **f''(c) の符号**で行う（増減表を作る代わり。f''(c) = 0 のときは
// 「判定できない」と言って、勝手に決めつけない）。
#pragma once
#include "expr.hpp"
#include "calc.hpp"
#include "solve.hpp"
#include <string>
#include <vector>

namespace crv {

using cal::Step;

struct Result {
  bool ok = false;
  std::string why;
  std::string var = "x";
  ex::E d1, d2;                       // f' と f''
  std::vector<ex::E> crit;            // f' = 0 の解（小さい順）
  std::vector<std::string> kinds;     // 「極大」「極小」「判定できない」
  std::vector<ex::E> vals;            // その点での f の値
  bool has_at = false;
  ex::E at, tangent, normal;          // 接線・法線（--at のとき）
  std::vector<Step> steps;
};

using cal::push;                                     // 手を積むのは calc.hpp と同じもの

inline Result curve(const ex::E& f, const std::string& want_var, const ex::E& at) {
  using namespace ex;
  Result r;
  std::vector<std::string> vs;
  collect_syms(f, vs);
  r.var = !want_var.empty() ? want_var : (vs.empty() ? "x" : vs[0]);
  const std::string var = r.var;
  const E x = sym(var);

  bool ok1 = true;
  r.d1 = simp(expand(cal::diff(f, var, &ok1)));
  if (!ok1) { r.why = "この式は微分できません"; return r; }
  bool ok2 = true;
  r.d2 = simp(expand(cal::diff(r.d1, var, &ok2)));
  if (!ok2) r.d2 = E();
  push(r.steps, "微分する", "f'(" + var + ") = " + to_infix(r.d1), f, r.d1);

  // 接線（--at）。y = f'(a)(x - a) + f(a)
  if (at) {
    r.has_at = true;
    r.at = at;
    const E fa = simp(subst(f, var, at));
    const E ma = simp(subst(r.d1, var, at));
    if (cal::has_var(fa, var) || cal::has_var(ma, var)) { r.why = "接点の値が求まりません"; return r; }
    r.tangent = expand(add_n({mul_n({ma, add_n({x, neg(at)})}), fa}));
    push(r.steps, "接線の式",
         "y = f'(" + to_infix(at) + ")(" + var + " - " + to_infix(at) + ") + f(" +
             to_infix(at) + ")",
         r.d1, r.tangent);
    // 法線（接線に垂直。傾きが 0 のときは x = a の縦線になるので出さない）
    if (!(is_num(ma) && ma->num.is_zero()))
      r.normal = expand(add_n({mul_n({neg(pow_e(ma, num(Rat(-1)))), add_n({x, neg(at)})}), fa}));
  }

  // 極値: f'(x) = 0 を解いて、f'' の符号で見分ける
  const slv::Solution s = slv::solve(eq(r.d1, num(Rat(0))), var);
  if (s.ok && !s.roots.empty()) {
    push(r.steps, "f'(x) = 0 を解く", "傾きが 0 になるところを探す", eq(r.d1, num(Rat(0))),
         eq(r.d1, num(Rat(0))));
    for (const slv::Step& st : s.steps)               // 手の型が違うので詰め替える
      push(r.steps, st.rule, st.note, st.before, st.after);
    std::vector<E> cs = s.roots;
    std::sort(cs.begin(), cs.end(), [](const E& a, const E& b) { return approx(a) < approx(b); });
    for (const E& c : cs) {
      const E fv = simp(subst(f, var, c));
      std::string kind = "判定できない";
      if (r.d2) {
        const E dv = simp(subst(r.d2, var, c));
        if (!cal::has_var(dv, var)) {
          const double t = approx(dv);
          if (t > 1e-12) kind = "極小";
          else if (t < -1e-12) kind = "極大";
        }
      }
      r.crit.push_back(c);
      r.kinds.push_back(kind);
      r.vals.push_back(fv);
      push(r.steps, "増減を調べる",
           var + " = " + to_infix(c) + " では f''(" + to_infix(c) + ") の符号から " + kind,
           eq(x, c), fv);
    }
  } else if (s.ok) {
    push(r.steps, "f'(x) = 0 を解く", "傾きが 0 になるところは無いので極値も無い",
         eq(r.d1, num(Rat(0))), eq(r.d1, num(Rat(0))));
  }
  r.ok = true;
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  using namespace ex;
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  const auto show = [&](const E& e) { return latex ? to_latex(e) : to_infix(e); };
  out.push_back("f'(" + r.var + ") = " + show(r.d1));
  if (r.has_at) {
    out.push_back("接線: y = " + show(r.tangent));
    if (r.normal) out.push_back("法線: y = " + show(r.normal));
  }
  if (r.crit.empty()) {
    out.push_back("極値なし");
    return out;
  }
  for (size_t i = 0; i < r.crit.size(); ++i)
    out.push_back(r.kinds[i] + ": " + r.var + " = " + show(r.crit[i]) + " のとき " +
                  show(r.vals[i]));
  return out;
}

}  // namespace crv
