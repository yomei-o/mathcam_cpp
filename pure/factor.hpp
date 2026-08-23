// 因数分解 — 高校（数学 I）の中心。展開の逆をやる。
//
// solve.hpp / calc.hpp と同じ作法で、**答えだけでなく手順**を出す。手順の名前は教科書の
// 言い方（「共通因数でくくる」「和と差の積」「平方の形」「たすき掛け」「因数定理」）。
//
// 何ができるか:
//   共通因数    6x^2y + 9xy^2 -> 3xy(2x + 3y)
//   1 変数      x^2 + 5x + 6 -> (x + 2)(x + 3)、2x^2 - 3x - 2 -> (x - 2)(2x + 1)
//               x^3 - 6x^2 + 11x - 6 -> (x - 1)(x - 2)(x - 3)（因数定理）
//   和と差の積  4x^2 - 25 -> (2x - 5)(2x + 5)
//   2 変数の 2 次 x^2 + 12xy + 36y^2 -> (x + 6y)^2、x^2 - y^2 -> (x - y)(x + y)
//
// **有理数の範囲でしか分けない**（x^2 - 2 は分けない）。教科書もそう教える。
// 分けられないときは「これ以上分けられません」と言って、勝手に無理数を持ち出さない。
#pragma once
#include "expr.hpp"
#include "solve.hpp"
#include "seq.hpp"
#include <string>
#include <vector>

namespace fac {

struct Step {
  std::string rule;      // 規則の名前（「共通因数でくくる」「たすき掛け」…）
  std::string note;      // 一言説明
  ex::E before, after;   // その手の前後
};

struct Result {
  bool ok = false;
  std::string why;
  ex::E value;                  // 因数分解した式（分けられなければ元の式）
  std::vector<Step> steps;
  bool changed = false;         // 1 つでも分けられたか
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

// 項を「有理数の係数」と「変数 -> 次数」に割る（共通因数を探すため）
struct Mono {
  ex::Rat coef;
  std::vector<std::pair<std::string, long long>> pows;   // 変数名の順
};

inline long long deg_in(const Mono& m, const std::string& v) {
  for (const std::pair<std::string, long long>& p : m.pows)
    if (p.first == v) return p.second;
  return 0;
}

inline bool as_mono(const ex::E& t, Mono& m) {
  using namespace ex;
  m.coef = Rat(1);
  m.pows.clear();
  std::vector<E> fs;
  if (t->k == Kind::Mul) fs = t->kids; else fs.push_back(t);
  for (const E& f : fs) {
    if (is_num(f)) { m.coef = m.coef * f->num; continue; }
    E b = f, p = num(Rat(1));
    if (f->k == Kind::Pow) { b = f->kids[0]; p = f->kids[1]; }
    if (!is_sym(b) || !is_num(p) || !p->num.is_int() || p->num.neg()) return false;
    bool hit = false;
    for (std::pair<std::string, long long>& q : m.pows)
      if (q.first == b->name) { q.second += p->num.n; hit = true; break; }
    if (!hit) m.pows.push_back({b->name, p->num.n});
  }
  std::sort(m.pows.begin(), m.pows.end());
  return true;
}

inline ex::E mono_e(const Mono& m) {
  using namespace ex;
  std::vector<E> fs{num(m.coef)};
  for (const std::pair<std::string, long long>& p : m.pows)
    fs.push_back(p.second == 1 ? sym(p.first) : pow_e(sym(p.first), num(Rat(p.second))));
  return mul_n(fs);
}

// 1 変数の多項式を因数分解して、使った規則の名前も返す
inline bool factor_one_var(const ex::E& e, const std::string& var, ex::E& out,
                           std::string& rule) {
  using namespace ex;
  std::vector<Rat> c;
  if (!slv::poly_coeffs(e, var, c)) return false;
  while (c.size() > 1 && c.back().is_zero()) c.pop_back();
  if (c.size() < 3) return false;                    // 1 次以下は分けない
  const E f = seqs::factor_poly(c, var);
  // **(x - 1)^2 は Mul ではなく Pow になる**（mul_n が同じ因数をまとめるため）。
  // Mul だけを見ていたので x^2 - 2x + 1 が「分けられない」と出ていた。
  int nlin = 0;                                      // 分けた因数の数（重複も数える）
  std::vector<E> parts;
  std::vector<E> fs;
  if (f->k == Kind::Mul) fs = f->kids; else fs.push_back(f);
  for (const E& k : fs) {
    if (is_num(k)) continue;
    if (k->k == Kind::Pow && is_num(k->kids[1]) && k->kids[1]->num.is_int() &&
        k->kids[1]->num.n > 1 && k->kids[0]->k == Kind::Add) {
      nlin += (int)k->kids[1]->num.n;
      for (long long i = 0; i < k->kids[1]->num.n; ++i) parts.push_back(k->kids[0]);
      continue;
    }
    if (k->k != Kind::Add) return false;             // 分かれていない（元の多項式のまま）
    ++nlin;
    parts.push_back(k);
  }
  if (nlin < 2) return false;                        // 分かれていない
  out = f;
  const size_t deg = c.size() - 1;
  if (deg > 2) { rule = "因数定理"; return true; }
  // 2 次のときは教科書の呼び方に分ける
  if (parts.size() == 2 && equal(parts[0], parts[1])) { rule = "平方の形"; return true; }
  if (c[1].is_zero()) { rule = "和と差の積"; return true; }
  rule = "たすき掛け";
  return true;
}

// 2 変数の同次 2 次式 a x^2 + b xy + c y^2 を分ける
inline bool factor_hom2(const ex::E& e, const std::string& vx, const std::string& vy,
                        ex::E& out, std::string& rule) {
  using namespace ex;
  Rat a(0), b(0), c(0);
  std::vector<E> ts;
  if (e->k == Kind::Add) ts = e->kids; else ts.push_back(e);
  for (const E& t : ts) {
    Mono m;
    if (!as_mono(t, m)) return false;
    const long long dx = deg_in(m, vx), dy = deg_in(m, vy);
    if (dx + dy != 2) return false;                  // 同次 2 次だけ
    for (const std::pair<std::string, long long>& p : m.pows)
      if (p.first != vx && p.first != vy) return false;
    if (dx == 2) a = a + m.coef;
    else if (dy == 2) c = c + m.coef;
    else b = b + m.coef;
  }
  if (a.is_zero() || !a.is_int() || !b.is_int() || !c.is_int()) return false;
  const long long D = b.n * b.n - 4 * a.n * c.n;
  long long sq = 0;
  if (D < 0 || !ex::iroot(D, 2, sq)) return false;   // 有理数の範囲で分かれない
  // x = ((-b ± sq)/(2a)) y  →  (2a x + (b ∓ sq) y) の積 / (4a) を整数係数に直す
  const Rat r1 = Rat(-b.n + sq, 2 * a.n), r2 = Rat(-b.n - sq, 2 * a.n);
  const E f1 = add_n({mul_n({num(Rat(r1.d)), sym(vx)}), mul_n({num(Rat(-r1.n)), sym(vy)})});
  const E f2 = add_n({mul_n({num(Rat(r2.d)), sym(vx)}), mul_n({num(Rat(-r2.n)), sym(vy)})});
  const Rat lead = a / (Rat(r1.d) * Rat(r2.d));
  out = lead.is_one() ? mul_n({f1, f2}) : mul_n({num(lead), f1, f2});
  if (equal(f1, f2)) rule = "平方の形";
  else if (b.is_zero()) rule = "和と差の積";
  else rule = "たすき掛け";
  return true;
}

inline Result factor(const ex::E& in) {
  using namespace ex;
  Result r;
  const E e = expand(in);
  r.value = e;
  r.ok = true;
  if (is_num(e)) { r.why = "数なので因数分解できません"; return r; }

  // 1) 共通因数（係数の最大公約数と、各変数の最小の次数）
  std::vector<E> ts;
  if (e->k == Kind::Add) ts = disp_terms(e); else ts.push_back(e);
  std::vector<Mono> ms;
  bool all_mono = true;
  for (const E& t : ts) {
    Mono m;
    if (!as_mono(t, m)) { all_mono = false; break; }
    ms.push_back(m);
  }
  E rest = e;
  Mono common;
  common.coef = Rat(1);
  if (all_mono && !ms.empty()) {
    long long gn = 0, ld = 1;
    for (const Mono& m : ms) {
      gn = seqs::llgcd(gn, m.coef.n);
      ld = ld / seqs::llgcd(ld, m.coef.d) * m.coef.d;
    }
    Rat g = gn == 0 ? Rat(1) : Rat(gn, ld);
    if (ms[0].coef.neg()) g = -g;                    // 先頭が負なら - もくくり出す
    std::vector<std::string> vars;
    for (const std::pair<std::string, long long>& p : ms[0].pows) vars.push_back(p.first);
    Mono cm;
    cm.coef = g;
    for (const std::string& v : vars) {
      long long mn = -1;
      for (const Mono& m : ms) {
        const long long d = deg_in(m, v);
        mn = mn < 0 ? d : (d < mn ? d : mn);
      }
      if (mn > 0) cm.pows.push_back({v, mn});
    }
    if (!cm.coef.is_one() || !cm.pows.empty()) {
      const E ce = mono_e(cm);
      rest = expand(mul_n({e, pow_e(ce, num(Rat(-1)))}));
      if (!(is_num(ce) && ce->num.is_one())) {
        common = cm;
        push(r.steps, "共通因数でくくる",
             "どの項にもある " + to_infix(ce) + " を外に出す", e, mul_n({ce, rest}));
      }
    }
  }

  // 2) 残りを分ける
  std::vector<std::string> vs;
  collect_syms(rest, vs);
  std::sort(vs.begin(), vs.end());                   // 2 変数のとき x を先に見る（符号が揃う）
  E inner = rest;
  std::string rule;
  bool split = false;
  if (vs.size() == 1) {
    E out;
    if (factor_one_var(rest, vs[0], out, rule)) { inner = out; split = true; }
  } else if (vs.size() == 2) {
    E out;
    if (factor_hom2(rest, vs[0], vs[1], out, rule)) { inner = out; split = true; }
  }
  if (split) {
    const std::string note =
        rule == "和と差の積"   ? "a^2 - b^2 = (a + b)(a - b)"
        : rule == "平方の形"   ? "a^2 ± 2ab + b^2 = (a ± b)^2"
        : rule == "たすき掛け" ? "掛けて定数項、足して 1 次の係数になる 2 数を探す"
                               : "代入して 0 になる値から因数を見つける";
    push(r.steps, rule, note, rest, inner);
  }

  const E ce = mono_e(common);
  r.value = (is_num(ce) && ce->num.is_one()) ? inner : mul_n({ce, inner});
  r.changed = split || !(is_num(ce) && ce->num.is_one());
  if (!r.changed) r.why = "有理数の範囲ではこれ以上分けられません";
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  out.push_back(latex ? ex::to_latex(r.value) : ex::to_infix(r.value));
  if (!r.changed) out.push_back(r.why);
  return out;
}

}  // namespace fac
