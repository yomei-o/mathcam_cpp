// 微分と積分 — 高校の範囲を「名前のついた書き換え」で解く。
//
// 方程式の solve.hpp と同じ考え方で作る: **答えだけでなく手順を出す**。手順は
// 「和の微分」「x の n 乗」「積の微分」「合成関数」のように**教科書の言い方**にする
// （正規化や約分は手順に出さない。出すと人には読めないものになる）。
//
// 何ができるか:
//   微分  多項式、x^n（有理数の n）、根号、積・商、合成関数、sin cos tan ln exp
//   積分  多項式、x^n（n ≠ -1）、1/x、(ax+b)^n、1/(ax+b)、sin cos exp。定積分は F(b) - F(a)
//
// **できないものは黙って間違えない**（ok=false と理由を返す）。sin(x^2) の積分のように
// 初等関数で表せないものは、そう言う。
#pragma once
#include "expr.hpp"
#include <string>
#include <vector>

namespace cal {

struct Step {
  std::string rule;      // 規則の名前（「x の n 乗」「積の微分」…）
  std::string note;      // 一言説明
  ex::E before, after;   // その手の前後
};

struct Result {
  bool ok = false;
  std::string why;
  ex::E value;                  // 微分した式 / 原始関数 / 定積分の値
  std::vector<Step> steps;
  bool definite = false;        // 定積分か
  ex::E lo, hi;                 // 定積分の範囲
  ex::E anti;                   // 定積分のときの原始関数
};

inline void push(std::vector<Step>& steps, const std::string& rule, const std::string& note,
                 const ex::E& before, const ex::E& after) {
  Step s;
  s.rule = rule;
  s.note = note;
  s.before = before;
  s.after = after;
  steps.push_back(s);
}

// var を含むか
inline bool has_var(const ex::E& e, const std::string& var) {
  if (e->k == ex::Kind::Sym) return e->name == var;
  for (const ex::E& k : e->kids)
    if (has_var(k, var)) return true;
  return false;
}

// ---------------------------------------------------------------- 微分
//
// 手順は**上から 1 段だけ**名前をつける（和なら「項ごとに微分する」、項ごとに規則名）。
// 全部の再帰に名前をつけると、人が読めない長さになる。

inline ex::E diff(const ex::E& e, const std::string& var, bool* ok = nullptr);

// その式に使う規則の名前（手順の見出し用）
inline std::string rule_of(const ex::E& e, const std::string& var) {
  using namespace ex;
  if (!has_var(e, var)) return "定数";
  if (e->k == Kind::Sym) return "変数そのもの";
  if (e->k == Kind::Add) return "和の微分";
  if (e->k == Kind::Pow) {
    const E& b = e->kids[0];
    if (b->k == Kind::Sym && b->name == var) return "x の n 乗";
    return "合成関数";
  }
  if (e->k == Kind::Mul) {
    int n = 0;
    for (const E& f : e->kids)
      if (has_var(f, var)) ++n;
    return n <= 1 ? "定数倍" : "積の微分";
  }
  if (e->k == Kind::Fn) return "合成関数";
  return "微分";
}

inline ex::E diff(const ex::E& e, const std::string& var, bool* ok) {
  using namespace ex;
  const auto fail = [&](const char* why) {
    (void)why;
    if (ok) *ok = false;
    return num(Rat(0));
  };
  if (!has_var(e, var)) return num(Rat(0));           // 定数
  switch (e->k) {
    case Kind::Sym:
      return num(Rat(1));                              // (x)' = 1
    case Kind::Add: {
      std::vector<E> ts;
      for (const E& k : e->kids) ts.push_back(diff(k, var, ok));
      return add_n(ts);
    }
    case Kind::Mul: {
      // 積の微分（n 個でも: 1 つずつ微分して残りを掛ける）
      std::vector<E> terms;
      for (size_t i = 0; i < e->kids.size(); ++i) {
        std::vector<E> fs;
        for (size_t j = 0; j < e->kids.size(); ++j)
          fs.push_back(i == j ? diff(e->kids[j], var, ok) : e->kids[j]);
        terms.push_back(mul_n(fs));
      }
      return add_n(terms);
    }
    case Kind::Pow: {
      const E& b = e->kids[0];
      const E& p = e->kids[1];
      if (!has_var(p, var)) {
        if (!is_num(p)) return fail("指数が数でない");
        // (f^n)' = n f^(n-1) f'   （f = x なら合成の分は 1）
        const E inner = diff(b, var, ok);
        return mul_n({p, pow_e(b, num(p->num - Rat(1))), inner});
      }
      // 指数に変数がある: (a^f)' = a^f ln(a) f'（底が定数のときだけ）
      if (!has_var(b, var)) {
        const E inner = diff(p, var, ok);
        return mul_n({e, fn_e("ln", {b}), inner});
      }
      return fail("底にも指数にも変数がある形は未対応");
    }
    case Kind::Fn: {
      const std::string& n = e->name;
      // 対数は底を明示して持っている（log(a, f)）。{log_a f}' = f' / (f ln a)
      if (n == "log" && e->kids.size() == 2) {
        const E& base = e->kids[0];
        if (has_var(base, var)) return fail("底に変数がある対数の微分は未対応");
        const E& f2 = e->kids[1];
        const E in2 = diff(f2, var, ok);
        return mul_n({pow_e(f2, num(Rat(-1))), pow_e(fn_e("ln", {base}), num(Rat(-1))), in2});
      }
      if (e->kids.size() != 1) return fail("この関数の微分は未対応");
      const E& f = e->kids[0];
      const E inner = diff(f, var, ok);
      if (n == "sin") return mul_n({fn_e("cos", {f}), inner});
      if (n == "cos") return mul_n({num(Rat(-1)), fn_e("sin", {f}), inner});
      if (n == "tan")                                  // 1/cos^2(f) * f'
        return mul_n({pow_e(fn_e("cos", {f}), num(Rat(-2))), inner});
      if (n == "ln") return mul_n({pow_e(f, num(Rat(-1))), inner});
      if (n == "exp") return mul_n({e, inner});
      return fail("この関数の微分は未対応");
    }
    default:
      return fail("微分できない形");
  }
}

// 手順つきの微分
inline Result differentiate(const ex::E& in, const std::string& want_var = "") {
  using namespace ex;
  Result r;
  std::vector<std::string> vs;
  collect_syms(in, vs);
  const std::string var = !want_var.empty() ? want_var : (vs.empty() ? "x" : vs[0]);
  r.ok = true;
  bool ok = true;
  const E d = simp(diff(in, var, &ok));
  if (!ok) {
    r.ok = false;
    r.why = "この式の微分は未対応";
    return r;
  }
  // 手順: 和なら項ごと、そうでなければ 1 手
  if (in->k == Kind::Add) {
    push(r.steps, "和の微分", "項ごとに微分して足す", in, in);
    // 並びは**表示順**（次数の降順）。正規順序のまま出すと `2x` が `x^3` より先に来て、
    // 人が読む順序と食い違う
    for (const E& t : disp_terms(in)) {
      bool ok2 = true;
      const E dt = simp(diff(t, var, &ok2));
      push(r.steps, rule_of(t, var), to_infix(t) + " を " + var + " で微分すると " + to_infix(dt),
           t, dt);
    }
  } else {
    push(r.steps, rule_of(in, var), to_infix(in) + " を " + var + " で微分する", in, d);
  }
  r.value = expand(d);
  return r;
}

// ---------------------------------------------------------------- 積分
//
// 1 つの項を積分する。できなければ ok=false。
inline bool integ_term(const ex::E& t, const std::string& var, ex::E& out, std::string& rule);
inline bool by_parts(const ex::E& t, const std::string& var, ex::E& out, std::string& rule);

// a*var + b の形なら a と b を返す（1 次の中身。置換積分の代わり）
inline bool linear_in(const ex::E& e, const std::string& var, ex::Rat& a, ex::Rat& b) {
  using namespace ex;
  a = Rat(0);
  b = Rat(0);
  std::vector<E> ts;
  if (e->k == Kind::Add) ts = e->kids; else ts.push_back(e);
  for (const E& t : ts) {
    if (!has_var(t, var)) {
      if (!is_num(t)) return false;
      b = b + t->num;
      continue;
    }
    if (t->k == Kind::Sym && t->name == var) { a = a + Rat(1); continue; }
    if (t->k == Kind::Mul) {
      Rat c(1);
      int nv = 0;
      for (const E& f : t->kids) {
        if (is_num(f)) { c = c * f->num; continue; }
        if (f->k == Kind::Sym && f->name == var) { ++nv; continue; }
        return false;
      }
      if (nv != 1) return false;
      a = a + c;
      continue;
    }
    return false;
  }
  return true;
}

// var の多項式か（部分積分で「微分するほう」に回せる形か）
inline bool is_poly_in(const ex::E& e, const std::string& var) {
  using namespace ex;
  if (!has_var(e, var)) return is_num(e) || true;      // 定数はそのまま係数
  if (e->k == Kind::Sym) return e->name == var;
  if (e->k == Kind::Pow)
    return e->kids[0]->k == Kind::Sym && e->kids[0]->name == var && is_num(e->kids[1]) &&
           e->kids[1]->num.is_int() && !e->kids[1]->num.neg();
  return false;
}

// Add でも通す積分（部分積分の途中で出る「多項式 ÷ x」を積分するのに要る）
inline bool integ_any(const ex::E& e, const std::string& var, ex::E& out) {
  using namespace ex;
  std::vector<E> ts;
  if (e->k == Kind::Add) ts = e->kids; else ts.push_back(e);
  std::vector<E> parts;
  for (const E& t : ts) {
    E it;
    std::string r;
    if (!integ_term(t, var, it, r)) return false;
    parts.push_back(it);
  }
  out = add_n(parts);
  return true;
}

// **部分積分**（∫u v' = uv - ∫u'v）。u が多項式なので、微分を繰り返せば必ず 0 になり、
// 表のように交互に符号をつけて足すだけで終わる（教科書の「順次部分積分」）。
//   x sin(x) / x^2 e^x / x ln(x) のような形が解けるようになる。
inline bool by_parts(const ex::E& t, const std::string& var, ex::E& out, std::string& rule) {
  using namespace ex;
  if (t->k != Kind::Mul) return false;
  std::vector<E> us, gs;
  for (const E& f : t->kids) {
    if (is_poly_in(f, var)) us.push_back(f);
    else gs.push_back(f);
  }
  if (gs.size() != 1 || us.empty()) return false;
  const E u = mul_n(us);
  const E g = gs[0];
  if (!has_var(u, var)) return false;                  // 係数だけなら普通の積分で足りる

  // log は「微分するほう」に回す（∫x^n ln(x) は U ln(x) - ∫U/x）。
  // 中身が ax（定数項なし）のときだけ: そうでないと U/(ax+b) が多項式にならない
  if ((g->k == Kind::Fn) && (g->name == "ln" || (g->name == "log" && g->kids.size() == 2))) {
    const E arg = g->name == "ln" ? g->kids[0] : g->kids[1];
    Rat a(0), b(0);
    if (!linear_in(arg, var, a, b) || a.is_zero() || !b.is_zero()) return false;
    E U;
    if (!integ_any(u, var, U)) return false;
    E rest;
    if (!integ_any(expand(mul_n({U, pow_e(sym(var), num(Rat(-1)))})), var, rest)) return false;
    out = add_n({mul_n({U, g}), mul_n({num(Rat(-1)), rest})});
    rule = "部分積分";
    return true;
  }

  E U = u, V = g, acc = num(Rat(0));
  long long sign = 1;
  for (int i = 0; i <= 12; ++i) {
    E Vn;
    std::string r2;
    if (!integ_term(V, var, Vn, r2)) return false;
    V = simp(Vn);
    acc = add_n({acc, mul_n({num(Rat(sign)), U, V})});
    bool ok2 = true;
    U = simp(diff(U, var, &ok2));
    if (!ok2) return false;
    if (is_num(U) && U->num.is_zero()) {               // u^(k) = 0 になったら打ち切り
      out = acc;
      rule = "部分積分";
      return true;
    }
    sign = -sign;
  }
  return false;
}

inline bool integ_term(const ex::E& t, const std::string& var, ex::E& out, std::string& rule) {
  using namespace ex;
  if (!has_var(t, var)) {                              // 定数 -> c*x
    out = mul_n({t, sym(var)});
    rule = "定数の積分";
    return true;
  }
  // 係数をくくり出す（数 × 残り）
  if (t->k == Kind::Mul) {
    Rat c(1);
    std::vector<E> rest;
    for (const E& f : t->kids) {
      if (is_num(f)) c = c * f->num;
      else rest.push_back(f);
    }
    if (!(c == Rat(1)) && !rest.empty()) {
      E sub;
      if (!integ_term(rest.size() == 1 ? rest[0] : mul_n(rest), var, sub, rule)) return false;
      out = mul_n({num(c), sub});
      return true;
    }
  }
  if (t->k == Kind::Sym && t->name == var) {           // x -> x^2/2
    out = mul_n({num(Rat(1, 2)), pow_e(sym(var), num(Rat(2)))});
    rule = "x の n 乗の積分";
    return true;
  }
  if (t->k == Kind::Pow) {
    const E& b = t->kids[0];
    const E& p = t->kids[1];
    // 底が定数で指数が 1 次: a^(cx+d) -> a^(cx+d) / (c ln a)
    if (!has_var(b, var) && has_var(p, var)) {
      Rat c2(0), d2(0);
      if (!linear_in(p, var, c2, d2) || c2.is_zero()) return false;
      out = mul_n({num(Rat(1) / c2), pow_e(fn_e("ln", {b}), num(Rat(-1))), t});
      rule = "指数関数の積分";
      return true;
    }
    // 1/cos^2 と 1/sin^2（教科書の表にある形。中身は 1 次まで）
    if (is_num(p) && p->num == Rat(-2) && b->k == Kind::Fn && b->kids.size() == 1) {
      Rat a2(0), c2(0);
      if (linear_in(b->kids[0], var, a2, c2) && !a2.is_zero()) {
        if (b->name == "cos") {
          out = mul_n({num(Rat(1) / a2), fn_e("tan", {b->kids[0]})});
          rule = "1/cos^2 の積分";
          return true;
        }
        if (b->name == "sin") {
          out = mul_n({num(Rat(-1) / a2), pow_e(fn_e("tan", {b->kids[0]}), num(Rat(-1)))});
          rule = "1/sin^2 の積分";
          return true;
        }
      }
    }
    if (!is_num(p) || has_var(p, var)) return false;
    Rat a(0), c(0);
    if (!linear_in(b, var, a, c) || a.is_zero()) return false;   // 中身は 1 次だけ
    if (p->num == Rat(-1)) {                            // 1/(ax+b) -> ln|ax+b| / a
      out = mul_n({num(Rat(1) / a), fn_e("ln", {fn_e("abs", {b})})});
      rule = c.is_zero() ? "1/x の積分" : "1 次の中身の 1/(ax+b)";
      return true;
    }
    const Rat np = p->num + Rat(1);
    out = mul_n({num(Rat(1) / (a * np)), pow_e(b, num(np))});
    rule = (b->k == Kind::Sym) ? "x の n 乗の積分" : "1 次の中身の n 乗";
    return true;
  }
  if (t->k == Kind::Fn && t->kids.size() == 1) {
    const E& f = t->kids[0];
    Rat a(0), c(0);
    if (!linear_in(f, var, a, c) || a.is_zero()) return false;
    const E ia = num(Rat(1) / a);
    if (t->name == "sin") { out = mul_n({ia, num(Rat(-1)), fn_e("cos", {f})}); rule = "sin の積分"; return true; }
    if (t->name == "cos") { out = mul_n({ia, fn_e("sin", {f})}); rule = "cos の積分"; return true; }
    if (t->name == "exp") { out = mul_n({ia, fn_e("exp", {f})}); rule = "exp の積分"; return true; }
    // tan は「置換すると log になる」形: ∫tan = -ln|cos|
    if (t->name == "tan") {
      out = mul_n({ia, num(Rat(-1)), fn_e("ln", {fn_e("abs", {fn_e("cos", {f})})})});
      rule = "tan の積分";
      return true;
    }
    // ∫ln(ax+b) dx = ((ax+b)ln(ax+b) - (ax+b))/a （部分積分の結果を表として持つ）
    if (t->name == "ln") {
      out = mul_n({ia, add_n({mul_n({f, fn_e("ln", {f})}), mul_n({num(Rat(-1)), f})})});
      rule = "ln の積分";
      return true;
    }
    return false;
  }
  if (by_parts(t, var, out, rule)) return true;
  return false;
}

// 手順つきの積分（定積分なら lo..hi）
inline Result integrate(const ex::E& in, const std::string& want_var = "",
                        const ex::E& lo = ex::E(), const ex::E& hi = ex::E()) {
  using namespace ex;
  Result r;
  std::vector<std::string> vs;
  collect_syms(in, vs);
  const std::string var = !want_var.empty() ? want_var : (vs.empty() ? "x" : vs[0]);
  // **まず展開せずに試す**（`(2x + 1)^3` は `(2x + 1)^4/8` と書けるほうが教科書的。
  // 先に展開すると多項式になり、答えが定数だけ違う別の原始関数になる）
  std::vector<E> ts;
  {
    E whole;
    std::string rule0;
    if (integ_term(in, var, whole, rule0)) {
      ts.push_back(in);
    } else {
      const E e0 = expand(in);
      if (e0->k == Kind::Add) ts = disp_terms(e0); else ts.push_back(e0);
    }
  }
  const E e = ts.size() == 1 ? ts[0] : expand(in);
  if (ts.size() > 1) push(r.steps, "和の積分", "項ごとに積分して足す", e, e);
  std::vector<E> parts;
  for (const E& t : ts) {
    E it;
    std::string rule;
    if (!integ_term(t, var, it, rule)) {
      r.ok = false;
      r.why = to_infix(t) + " の積分は未対応（初等関数で書けない形かもしれない）";
      return r;
    }
    it = simp(it);
    push(r.steps, rule, to_infix(t) + " を積分すると " + to_infix(it), t, it);
    parts.push_back(it);
  }
  const E anti = simp(add_n(parts));
  r.ok = true;
  r.anti = anti;
  if (lo && hi) {
    r.definite = true;
    r.lo = lo;
    r.hi = hi;
    const E fb = simp(subst(anti, var, hi));
    const E fa = simp(subst(anti, var, lo));
    push(r.steps, "上端と下端を入れる",
         "F(" + to_infix(hi) + ") - F(" + to_infix(lo) + ") = " + to_infix(fb) + " - " +
             to_infix(fa),
         anti, add_n({fb, mul_n({num(Rat(-1)), fa})}));
    r.value = expand(add_n({fb, mul_n({num(Rat(-1)), fa})}));
  } else {
    r.value = anti;
  }
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false,
                                             bool is_integral = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  const std::string v = latex ? ex::to_latex(r.value) : ex::to_infix(r.value);
  if (!is_integral) { out.push_back(v); return out; }
  if (r.definite) { out.push_back(v); return out; }
  out.push_back(v + " + C");                 // 不定積分は積分定数をつける
  return out;
}

}  // namespace cal
