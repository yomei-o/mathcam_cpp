// 円の方程式 — 数学 II（図形と方程式）。
//
//   x^2 + y^2 - 4x + 2y - 4 = 0  ->  (x - 2)^2 + (y + 1)^2 = 9、中心 (2, -1)、半径 3
//
// やることは **2 つの変数それぞれの平方完成**だけ。右辺が負になれば「表す図形はない」、
// 0 なら「1 点」と言う（教科書もそこを場合分けする）。
#pragma once
#include "expr.hpp"
#include "solve.hpp"
#include <string>
#include <vector>

namespace cir {

using slv::Step;
using slv::push;

struct Result {
  bool ok = false;
  std::string why;
  std::string vx = "x", vy = "y";
  ex::E cx, cy;                   // 中心
  ex::E r2, r;                    // 半径の 2 乗と半径
  ex::E standard;                 // (x - p)^2 + (y - q)^2 = r^2
  std::string kind;               // 「円」「1 点」「図形なし」
  std::vector<Step> steps;
};

// e を「a(x^2 + y^2) + bx + cy + d」として係数を取り出す
inline bool coeffs(const ex::E& e, const std::string& vx, const std::string& vy, ex::Rat& a,
                   ex::Rat& b, ex::Rat& c, ex::Rat& d) {
  using namespace ex;
  a = b = c = d = Rat(0);
  Rat ax(0), ay(0);
  std::vector<E> ts;
  if (e->k == Kind::Add) ts = e->kids; else ts.push_back(e);
  for (const E& t : ts) {
    Rat k(1);
    std::string v;
    long long deg = 0;
    std::vector<E> fs;
    if (t->k == Kind::Mul) fs = t->kids; else fs.push_back(t);
    for (const E& f : fs) {
      if (is_num(f)) { k = k * f->num; continue; }
      E bs = f, p = num(Rat(1));
      if (f->k == Kind::Pow) { bs = f->kids[0]; p = f->kids[1]; }
      if (!is_sym(bs) || !is_num(p) || !p->num.is_int() || p->num.neg()) return false;
      if (!v.empty() && v != bs->name) return false;         // xy の項は円にならない
      v = bs->name;
      deg += p->num.n;
    }
    if (v.empty()) { d = d + k; continue; }
    if (v != vx && v != vy) return false;
    if (deg == 2) { (v == vx ? ax : ay) = (v == vx ? ax : ay) + k; continue; }
    if (deg == 1) { (v == vx ? b : c) = (v == vx ? b : c) + k; continue; }
    return false;                                            // 3 次以上
  }
  if (ax.is_zero() || !(ax == ay)) return false;             // x^2 と y^2 の係数が同じでないと円でない
  a = ax;
  return true;
}

inline Result circle(const ex::E& in, const std::string& want_x, const std::string& want_y) {
  using namespace ex;
  Result r;
  E lhs = in;
  if (in->k == Kind::Rel) {
    if (in->name != "=") { r.why = "= の式にしてください"; return r; }
    lhs = expand(sub(in->kids[0], in->kids[1]));
  } else {
    lhs = expand(in);
  }
  std::vector<std::string> vs;
  collect_syms(lhs, vs);
  std::sort(vs.begin(), vs.end());
  if (vs.size() != 2) { r.why = "2 変数（x と y）の式にしてください"; return r; }
  r.vx = want_x.empty() ? vs[0] : want_x;
  r.vy = want_y.empty() ? vs[1] : want_y;

  Rat a, b, c, d;
  if (!coeffs(lhs, r.vx, r.vy, a, b, c, d)) { r.why = "円の方程式の形ではありません"; return r; }
  if (!a.is_one()) {
    push(r.steps, "両辺を割る", "x^2 の係数を 1 にする（" + a.str() + " で割る）", in, in);
    b = b / a;
    c = c / a;
    d = d / a;
    a = Rat(1);
  }
  const Rat p = -b / Rat(2), q = -c / Rat(2);
  const Rat rr = p * p + q * q - d;                          // 半径の 2 乗
  const E X1 = pow_e(add_n({sym(r.vx), num(-p)}), num(Rat(2)));
  const E Y1 = pow_e(add_n({sym(r.vy), num(-q)}), num(Rat(2)));
  r.standard = eq(add_n({X1, Y1}), num(rr));
  push(r.steps, "平方完成", "x と y をそれぞれ平方完成する", lhs, r.standard);
  r.cx = num(p);
  r.cy = num(q);
  r.r2 = num(rr);
  r.ok = true;
  if (rr.neg()) {
    r.kind = "図形なし";
    push(r.steps, "右辺の符号", "右辺が負なので、この式を満たす点は無い", r.standard, r.standard);
    return r;
  }
  if (rr.is_zero()) {
    r.kind = "1 点";
    push(r.steps, "右辺の符号", "右辺が 0 なので、中心の 1 点だけ", r.standard, r.standard);
    return r;
  }
  r.kind = "円";
  r.r = pow_e(num(rr), num(Rat(1, 2)));
  return r;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::vector<std::string> answer_lines(const Result& r, bool latex = false) {
  std::vector<std::string> out;
  if (!r.ok) { out.push_back(r.why); return out; }
  const auto show = [&](const ex::E& e) { return latex ? ex::to_latex(e) : ex::to_infix(e); };
  out.push_back(show(r.standard));
  if (r.kind == "図形なし") { out.push_back("この式を満たす点はありません"); return out; }
  if (r.kind == "1 点") {
    out.push_back("1 点 (" + show(r.cx) + ", " + show(r.cy) + ") だけ");
    return out;
  }
  out.push_back("中心 (" + show(r.cx) + ", " + show(r.cy) + ")、半径 " + show(r.r));
  return out;
}

}  // namespace cir
