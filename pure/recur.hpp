// 漸化式 — 数学 B。a_(n+1) の式と初項から、一般項 a_n を出す。
//
// 教科書に出る 4 つの型だけを、教科書の名前で解く:
//
//   a_(n+1) = a_n + d        等差型      a_n = a_1 + (n - 1)d
//   a_(n+1) = r a_n          等比型      a_n = a_1 r^(n-1)
//   a_(n+1) = p a_n + q      特性方程式  a_n = (a_1 - c) p^(n-1) + c   （c = q/(1-p)）
//   a_(n+1) = a_n + f(n)     階差型      a_n = a_1 + Σ[k=1..n-1] f(k)
//
// 入力は「次の項の式」を a（= a_n）と n で書いたもの: `2a + 1` のように渡す。
// **出した一般項は必ず確かめる**（a_1 から数項を漸化式で回して突き合わせる）。合わなければ
// 答えを出さない。
#pragma once
#include "expr.hpp"
#include "seq.hpp"
#include "solve.hpp"
#include <string>
#include <vector>

namespace rec {

using seqs::Step;
using seqs::push;

struct Result {
  bool ok = false;
  std::string why;
  std::string type;               // 「等差型」「等比型」「特性方程式」「階差型」
  std::string var = "n";
  ex::E term;                     // 一般項 a_n
  ex::E sum;                      // 初項から第 n 項までの和（出せるときだけ）
  std::vector<Step> steps;
};

// next を「p·a + rest」に分ける（a は a_n、rest は a を含まない式）
inline bool split_pa(const ex::E& next, ex::Rat& p, ex::E& rest) {
  using namespace ex;
  p = Rat(0);
  std::vector<E> ks;
  std::vector<E> ts;
  if (next->k == Kind::Add) ts = next->kids; else ts.push_back(next);
  for (const E& t : ts) {
    if (!slv::has_v(t, "a")) { ks.push_back(t); continue; }
    if (t->k == Kind::Sym && t->name == "a") { p = p + Rat(1); continue; }
    if (t->k == Kind::Mul) {
      Rat c(1);
      int na = 0;
      for (const E& f : t->kids) {
        if (is_num(f)) { c = c * f->num; continue; }
        if (f->k == Kind::Sym && f->name == "a") { ++na; continue; }
        return false;                                // a·n のような形は未対応
      }
      if (na != 1) return false;
      p = p + c;
      continue;
    }
    return false;
  }
  rest = ks.empty() ? num(Rat(0)) : add_n(ks);
  return true;
}

// 一般項が漸化式を満たすか（a_1 から回して確かめる）
inline bool verify(const ex::E& term, const std::string& var, const ex::E& next,
                   const ex::Rat& a1, int upto = 6) {
  using namespace ex;
  Rat cur = a1;
  for (int i = 1; i <= upto; ++i) {
    const E got = simp(subst(term, var, num(Rat(i))));
    if (!is_num(got) || !(got->num == cur)) return false;
    E nx = subst(next, "a", num(cur));
    nx = simp(subst(nx, var, num(Rat(i))));
    if (!is_num(nx)) return false;
    cur = nx->num;
  }
  return true;
}

inline Result solve(const ex::E& next, const ex::Rat& a1, const std::string& want_var) {
  using namespace ex;
  Result r;
  r.var = want_var.empty() ? "n" : want_var;
  const std::string var = r.var;
  const E n = sym(var);
  Rat p;
  E rest;
  if (!split_pa(next, p, rest)) { r.why = "a_(n+1) = p a_n + f(n) の形にしてください"; return r; }
  const E shown = eq(sym("a"), next);

  if (p == Rat(1)) {
    // a_(n+1) = a_n + f(n)。f が定数なら等差、そうでなければ階差
    if (!slv::has_v(rest, var)) {
      r.type = "等差型";
      const Rat d = is_num(rest) ? rest->num : Rat(0);
      if (!is_num(rest)) { r.why = "公差が数になりません"; return r; }
      push(r.steps, "等差型", "a_(n+1) - a_n = " + d.str() + " で一定", shown, shown);
      r.term = seqs::nice(add_n({num(a1), mul_n({num(d), add_n({n, num(Rat(-1))})})}));
      push(r.steps, "一般項", "a_n = 初項 + (n - 1)×公差", r.term, r.term);
    } else {
      r.type = "階差型";
      push(r.steps, "階差型", "a_(n+1) - a_n = " + to_infix(rest) + " なので Σ で足す", shown,
           shown);
      const E fk = subst(rest, var, sym("k"));
      const seqs::Sum sm = seqs::sigma(fk, "k", num(Rat(1)), add_n({n, num(Rat(-1))}));
      if (!sm.ok) { r.why = sm.why; return r; }
      for (const Step& st : sm.steps) r.steps.push_back(st);
      r.term = seqs::nice(add_n({num(a1), sm.value}));
      push(r.steps, "一般項", "a_n = a_1 + Σ[k=1..n-1] f(k)（n >= 2）", r.term, r.term);
    }
  } else if (is_num(rest) && rest->num.is_zero()) {
    r.type = "等比型";
    push(r.steps, "等比型", "a_(n+1) / a_n = " + p.str() + " で一定", shown, shown);
    r.term = simp(mul_n({num(a1), pow_e(num(p), add_n({n, num(Rat(-1))}))}));
    push(r.steps, "一般項", "a_n = 初項 × 公比^(n - 1)", r.term, r.term);
  } else if (is_num(rest)) {
    // a_(n+1) = p a_n + q。特性方程式 x = px + q の解 c を引くと等比数列になる
    r.type = "特性方程式";
    const Rat q = rest->num;
    const Rat c = q / (Rat(1) - p);
    push(r.steps, "特性方程式",
         "x = " + p.str() + "x + " + q.str() + " を解くと x = " + c.str(),
         eq(sym("x"), add_n({mul_n({num(p), sym("x")}), num(q)})), num(c));
    push(r.steps, "等比数列に直す",
         "a_n - " + c.str() + " は公比 " + p.str() + " の等比数列（初項 " + (a1 - c).str() + "）",
         shown, shown);
    r.term = simp(add_n({mul_n({num(a1 - c), pow_e(num(p), add_n({n, num(Rat(-1))}))}), num(c)}));
    push(r.steps, "一般項", "a_n = (a_1 - c)·p^(n-1) + c", r.term, r.term);
  } else {
    r.why = "p a_n + q（q は数）か a_n + f(n) の形だけ解けます";
    return r;
  }

  if (!verify(r.term, var, next, a1)) {
    r.why = "出した一般項が漸化式に合いませんでした";
    return r;
  }
  // 和も出せるなら出す（多項式や等比なら Σ が通る）
  const seqs::Sum tot = seqs::sigma(subst(r.term, var, sym("k")), "k", num(Rat(1)), n);
  if (tot.ok) {
    r.sum = tot.value;
    push(r.steps, "初項から第 n 項までの和", "S_n = Σ[k=1..n] a_k = " + to_infix(tot.value),
         r.term, tot.value);
  }
  r.ok = true;
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  const auto show = [&](const ex::E& e) { return latex ? ex::to_latex(e) : ex::to_infix(e); };
  out.push_back(r.type);
  out.push_back("一般項: a_" + r.var + " = " + show(r.term));
  if (r.sum) out.push_back("和: S_" + r.var + " = " + show(r.sum));
  return out;
}

}  // namespace rec
