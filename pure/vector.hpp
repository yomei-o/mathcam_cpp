// ベクトル — 数学 B / C。成分で与えられた 2 つのベクトルを調べる。
//
//   a = (1, 2), b = (3, 4)  ->  内積 11、|a| = sqrt(5)、|b| = 5、なす角は特別角でない
//   a = (1, 0), b = (1, 1)  ->  なす角 pi/4
//   a = (1, 2), b = (2, 4)  ->  平行
//   a = (1, 2), b = (2, -1) ->  垂直（内積が 0）
//
// **なす角は cos θ が特別角の値のときだけ書く**（そうでなければ cos θ の値まで）。
// 三角方程式と同じ約束で、arccos を勝手に持ち出さない。
#pragma once
#include "expr.hpp"
#include "solve.hpp"
#include <string>
#include <vector>

namespace vec {

using slv::Step;
using slv::push;

struct Result {
  bool ok = false;
  std::string why;
  std::vector<ex::E> a, b;
  ex::E dot, na, nb, cosv, angle;   // 内積・大きさ・cos θ・なす角
  ex::E sum, diff;                  // 和と差（成分）
  bool para = false, perp = false;
  std::vector<Step> steps;
};

inline std::string show_vec(const std::vector<ex::E>& v, bool latex) {
  std::string s = "(";
  for (size_t i = 0; i < v.size(); ++i) {
    if (i) s += ", ";
    s += latex ? ex::to_latex(v[i]) : ex::to_infix(v[i]);
  }
  return s + ")";
}

inline Result analyze(const std::vector<ex::E>& a, const std::vector<ex::E>& b) {
  using namespace ex;
  Result r;
  r.a = a;
  r.b = b;
  if (a.size() != b.size() || a.size() < 2 || a.size() > 3) {
    r.why = "2 次元か 3 次元で、成分の数をそろえてください";
    return r;
  }
  std::vector<E> ds, ss, aa, bb;
  for (size_t i = 0; i < a.size(); ++i) {
    ds.push_back(mul_n({a[i], b[i]}));
    aa.push_back(mul_n({a[i], a[i]}));
    bb.push_back(mul_n({b[i], b[i]}));
  }
  r.dot = simp(expand(add_n(ds)));
  r.na = pow_e(simp(expand(add_n(aa))), num(Rat(1, 2)));
  r.nb = pow_e(simp(expand(add_n(bb))), num(Rat(1, 2)));
  {
    std::vector<E> su, di;
    for (size_t i = 0; i < a.size(); ++i) {
      su.push_back(simp(add_n({a[i], b[i]})));
      di.push_back(simp(add_n({a[i], neg(b[i])})));
    }
    r.sum = raw(Kind::Fn, su, "vec");
    r.diff = raw(Kind::Fn, di, "vec");
  }
  push(r.steps, "内積", "成分どうしを掛けて足す", r.dot, r.dot);
  push(r.steps, "大きさ", "|a| = sqrt(a・a)", r.na, r.na);

  if (is_num(r.dot) && r.dot->num.is_zero()) {
    r.perp = true;
    push(r.steps, "垂直", "内積が 0 なので 2 つのベクトルは垂直", r.dot, r.dot);
  }
  // 平行: a1 b2 - a2 b1 = 0（3 次元なら外積が 0）
  {
    bool par = true;
    for (size_t i = 0; i < a.size() && par; ++i)
      for (size_t j = i + 1; j < a.size() && par; ++j) {
        const E cr = simp(expand(add_n({mul_n({a[i], b[j]}), neg(mul_n({a[j], b[i]}))})));
        if (!(is_num(cr) && cr->num.is_zero())) par = false;
      }
    if (par) {
      r.para = true;
      push(r.steps, "平行", "成分の比が等しいので 2 つのベクトルは平行", r.dot, r.dot);
    }
  }

  // cos θ = a・b / (|a||b|)
  const E den = simp(mul_n({r.na, r.nb}));
  if (is_num(den) && den->num.is_zero()) { r.ok = true; return r; }
  r.cosv = simp(mul_n({r.dot, pow_e(den, num(Rat(-1)))}));
  push(r.steps, "なす角", "cos θ = a・b / (|a||b|) = " + to_infix(r.cosv), r.cosv, r.cosv);
  for (long long t = 0; t <= 12; ++t) {              // 0 <= θ <= π の特別角だけ探す
    const long long m = t % 12;
    if (m == 1 || m == 5 || m == 7 || m == 11) continue;
    E cv;
    if (!trig_exact("cos", Rat(t, 12), cv)) continue;
    if (!equal(simp(cv), r.cosv)) continue;
    r.angle = t == 0 ? num(Rat(0)) : simp(mul_n({num(Rat(t, 12)), fn_e("pi", {})}));
    break;
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
  out.push_back("内積: " + show(r.dot));
  out.push_back("大きさ: |a| = " + show(r.na) + "、|b| = " + show(r.nb));
  out.push_back("和: " + show_vec(r.sum->kids, latex) + "、差: " + show_vec(r.diff->kids, latex));
  if (r.perp) out.push_back("垂直（内積が 0）");
  if (r.para) out.push_back("平行（成分の比が等しい）");
  if (r.cosv) {
    out.push_back("cos θ = " + show(r.cosv));
    if (r.angle) out.push_back("なす角 θ = " + show(r.angle));
    else out.push_back("なす角は特別角になりません");
  }
  return out;
}

}  // namespace vec
