// 極限 — 数学 III の入口。lim[x->a] f(x)。
//
// 教科書でまず出る 3 つの形だけを、教科書の手順の名前で解く:
//
//   そのまま代入できる       lim[x->2] (x^2 + 1) = 5
//   0/0 になる（約分する）   lim[x->1] (x^2 - 1)/(x - 1) = 2
//   x -> ∞（最高次で割る）   lim[x->∞] (2x^2 + 1)/(x^2 - x) = 2
//
// それと sin(x)/x -> 1（数学 III の基本公式）。
//
// **できないものは黙って間違えない**。分母だけが 0 になるときは「発散する」と言い、
// 符号が決められないときは決めつけない。
#pragma once
#include "expr.hpp"
#include "solve.hpp"
#include "calc.hpp"
#include <string>
#include <vector>

namespace lim {

using cal::Step;
using cal::push;

struct Result {
  bool ok = false;
  std::string why;
  std::string var = "x";
  ex::E value;                   // 収束するときの値
  int inf = 0;                   // +1: +∞ に発散 / -1: -∞ / 0: 収束
  bool diverge = false;          // 符号が決められない発散
  std::vector<Step> steps;
};

// 多項式を (var - a) で割る（0/0 の約分。割り切れるときだけ true）
inline bool div_root(std::vector<ex::Rat>& c, const ex::Rat& a) {
  using namespace ex;
  const size_t n = c.size();
  if (n < 2) return false;
  std::vector<Rat> b(n - 1, Rat(0));
  b[n - 2] = c[n - 1];
  for (size_t i = n - 2; i >= 1; --i) b[i - 1] = c[i] + a * b[i];
  const Rat rem = c[0] + a * b[0];
  if (!rem.is_zero()) return false;
  c = b;
  return true;
}

inline ex::Rat poly_at(const std::vector<ex::Rat>& c, const ex::Rat& a) {
  using namespace ex;
  Rat v(0), pw(1);
  for (size_t i = 0; i < c.size(); ++i) { v = v + c[i] * pw; pw = pw * a; }
  return v;
}

inline Result limit(const ex::E& f, const std::string& want_var, const ex::E& a, int at_inf) {
  using namespace ex;
  Result r;
  std::vector<std::string> vs;
  collect_syms(f, vs);
  r.var = !want_var.empty() ? want_var : (vs.empty() ? "x" : vs[0]);
  const std::string var = r.var;

  std::vector<E> up, down;
  split_num_den(f, up, down);
  const E num = up.empty() ? ex::num(Rat(1)) : (up.size() == 1 ? up[0] : mul_n(up));
  const E den = down.empty() ? ex::num(Rat(1)) : (down.size() == 1 ? down[0] : mul_n(down));

  std::vector<Rat> cn, cd;
  const bool poly = slv::poly_coeffs(expand(num), var, cn) &&
                    slv::poly_coeffs(expand(den), var, cd);
  if (poly) {
    while (cn.size() > 1 && cn.back().is_zero()) cn.pop_back();
    while (cd.size() > 1 && cd.back().is_zero()) cd.pop_back();
  }

  // ---------------- x -> ±∞
  if (at_inf) {
    if (!poly) { r.why = "x -> 無限大 は分数式のときだけ解けます"; return r; }
    const size_t dn = cn.size() - 1, dd = cd.size() - 1;
    push(r.steps, "最高次で割る", "分子と分母を x^" + std::to_string(dd > dn ? dd : dn) +
         " で割ると、残るのは最高次の係数だけ", f, f);
    r.ok = true;
    if (dn < dd) {
      push(r.steps, "次数を比べる", "分母のほうが次数が高いので 0 に近づく", f, ex::num(Rat(0)));
      r.value = ex::num(Rat(0));
      return r;
    }
    if (dn == dd) {
      const Rat v = cn[dn] / cd[dd];
      push(r.steps, "次数を比べる", "次数が同じなので最高次の係数の比になる", f, ex::num(v));
      r.value = ex::num(v);
      return r;
    }
    // 分子のほうが次数が高い -> 発散。符号は「最高次の係数の比」と x の符号で決まる
    Rat lead = cn[dn] / cd[dd];
    const size_t gap = dn - dd;
    int sign = lead.neg() ? -1 : 1;
    if (at_inf < 0 && gap % 2 == 1) sign = -sign;    // x -> -∞ で奇数次なら向きが変わる
    push(r.steps, "次数を比べる", "分子のほうが次数が高いので発散する", f, f);
    r.inf = sign;
    return r;
  }

  // ---------------- 有限の a
  if (!is_num(a)) { r.why = "近づく先は数でないと解けません"; return r; }
  const Rat av = a->num;
  const E dv = simp(subst(den, var, a));
  const E nv = simp(subst(num, var, a));
  if (is_num(dv) && !dv->num.is_zero()) {
    const E v = simp(subst(f, var, a));
    if (!cal::has_var(v, var)) {
      push(r.steps, "そのまま代入する", "分母が 0 にならないので、代入するだけでよい", f, v);
      r.ok = true;
      r.value = v;
      return r;
    }
  }
  if (is_num(dv) && dv->num.is_zero() && is_num(nv) && !nv->num.is_zero()) {
    push(r.steps, "分母だけが 0", "分子は 0 でないので、値はどこまでも大きくなる", f, f);
    r.ok = true;
    r.diverge = true;
    return r;
  }

  // 0/0 の形
  if (poly && is_num(dv) && dv->num.is_zero()) {
    push(r.steps, "0/0 の形", "分子も分母も 0 になるので、共通の因数 (" + var + " - " +
         av.str() + ") で約分する", f, f);
    int cut = 0;
    while (poly_at(cn, av).is_zero() && poly_at(cd, av).is_zero()) {
      if (!div_root(cn, av) || !div_root(cd, av)) break;
      ++cut;
    }
    if (cut == 0) { r.why = "約分できませんでした"; return r; }
    const E n2 = slv::from_coeffs(cn, var), d2 = slv::from_coeffs(cd, var);
    const E shown = mul_n({n2, pow_e(d2, ex::num(Rat(-1)))});
    push(r.steps, "約分する", std::to_string(cut) + " 回割れる", f, shown);
    const Rat dv2 = poly_at(cd, av);
    if (dv2.is_zero()) {
      push(r.steps, "分母だけが 0", "約分しても分母が 0 なので発散する", shown, shown);
      r.ok = true;
      r.diverge = true;
      return r;
    }
    const E v = simp(subst(shown, var, a));
    push(r.steps, "代入する", "約分したあとなら代入できる", shown, v);
    r.ok = true;
    r.value = v;
    return r;
  }

  // sin(kx)/(mx) -> k/m（数学 III の基本公式）
  if (av.is_zero() && num->k == Kind::Fn && num->kids.size() == 1 &&
      (num->name == "sin" || num->name == "tan")) {
    Rat k(0), b0(0), m(0), b1(0);
    if (cal::linear_in(num->kids[0], var, k, b0) && b0.is_zero() && !k.is_zero() &&
        cal::linear_in(den, var, m, b1) && b1.is_zero() && !m.is_zero()) {
      push(r.steps, "sin x / x の公式",
           "x -> 0 のとき sin(x)/x -> 1 を使う（中身に合わせて係数を出す）", f,
           ex::num(k / m));
      r.ok = true;
      r.value = ex::num(k / m);
      return r;
    }
  }

  r.why = "この形の極限は未対応";
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  if (r.diverge) { out.push_back("発散する（値は定まらない）"); return out; }
  if (r.inf > 0) { out.push_back("+∞ に発散する"); return out; }
  if (r.inf < 0) { out.push_back("-∞ に発散する"); return out; }
  out.push_back(latex ? ex::to_latex(r.value) : ex::to_infix(r.value));
  return out;
}

}  // namespace lim
