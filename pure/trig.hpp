// 三角関数の変形 — 数学 II。加法定理・2 倍角・合成。
//
//   sin(x + pi/3)            -> 加法定理で開く
//   sin(2x)                  -> 2 sin(x) cos(x)（2 倍角）
//   sin(x) + sqrt(3) cos(x)  -> 2 sin(x + pi/3)（合成）
//
// **合成は「係数の組が特別角になるとき」だけ角を書く**。cos α = a/r, sin α = b/r に
// 合う特別角が無ければ、r だけ出して「α は特別角ではありません」と言う（教科書もそこで
// 止めて α を図で示す）。勝手に arctan を持ち出さない。
#pragma once
#include "expr.hpp"
#include "calc.hpp"
#include <string>
#include <vector>

namespace trg {

using cal::Step;
using cal::push;

struct Result {
  bool ok = false;
  std::string why;
  ex::E value;
  std::vector<Step> steps;
  bool composed = false;           // 合成したか
  ex::E amp, phase;                // 合成のときの r と α
};

// sin/cos の中身を「1 つの角」として見る
inline bool is_trig(const ex::E& e, const char* name) {
  return e->k == ex::Kind::Fn && e->name == name && e->kids.size() == 1;
}

// 加法定理と 2 倍角を 1 段だけ開く。開けたら true
inline bool expand_once(const ex::E& e, ex::E& out, std::string& rule) {
  using namespace ex;
  if (!(is_trig(e, "sin") || is_trig(e, "cos"))) return false;
  const bool sn = is_trig(e, "sin");
  const E u = e->kids[0];
  // n 倍角（整数 n >= 2）: n u = u + (n-1)u と見て加法定理に落とす
  if (u->k == Kind::Mul && u->kids.size() == 2 && is_num(u->kids[0]) &&
      u->kids[0]->num.is_int() && u->kids[0]->num.n >= 2) {
    const long long n = u->kids[0]->num.n;
    const E base = u->kids[1];
    const E a = base, b = n == 2 ? base : mul_n({num(Rat(n - 1)), base});
    out = sn ? add_n({mul_n({fn_e("sin", {a}), fn_e("cos", {b})}),
                      mul_n({fn_e("cos", {a}), fn_e("sin", {b})})})
             : add_n({mul_n({fn_e("cos", {a}), fn_e("cos", {b})}),
                      neg(mul_n({fn_e("sin", {a}), fn_e("sin", {b})}))});
    rule = n == 2 ? "2 倍角の公式" : "加法定理";
    return true;
  }
  // 和の角: sin(A + B) / cos(A + B)
  if (u->k == Kind::Add && u->kids.size() >= 2) {
    const E a = u->kids[0];
    std::vector<E> restk(u->kids.begin() + 1, u->kids.end());
    const E b = restk.size() == 1 ? restk[0] : add_n(restk);
    out = sn ? add_n({mul_n({fn_e("sin", {a}), fn_e("cos", {b})}),
                      mul_n({fn_e("cos", {a}), fn_e("sin", {b})})})
             : add_n({mul_n({fn_e("cos", {a}), fn_e("cos", {b})}),
                      neg(mul_n({fn_e("sin", {a}), fn_e("sin", {b})}))});
    rule = "加法定理";
    return true;
  }
  return false;
}

// 木のどこか 1 か所を開く（上から順に）
inline bool expand_tree(const ex::E& e, ex::E& out, std::string& rule) {
  using namespace ex;
  if (expand_once(e, out, rule)) return true;
  for (size_t i = 0; i < e->kids.size(); ++i) {
    E sub;
    if (expand_tree(e->kids[i], sub, rule)) {
      std::vector<E> ks = e->kids;
      ks[i] = sub;
      out = simp(raw(e->k, ks, e->name));
      return true;
    }
  }
  return false;
}

// a sin(u) + b cos(u) の係数を式のまま取り出す（sqrt を含んでよい）
inline bool split_ab(const ex::E& e, ex::E& a, ex::E& b, ex::E& u) {
  using namespace ex;
  if (e->k != Kind::Add) return false;
  a = num(Rat(0));
  b = num(Rat(0));
  for (const E& t : e->kids) {
    std::vector<E> coef;
    E core;
    std::vector<E> fs;
    if (t->k == Kind::Mul) fs = t->kids; else fs.push_back(t);
    for (const E& f : fs) {
      if (is_trig(f, "sin") || is_trig(f, "cos")) {
        if (core) return false;
        core = f;
        continue;
      }
      coef.push_back(f);
    }
    if (!core) return false;
    if (!u) u = core->kids[0];
    else if (!equal(u, core->kids[0])) return false;
    const E c = coef.empty() ? num(Rat(1)) : mul_n(coef);
    if (is_trig(core, "sin")) a = add_n({a, c}); else b = add_n({b, c});
  }
  return u && !(is_num(a) && a->num.is_zero() && is_num(b) && b->num.is_zero());
}

inline Result transform(const ex::E& in, const std::string& mode) {
  using namespace ex;
  Result r;
  r.value = in;
  r.ok = true;
  std::string why_compose;                           // 合成は届かなかったときの言い方

  // 1) 合成（a sin u + b cos u -> r sin(u + α)）
  if (mode != "expand") {
    E a, b, u;
    if (split_ab(simp(in), a, b, u)) {
      const E r2 = simp(expand(add_n({mul_n({a, a}), mul_n({b, b})})));
      const E amp = pow_e(r2, num(Rat(1, 2)));
      // cos α = a/r, sin α = b/r になる特別角を探す
      const E ca = simp(mul_n({a, pow_e(amp, num(Rat(-1)))}));
      const E sa = simp(mul_n({b, pow_e(amp, num(Rat(-1)))}));
      for (long long t = 0; t < 24; ++t) {
        const long long m = t % 12;
        if (m == 1 || m == 5 || m == 7 || m == 11) continue;
        E cv, sv;
        if (!trig_exact("cos", Rat(t, 12), cv) || !trig_exact("sin", Rat(t, 12), sv)) continue;
        if (!equal(simp(cv), ca) || !equal(simp(sv), sa)) continue;
        // α は -π < α <= π で書く（教科書は sin x - cos x を sqrt(2) sin(x - π/4) と書く）
        const long long tt = t > 12 ? t - 24 : t;
        const E al = tt == 0 ? num(Rat(0)) : simp(mul_n({num(Rat(tt, 12)), fn_e("pi", {})}));
        push(r.steps, "三角関数の合成",
             "a sin x + b cos x = r sin(x + α)。r = sqrt(a^2 + b^2) = " + to_infix(amp) +
                 "、cos α = " + to_infix(ca) + "、sin α = " + to_infix(sa),
             in, mul_n({amp, fn_e("sin", {add_n({u, al})})}));
        r.value = mul_n({amp, fn_e("sin", {add_n({u, al})})});
        r.composed = true;
        r.amp = amp;
        r.phase = al;
        return r;
      }
      if (true) {                                    // 角が特別角でないときの言い方（auto でも使う）
        r.amp = amp;
        push(r.steps, "三角関数の合成", "r = sqrt(a^2 + b^2) = " + to_infix(amp) +
             " までは出るが、cos α = " + to_infix(ca) + "、sin α = " + to_infix(sa) +
             " に合う特別角が無い", in, in);
        r.why = "α が特別角にならないので、r = " + to_infix(amp) + " までしか書けません";
        if (mode == "compose") return r;
        r.steps.clear();                             // auto のときは開くほうも試す
        why_compose = r.why;
        r.why.clear();
      }
    }
  }

  // 2) 加法定理・2 倍角で開く
  if (mode != "compose") {
    E cur = simp(in);
    for (int i = 0; i < 8; ++i) {
      E out;
      std::string rule;
      if (!expand_tree(cur, out, rule)) break;
      out = simp(expand(out));
      push(r.steps, rule, to_infix(cur) + " を開く", cur, out);
      cur = out;
    }
    if (!r.steps.empty()) { r.value = cur; return r; }
  }

  r.why = why_compose.empty()
              ? "この形は変形できません（加法定理・2 倍角・合成のどれにも当てはまらない）"
              : why_compose;
  r.ok = false;
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  out.push_back(latex ? ex::to_latex(r.value) : ex::to_infix(r.value));
  return out;
}

}  // namespace trg
