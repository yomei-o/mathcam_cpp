// 解く — 一次・二次方程式を「名前のついた書き換え」の列として解く。
//
// このファイルの本体は答えではなく**手順**である。答えだけなら 30 行で済む（係数を取り出して
// 解の公式に入れる）。読める手順にするために必要なのは:
//
//   * 変形の 1 手ごとに「規則の名前・変形前・変形後・一言説明」を残すこと
//   * 正規化（同類項をまとめる、約分する）を手順に**出さない**こと。人が紙に書かない操作を
//     並べると読めなくなる。出すのは人が紙に書く手（移項・両辺を割る・因数分解・解の公式）だけ
//   * 因数分解できるなら公式より先に試すこと。人はそう解くし、そのほうが手順が短い
//
// 対応範囲（RESUME の最初のゴール）: 変数 1 つの一次・二次方程式。係数は厳密有理数。
// 判別式が平方数でないときは sqrt を残した厳密な形で出す（0.618... にはしない）。
#pragma once
#include "expr.hpp"
#include <string>
#include <vector>

namespace slv {

struct Step {
  std::string rule;     // 規則の名前（「移項」「両辺を割る」…）。UI の見出しになる
  std::string note;     // 一言説明（「両辺から 3 を引く」）
  ex::E before, after;  // その手の前後。式木のまま持つので、後から LaTeX でも中置でも出せる
};

struct Solution {
  bool ok = false;
  std::string why;                 // ok=false のときの理由
  std::string kind;                // "linear" / "quadratic" / "identity" / "contradiction"
  std::string var;                 // 解いた変数
  std::vector<ex::E> roots;        // 解（厳密。重解は 1 つにまとめる）
  std::vector<Step> steps;
};

// ---------------------------------------------------------------- 多項式として見る

// e を var の多項式として係数に落とす。次数が高すぎる／var の入った関数がある等で
// 落とせないときは false（呼ぶ側が「対応外」として扱う）。
inline bool poly_coeffs(const ex::E& e, const std::string& var, std::vector<ex::Rat>& out) {
  using namespace ex;
  switch (e->k) {
    case Kind::Num:
      if (out.empty()) out.push_back(Rat(0));
      out[0] = out[0] + e->num;
      return true;
    case Kind::Sym: {
      if (e->name != var) return false;               // 別の変数が混ざる式は対応外
      if (out.size() < 2) out.resize(2, Rat(0));
      out[1] = out[1] + Rat(1);
      return true;
    }
    case Kind::Add: {
      for (const E& c : e->kids) if (!poly_coeffs(c, var, out)) return false;
      return true;
    }
    case Kind::Mul: {
      // 係数（var を含まない部分）と var^n に分ける
      Rat coef(1);
      long long deg = 0;
      for (const E& f : e->kids) {
        if (is_num(f)) { coef = coef * f->num; continue; }
        if (is_sym(f)) {
          if (f->name != var) return false;
          deg += 1;
          continue;
        }
        if (f->k == Kind::Pow && is_sym(f->kids[0]) && f->kids[0]->name == var &&
            is_num(f->kids[1]) && f->kids[1]->num.is_int() && f->kids[1]->num.n >= 0) {
          deg += f->kids[1]->num.n;
          continue;
        }
        return false;                                  // 1/x や sin(x) が混ざる
      }
      if (deg > 8) return false;
      if ((long long)out.size() < deg + 1) out.resize((size_t)deg + 1, Rat(0));
      out[(size_t)deg] = out[(size_t)deg] + coef;
      return true;
    }
    case Kind::Pow: {
      if (is_sym(e->kids[0]) && e->kids[0]->name == var && is_num(e->kids[1]) &&
          e->kids[1]->num.is_int() && e->kids[1]->num.n >= 0) {
        const long long d = e->kids[1]->num.n;
        if (d > 8) return false;
        if ((long long)out.size() < d + 1) out.resize((size_t)d + 1, Rat(0));
        out[(size_t)d] = out[(size_t)d] + Rat(1);
        return true;
      }
      return false;
    }
    default: return false;                             // Fn / Eq は対応外
  }
}

// 係数から式木に戻す（手順表示で「整理した式」を見せるため）
inline ex::E from_coeffs(const std::vector<ex::Rat>& c, const std::string& var) {
  using namespace ex;
  std::vector<E> terms;
  for (size_t i = 0; i < c.size(); ++i) {
    if (c[i].is_zero()) continue;
    E t = i == 0 ? num(c[i])
                 : mul_n({num(c[i]), i == 1 ? sym(var) : pow_e(sym(var), num((long long)i))});
    terms.push_back(t);
  }
  if (terms.empty()) return num(Rat(0));
  return add_n(terms);
}

// 整数の平方根（厳密に取れるときだけ）。判別式を sqrt のまま残すか畳むかの判断に使う
inline bool isqrt_exact(long long v, long long& out) {
  if (v < 0) return false;
  long long r = (long long)std::llround(std::sqrt((double)v));
  for (long long c = r > 2 ? r - 2 : 0; c <= r + 2; ++c)
    if (c * c == v) { out = c; return true; }
  return false;
}

// ---------------------------------------------------------------- 解く

// 手順の記録は「人が紙に書く手」だけ。正規化は黙って行う。
inline void push(std::vector<Step>& steps, const std::string& rule, const std::string& note,
                 const ex::E& before, const ex::E& after) {
  Step s;
  s.rule = rule;
  s.note = note;
  s.before = before;
  s.after = after;
  steps.push_back(s);
}

inline Solution solve(const ex::E& in, const std::string& want_var = "") {
  using namespace ex;
  Solution r;
  if (in->k != Kind::Eq) { r.why = "方程式ではありません（= がない）"; return r; }

  std::vector<std::string> syms;
  collect_syms(in, syms);
  if (syms.empty()) {
    // 3 = 3 のような式。真偽を答える
    const E d = expand(sub(in->kids[0], in->kids[1]));
    r.ok = true;
    r.kind = is_num(d) && d->num.is_zero() ? "identity" : "contradiction";
    return r;
  }
  r.var = want_var.empty() ? syms[0] : want_var;
  if (syms.size() > 1) { r.why = "変数が 2 つ以上あります（連立は未対応）"; return r; }

  // 1) 右辺を左辺に移す。人が紙に書く最初の手なので、これは手順に出す
  const E lhs = in->kids[0], rhs = in->kids[1];
  E diff = expand(sub(lhs, rhs));
  if (!is_num(rhs) || !rhs->num.is_zero())
    push(r.steps, "移項", "右辺を左辺に移して = 0 の形にする", in, eq(diff, num(Rat(0))));

  std::vector<Rat> c;
  if (!poly_coeffs(diff, r.var, c)) { r.why = "一次・二次の多項式に落とせません"; return r; }
  while (c.size() > 1 && c.back().is_zero()) c.pop_back();
  const size_t deg = c.empty() ? 0 : c.size() - 1;

  // 2) 分母を払う。係数に分数があると人は必ずこれをやる
  long long lcm = 1;
  for (const Rat& q : c) lcm = std::lcm(lcm, q.d);
  if (lcm > 1) {
    const E before = eq(from_coeffs(c, r.var), num(Rat(0)));
    for (Rat& q : c) q = q * Rat(lcm);
    push(r.steps, "分母を払う", "両辺に " + std::to_string(lcm) + " をかける", before,
         eq(from_coeffs(c, r.var), num(Rat(0))));
  }

  if (deg == 0) {
    r.ok = true;
    r.kind = c.empty() || c[0].is_zero() ? "identity" : "contradiction";
    return r;
  }

  if (deg == 1) {
    r.kind = "linear";
    // a x + b = 0  ->  x = -b/a
    const Rat a = c[1], b = c[0];
    const E before = eq(from_coeffs(c, r.var), num(Rat(0)));
    if (!b.is_zero()) {
      std::vector<Rat> c2{Rat(0), a};
      push(r.steps, "移項", "両辺から " + b.str() + " を引く", before,
           eq(from_coeffs(c2, r.var), num(-b)));
    }
    const E root = num(-b / a);
    if (!(a.is_one()))
      push(r.steps, "両辺を割る", "両辺を " + a.str() + " で割る",
           eq(mul_n({num(a), sym(r.var)}), num(-b)), eq(sym(r.var), root));
    r.roots.push_back(root);
    r.ok = true;
    return r;
  }

  if (deg == 2) {
    r.kind = "quadratic";
    const Rat a = c[2], b = c[1], cc = c[0];
    const E norm = eq(from_coeffs(c, r.var), num(Rat(0)));

    // 3) 因数分解を先に試す。人はそう解くし、手順が短くなる。
    //    整数係数のとき、判別式が平方数なら (a x - p)(x - q) の形に開ける
    const Rat disc = b * b - Rat(4) * a * cc;
    long long sq = 0;
    const bool square = disc.is_int() && isqrt_exact(disc.n, sq);
    const E x = sym(r.var);

    if (square && a.is_int() && b.is_int() && cc.is_int()) {
      // 解は (-b ± sq) / (2a)
      const Rat r1 = (-b + Rat(sq)) / (Rat(2) * a);
      const Rat r2 = (-b - Rat(sq)) / (Rat(2) * a);
      // 因数の書き方は人に合わせる: 根が 1/3 なら (x - 1/3) ではなく (3x - 1) と書く。
      // a(x - p/q) = (a/q)(qx - p) なので、分母を因数に吸わせると係数が 1 になることが多い
      // （3x^2 + 5x - 2 = 0 なら 3*(x - 1/3)*(x + 2) ではなく (3x - 1)(x + 2) になる）。
      auto factor_of = [&](const Rat& root) {
        return root.d == 1 ? add_n({x, num(-root)})
                           : add_n({mul_n({num(Rat(root.d)), x}), num(-Rat(root.n))});
      };
      const E f1 = factor_of(r1);
      const E f2 = factor_of(r2);
      const Rat lead = a / (Rat(r1.d) * Rat(r2.d));
      const E factored = lead.is_one() ? mul_n({f1, f2}) : mul_n({num(lead), f1, f2});
      push(r.steps, "因数分解", "左辺を積の形にする", norm, eq(factored, num(Rat(0))));
      push(r.steps, "積が 0",
           "積が 0 になるのは、どちらかの因数が 0 のとき: " + to_infix(f1) + " = 0 または " +
               to_infix(f2) + " = 0",
           eq(factored, num(Rat(0))), eq(f1, num(Rat(0))));
      r.roots.push_back(num(r1));
      if (!(r1 == r2)) r.roots.push_back(num(r2));
      r.ok = true;
      return r;
    }

    // 4) 因数分解できないときは解の公式。判別式の符号で場合分けする
    if (disc.neg()) {
      push(r.steps, "判別式", "D = b^2 - 4ac = " + disc.str() + " < 0 なので実数解はない",
           norm, norm);
      r.ok = true;
      r.kind = "quadratic";
      return r;                                    // roots は空（実数解なし）
    }
    // x = (-b ± sqrt(D)) / (2a) を厳密なまま組む
    const E sq_e = fn_e("sqrt", {num(disc)});
    const E denom = num(Rat(2) * a);
    const E r1 = simp(mul_n({add_n({num(-b), sq_e}), pow_e(denom, num(Rat(-1)))}));
    const E r2 = simp(mul_n({add_n({num(-b), neg(sq_e)}), pow_e(denom, num(Rat(-1)))}));
    push(r.steps, "解の公式",
         "a = " + a.str() + ", b = " + b.str() + ", c = " + cc.str() +
             " を x = (-b ± sqrt(b^2 - 4ac)) / (2a) に入れる",
         norm, eq(x, r1));
    r.roots.push_back(r1);
    if (!equal(r1, r2)) r.roots.push_back(r2);
    r.ok = true;
    return r;
  }

  r.why = "3 次以上は未対応";
  return r;
}

}  // namespace slv
