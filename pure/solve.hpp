// 解く — 中学レベルの計算を「名前のついた書き換え」の列として解く。
//
// このファイルの本体は答えではなく**手順**である。答えだけなら 30 行で済む（係数を取り出して
// 解の公式に入れる）。読める手順にするために必要なのは:
//
//   * 変形の 1 手ごとに「規則の名前・変形前・変形後・一言説明」を残すこと
//   * 正規化（同類項をまとめる、約分する）を手順に**出さない**こと。人が紙に書かない操作を
//     並べると読めなくなる。出すのは人が紙に書く手（移項・両辺を割る・因数分解・解の公式）だけ
//   * 因数分解できるなら公式より先に試すこと。人はそう解くし、そのほうが手順が短い
//
// 対応範囲: 変数 1 つの一次・二次方程式、**一次不等式**、**2 元 1 次の連立方程式**、
// **連立不等式**。係数は厳密有理数。判別式が平方数でないときは sqrt を残した厳密な形で出す。
//
// 設計判断:
//
//   * **連立と不等式は 1 変数の方程式の解き方を再利用する**。消去や代入で 1 変数の式にしたら、
//     そこから先は solve_eq に投げてその手順を継ぎ足す。同じ変形を 2 か所に書くと、
//     片方だけ直して「連立のときだけ手順の文言が違う」という状態になる。
//   * **負の数で割ると不等号の向きが変わる**ことは、手順に理由つきで出す（中学生が最も
//     間違えるところなので、黙って向きを変えたら手順の意味がない）。
//   * 答えの文字列を作るのは answer_lines() の 1 か所だけ。CLI・WASM・パリティテストが
//     同じ関数を通る（文言が場所ごとに散ると、両言語の一致を縛れなくなる）。
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

// 1 本の範囲（境界が無い側は空）。二次不等式の「または」を表すのに使う
struct Range {
  ex::E lo, hi;
  bool lo_eq = false, hi_eq = false;
};

struct Solution {
  bool ok = false;
  std::string why;                 // ok=false のときの理由
  // 方程式:   "linear" / "quadratic" / "identity" / "contradiction"
  // 連立方程式: "system" / "dependent" / "contradiction"
  // 不等式:   "inequality" / "all" / "empty" / "point"
  std::string kind;
  std::string var;                 // 解いた変数（1 変数のとき）
  std::vector<ex::E> roots;        // 解（厳密。重解は 1 つにまとめる）
  std::vector<Step> steps;

  std::vector<std::string> vars;   // 連立で解いた変数の並び
  std::vector<ex::E> vals;         // vars と同じ長さ

  ex::E lo, hi;                    // 不等式の解の範囲（境界が無い側は空）
  bool lo_eq = false, hi_eq = false;  // 境界に等号を含むか

  // **二次不等式は答えが 2 つの範囲になる**（x < 2 または x > 3）。1 本で済むときは
  // 上の lo/hi をそのまま使い、2 本以上のときだけこちらに入れる（表示は range_text が見る）。
  std::vector<Range> ranges;
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
    default: return false;                             // Fn / Rel / Sys は対応外
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

// 多変数の一次式として見る: e = a[0]*vars[0] + ... + c。二次以上や 1/x が混ざれば false。
inline bool lin_coeffs(const ex::E& e, const std::vector<std::string>& vars,
                       std::vector<ex::Rat>& a, ex::Rat& c) {
  using namespace ex;
  a.assign(vars.size(), Rat(0));
  c = Rat(0);
  std::vector<E> terms;
  if (e->k == Kind::Add) terms = e->kids; else terms.push_back(e);
  for (const E& t : terms) {
    Rat coef(1);
    int which = -1;
    std::vector<E> fs;
    if (t->k == Kind::Mul) fs = t->kids; else fs.push_back(t);
    for (const E& f : fs) {
      if (is_num(f)) { coef = coef * f->num; continue; }
      if (is_sym(f)) {
        if (which >= 0) return false;                  // x*y は一次ではない
        for (size_t i = 0; i < vars.size(); ++i)
          if (vars[i] == f->name) which = (int)i;
        if (which < 0) return false;
        continue;
      }
      return false;                                    // Pow / Fn が混ざる
    }
    if (which < 0) c = c + coef;
    else a[(size_t)which] = a[(size_t)which] + coef;
  }
  return true;
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

inline ex::Rat at(const std::vector<ex::Rat>& v, size_t i) {
  return i < v.size() ? v[i] : ex::Rat(0);
}

// 「文字の項を左辺、数を右辺」に集める 1 手の説明。
//
// **引く量は左辺の定数で決まる**。両辺の差（左 - 右）で書くと、"3x - 5 > 1" に
// 「両辺に 6 を足す」と書いてしまう。6 を足すと 3x + 1 > 7 で、3x > 6 にはならない
// （実際に足すのは 5）。この 1 行を間違えると手順が数学として嘘になる。
struct MoveNote {
  std::string rule, note;
};
inline MoveNote move_note(const std::vector<ex::Rat>& L, const std::vector<ex::Rat>& R,
                          const std::string& var) {
  using namespace ex;
  const Rat bl = at(L, 0), ar = at(R, 1);
  if (!ar.is_zero() && !bl.is_zero()) return {"移項", "文字の項を左辺に、数を右辺に集める"};
  if (!ar.is_zero())
    return {"移項", "右辺の " + to_infix(mul_n({num(ar), sym(var)})) + " を左辺に移す"};
  if (!bl.is_zero())
    return {"移項", bl.neg() ? "両辺に " + (-bl).str() + " を足す"
                            : "両辺から " + bl.str() + " を引く"};
  return {"整理", "左辺の同類項をまとめる"};       // 移すものが無い（まとめただけ）
}

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

// 変数 1 つの一次・二次方程式
inline Solution solve_eq(const ex::E& in, const std::string& want_var = "") {
  using namespace ex;
  Solution r;

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
  if (syms.size() > 1) { r.why = "変数が 2 つ以上あります（連立にするなら , で区切る）"; return r; }

  const E lhs = in->kids[0], rhs = in->kids[1];
  const E x = sym(r.var);
  E diff = expand(sub(lhs, rhs));

  std::vector<Rat> c;
  if (!poly_coeffs(diff, r.var, c)) { r.why = "一次・二次の多項式に落とせません"; return r; }
  while (c.size() > 1 && c.back().is_zero()) c.pop_back();
  const size_t deg = c.empty() ? 0 : c.size() - 1;

  if (deg == 0) {
    r.ok = true;
    r.kind = c.empty() || c[0].is_zero() ? "identity" : "contradiction";
    return r;
  }

  if (deg == 1) {
    r.kind = "linear";
    // 一次は「= 0 の形」を経由しない。人は 3x - 5 = 1 を 3x = 6 と書く（3x - 6 = 0 とは書かない）。
    // 二次だけ = 0 の形にする（そこから因数分解・解の公式に入るので、人もそう書く）。
    std::vector<Rat> L, R;
    poly_coeffs(expand(lhs), r.var, L);
    poly_coeffs(expand(rhs), r.var, R);
    Rat a = c[1], b = c[0];

    E cur = in;
    const E moved = eq(mul_n({num(a), x}), num(-b));
    if (!equal(moved, in)) {                        // 既にその形なら手順に出さない
      const MoveNote mn = move_note(L, R, r.var);
      push(r.steps, mn.rule, mn.note, in, moved);
      cur = moved;
    }

    const long long lcm = std::lcm(a.d, b.d);
    if (lcm > 1) {
      a = a * Rat(lcm);
      b = b * Rat(lcm);
      const E after = eq(mul_n({num(a), x}), num(-b));
      push(r.steps, "分母を払う", "両辺に " + std::to_string(lcm) + " をかける", cur, after);
      cur = after;
    }

    const E root = num(-b / a);
    if (!a.is_one())
      push(r.steps, "両辺を割る", "両辺を " + a.str() + " で割る", cur, eq(x, root));
    r.roots.push_back(root);
    r.ok = true;
    return r;
  }

  // 二次: まず = 0 の形にしてから、因数分解 -> 解の公式
  if (!is_num(rhs) || !rhs->num.is_zero())
    push(r.steps, "移項", "右辺を左辺に移して = 0 の形にする", in, eq(diff, num(Rat(0))));
  {
    long long lcm = 1;
    for (const Rat& q : c) lcm = std::lcm(lcm, q.d);
    if (lcm > 1) {
      const E before = eq(from_coeffs(c, r.var), num(Rat(0)));
      for (Rat& q : c) q = q * Rat(lcm);
      push(r.steps, "分母を払う", "両辺に " + std::to_string(lcm) + " をかける", before,
           eq(from_coeffs(c, r.var), num(Rat(0))));
    }
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

// ---------------------------------------------------------------- 一次不等式

// 範囲を Solution に入れる（op は最終形の向き。x <= 3 なら hi=3, hi_eq=true）
inline void set_range(Solution& r, const std::string& op, const ex::E& bound) {
  if (op == "<" || op == "<=") { r.hi = bound; r.hi_eq = (op == "<="); }
  else { r.lo = bound; r.lo_eq = (op == ">="); }
  r.kind = "inequality";
}

// 二次式 a x^2 + b x + c = 0 の実数解を**小さい順**に返す。手順も足す
// （因数分解できるならそれ、できなければ解の公式。solve_eq と同じ言い方にする）。
// 返り値: 実数解の個数（0 / 1 / 2）
inline int quad_roots(const ex::Rat& a, const ex::Rat& b, const ex::Rat& cc,
                      const std::string& var, std::vector<Step>& steps, ex::E& r1, ex::E& r2) {
  using namespace ex;
  const E x = sym(var);
  const std::vector<Rat> co = {cc, b, a};
  const E norm = eq(from_coeffs(co, var), num(Rat(0)));
  const Rat disc = b * b - Rat(4) * a * cc;
  if (disc.neg()) {
    push(steps, "判別式", "D = b^2 - 4ac = " + disc.str() + " < 0 なので、= 0 になる x は無い",
         norm, norm);
    return 0;
  }
  long long sq = 0;
  const bool square = disc.is_int() && isqrt_exact(disc.n, sq);
  if (square && a.is_int() && b.is_int() && cc.is_int()) {
    Rat p = (-b + Rat(sq)) / (Rat(2) * a);
    Rat q = (-b - Rat(sq)) / (Rat(2) * a);
    if (q < p) { const Rat t = p; p = q; q = t; }
    auto factor_of = [&](const Rat& root) {
      return root.d == 1 ? add_n({x, num(-root)})
                         : add_n({mul_n({num(Rat(root.d)), x}), num(-Rat(root.n))});
    };
    const E f1 = factor_of(p), f2 = factor_of(q);
    const Rat lead = a / (Rat(p.d) * Rat(q.d));
    const E factored = lead.is_one() ? mul_n({f1, f2}) : mul_n({num(lead), f1, f2});
    push(steps, "因数分解", "左辺を積の形にする", norm, eq(factored, num(Rat(0))));
    r1 = num(p);
    r2 = num(q);
    return (p == q) ? 1 : 2;
  }
  const E sq_e = fn_e("sqrt", {num(disc)});
  const E denom = num(Rat(2) * a);
  E e1 = simp(mul_n({add_n({num(-b), neg(sq_e)}), pow_e(denom, num(Rat(-1)))}));
  E e2 = simp(mul_n({add_n({num(-b), sq_e}), pow_e(denom, num(Rat(-1)))}));
  if (approx(e2) < approx(e1)) { const E t = e1; e1 = e2; e2 = t; }
  push(steps, "解の公式",
       "a = " + a.str() + ", b = " + b.str() + ", c = " + cc.str() +
           " を x = (-b ± sqrt(b^2 - 4ac)) / (2a) に入れる",
       norm, eq(x, e1));
  r1 = e1;
  r2 = e2;
  return disc.is_zero() ? 1 : 2;
}

// 二次不等式（左辺に寄せて a x^2 + b x + c op 0 にしたあと）。
//
// **上に開いた放物線（a > 0）で考える**のが人のやり方。a < 0 なら両辺を -1 倍して
// 向きを変える（そこも手順に出す）。あとは「外側」か「内側」かだけ。
inline void solve_quad_ineq(Solution& r, std::vector<ex::Rat> c, std::string op,
                            const ex::E& shown) {
  using namespace ex;
  const std::string& var = r.var;
  const E x = sym(var);
  Rat a = c[2], b = c[1], cc = c[0];
  if (a.neg()) {
    a = -a; b = -b; cc = -cc;
    op = flip_op(op);
    const std::vector<Rat> co = {cc, b, a};
    push(r.steps, "両辺を -1 倍",
         "x^2 の係数を正にする。負の数を掛けるので不等号の向きが変わる", shown,
         rel(op, from_coeffs(co, var), num(Rat(0))));
  }
  E p, q;
  const int nr = quad_roots(a, b, cc, var, r.steps, p, q);
  const bool ge = (op == ">" || op == ">=");
  const bool with_eq = (op == ">=" || op == "<=");
  r.ok = true;
  if (nr == 0) {                                   // 放物線は x 軸と交わらない（常に正）
    r.kind = ge ? "all" : "empty";
    push(r.steps, "グラフの向き",
         ge ? "上に開いた放物線が x 軸より上にあるので、すべての実数で成り立つ"
            : "上に開いた放物線が x 軸より上にあるので、成り立つ x は無い",
         shown, shown);
    return;
  }
  if (nr == 1) {                                   // 接する
    if (ge && with_eq) {                           // >= 0 は常に成り立つ
      r.kind = "all";
      push(r.steps, "グラフの向き", "接するだけなので、= も含めればすべての実数で成り立つ",
           shown, shown);
      return;
    }
    if (!ge && !with_eq) {                         // < 0 は成り立たない
      r.kind = "empty";
      push(r.steps, "グラフの向き", "接するだけなので、< 0 になる x は無い", shown, shown);
      return;
    }
    if (!ge && with_eq) {                          // <= 0 は接点のみ
      r.kind = "point";
      r.roots.push_back(p);
      push(r.steps, "グラフの向き", "接点だけが解", eq(x, p), eq(x, p));
      return;
    }
    // > 0 は接点以外すべて
    Range lo_side, hi_side;
    hi_side.hi = p;
    lo_side.lo = p;
    r.ranges.push_back(hi_side);
    r.ranges.push_back(lo_side);
    r.kind = "inequality";
    push(r.steps, "グラフの向き", "接点では 0 になるので、そこだけ外す", shown, shown);
    return;
  }
  // 交点が 2 つ。外側か内側か
  r.kind = "inequality";
  if (ge) {
    Range left, right;
    left.hi = p;
    left.hi_eq = with_eq;
    right.lo = q;
    right.lo_eq = with_eq;
    r.ranges.push_back(left);
    r.ranges.push_back(right);
    push(r.steps, "グラフの向き",
         "上に開いた放物線なので、2 つの解の**外側**で 0 より大きい", shown, shown);
  } else {
    r.lo = p;
    r.hi = q;
    r.lo_eq = with_eq;
    r.hi_eq = with_eq;
    push(r.steps, "グラフの向き",
         "上に開いた放物線なので、2 つの解の**間**で 0 より小さい", shown, shown);
  }
}

inline Solution solve_ineq(const ex::E& in, const std::string& want_var = "") {
  using namespace ex;
  Solution r;
  std::string op = in->name;

  std::vector<std::string> syms;
  collect_syms(in, syms);
  const E diff0 = expand(sub(in->kids[0], in->kids[1]));   // diff0 op 0
  if (syms.empty()) {
    // 3 < 5 のような式。真偽を答える
    const double v = approx(diff0);
    const bool t = op == "<" ? v < 0 : op == "<=" ? v <= 0 : op == ">" ? v > 0 : v >= 0;
    r.ok = true;
    r.kind = t ? "all" : "empty";
    return r;
  }
  r.var = want_var.empty() ? syms[0] : want_var;
  if (syms.size() > 1) { r.why = "変数が 2 つ以上あります（連立にするなら , で区切る）"; return r; }

  std::vector<Rat> c;
  if (!poly_coeffs(diff0, r.var, c)) { r.why = "一次式に落とせません"; return r; }
  while (c.size() > 1 && c.back().is_zero()) c.pop_back();
  const size_t deg = c.empty() ? 0 : c.size() - 1;
  if (deg > 2) { r.why = "三次以上の不等式は未対応"; return r; }
  if (deg == 2) {
    // 二次不等式。まず左辺に寄せた形を見せてから解く
    const ex::E shown = rel(op, from_coeffs(c, r.var), num(Rat(0)));
    if (!equal(shown, in)) push(r.steps, "移項", "右辺を左辺に移して 0 と比べる形にする", in, shown);
    solve_quad_ineq(r, c, op, shown);
    return r;
  }

  const E x = sym(r.var);
  if (deg == 0) {                                   // x が消えた（0 < 1 のような形）
    const Rat b = c.empty() ? Rat(0) : c[0];
    const bool t = op == "<" ? b < Rat(0)
                 : op == "<=" ? (b < Rat(0) || b.is_zero())
                 : op == ">" ? Rat(0) < b
                 : (Rat(0) < b || b.is_zero());
    r.ok = true;
    r.kind = t ? "all" : "empty";
    return r;
  }

  Rat a = c[1], b = c[0];
  // 1) 移項して a x (op) -b の形にする。人が紙に書く最初の手。
  //    ただし**既にその形なら手順に出さない**（"3x > 6" に「移項」と書いても何も動かない）
  E cur = in;
  {
    const E after = rel(op, mul_n({num(a), x}), num(-b));
    if (!equal(after, in)) {
      const std::string note = b.neg() ? "両辺に " + (-b).str() + " を足す"
                                       : "両辺から " + b.str() + " を引く";
      push(r.steps, "移項", b.is_zero() ? "右辺を左辺に移す" : note, in, after);
      cur = after;
    }
  }

  // 2) 分母を払う。かけるのは**正の数**なので不等号の向きは変わらない
  const long long lcm = std::lcm(a.d, b.d);
  if (lcm > 1) {
    a = a * Rat(lcm);
    b = b * Rat(lcm);
    const E after = rel(op, mul_n({num(a), x}), num(-b));
    push(r.steps, "分母を払う",
         "両辺に " + std::to_string(lcm) + " をかける（正の数なので不等号の向きは変わらない）",
         cur, after);
    cur = after;
  }

  // 3) 両辺を a で割る。**負の数で割るときは向きが変わる**（ここが中学の山場）
  const Rat bound = -b / a;
  if (!a.is_one()) {
    if (a.neg()) {
      op = flip_op(op);
      push(r.steps, "両辺を割る（負の数）",
           "両辺を " + a.str() + " で割る。負の数で割るので不等号の向きが変わる", cur,
           rel(op, x, num(bound)));
    } else {
      push(r.steps, "両辺を割る", "両辺を " + a.str() + " で割る", cur, rel(op, x, num(bound)));
    }
  }
  set_range(r, op, num(bound));
  r.ok = true;
  return r;
}

// ---------------------------------------------------------------- 連立不等式

// 2 つの範囲の重なりを取る。境界が同じ値なら、**厳しい方**（等号を含まない方）が残る。
// 解を「範囲の列」に直す（二次不等式は 2 本になることがある）。
// **境界の大小は approx で比べる**（sqrt(2) のような無理数が境界に出るので、有理数の比較では
// 足りない。等しいかどうかだけは式として equal も見る）。
inline std::vector<Range> as_ranges(const Solution& s) {
  std::vector<Range> out;
  if (s.kind == "empty") return out;
  if (s.kind == "all") { out.push_back(Range()); return out; }
  if (s.kind == "point") {
    if (!s.roots.empty()) {
      Range g;
      g.lo = g.hi = s.roots[0];
      g.lo_eq = g.hi_eq = true;
      out.push_back(g);
    }
    return out;
  }
  if (!s.ranges.empty()) return s.ranges;
  Range g;
  g.lo = s.lo; g.hi = s.hi; g.lo_eq = s.lo_eq; g.hi_eq = s.hi_eq;
  if (g.lo || g.hi) out.push_back(g);
  else out.push_back(Range());
  return out;
}

// 2 本の範囲の重なり。空なら false
inline bool range_meet(const Range& a, const Range& b, Range& out) {
  using namespace ex;
  out = Range();
  // 下端は大きいほう
  if (a.lo && b.lo) {
    const double xa = approx(a.lo), xb = approx(b.lo);
    if (xa > xb) { out.lo = a.lo; out.lo_eq = a.lo_eq; }
    else if (xb > xa) { out.lo = b.lo; out.lo_eq = b.lo_eq; }
    else { out.lo = a.lo; out.lo_eq = a.lo_eq && b.lo_eq; }   // 同じ値なら厳しいほう
  } else if (a.lo) { out.lo = a.lo; out.lo_eq = a.lo_eq; }
  else if (b.lo) { out.lo = b.lo; out.lo_eq = b.lo_eq; }
  // 上端は小さいほう
  if (a.hi && b.hi) {
    const double xa = approx(a.hi), xb = approx(b.hi);
    if (xa < xb) { out.hi = a.hi; out.hi_eq = a.hi_eq; }
    else if (xb < xa) { out.hi = b.hi; out.hi_eq = b.hi_eq; }
    else { out.hi = a.hi; out.hi_eq = a.hi_eq && b.hi_eq; }
  } else if (a.hi) { out.hi = a.hi; out.hi_eq = a.hi_eq; }
  else if (b.hi) { out.hi = b.hi; out.hi_eq = b.hi_eq; }
  if (out.lo && out.hi) {
    const double lo = approx(out.lo), hi = approx(out.hi);
    if (hi < lo) return false;
    if (hi == lo && !(out.lo_eq && out.hi_eq)) return false;   // 境界が開いていれば 1 点も残らない
  }
  return true;
}

// 範囲の列どうしの重なり（「または」を含む答えの共通部分）
inline std::vector<Range> meet_all(const std::vector<Range>& a, const std::vector<Range>& b) {
  std::vector<Range> out;
  for (const Range& x : a)
    for (const Range& y : b) {
      Range g;
      if (range_meet(x, y, g)) out.push_back(g);
    }
  return out;
}

inline Solution solve_sys_ineq(const std::vector<ex::E>& rels, const std::string& want_var) {
  using namespace ex;
  Solution r;
  static const char* ord[] = {"1 つ目", "2 つ目", "3 つ目", "4 つ目"};
  std::vector<Range> acc{Range()};                 // 最初は「すべての実数」
  for (size_t i = 0; i < rels.size(); ++i) {
    const Solution s = solve_ineq(rels[i], want_var);
    if (!s.ok) { r.why = s.why; return r; }
    if (r.var.empty()) r.var = s.var;
    if (!s.var.empty() && s.var != r.var) { r.why = "変数が揃っていません"; return r; }
    const std::string label = i < 4 ? ord[i] : "次";
    push(r.steps, label + "の不等式", "まずこれを解く", rels[i], rels[i]);
    for (const Step& st : s.steps) r.steps.push_back(st);
    acc = meet_all(acc, as_ranges(s));
    if (acc.empty()) {                             // 1 本でも成り立たなければ全体が解なし
      push(r.steps, "共通範囲", "重なりが無いので解なし", num(Rat(0)), num(Rat(0)));
      r.ok = true;
      r.kind = "empty";
      return r;
    }
  }
  r.ok = true;
  if (acc.size() == 1) {
    const Range& g = acc[0];
    if (!g.lo && !g.hi) { r.kind = "all"; return r; }
    if (g.lo && g.hi && approx(g.lo) == approx(g.hi)) {   // x >= 2 かつ x <= 2 → 1 点
      push(r.steps, "共通範囲", "両端が同じ値なので解は 1 つ", eq(sym(r.var), g.lo),
           eq(sym(r.var), g.lo));
      r.roots.push_back(g.lo);
      r.kind = "point";
      return r;
    }
    r.lo = g.lo; r.hi = g.hi; r.lo_eq = g.lo_eq; r.hi_eq = g.hi_eq;
  } else {
    r.ranges = acc;
  }
  r.kind = "inequality";
  // 範囲は「x > 2 かつ x <= 5」の 2 本として持つ（a < x <= b の連鎖は木に無い。
  // 連鎖を木に入れると、印字・解析・パーサの全部に例外が増えるので、答えの文字列だけで作る）
  const E body = sym(r.var);
  const Range& g0 = acc[0];
  const E lo_rel = g0.lo ? rel(g0.lo_eq ? ">=" : ">", body, g0.lo) : ex::E();
  const E hi_rel = g0.hi ? rel(g0.hi_eq ? "<=" : "<", body, g0.hi) : ex::E();
  const E shown = (lo_rel && hi_rel) ? sys({lo_rel, hi_rel}) : (lo_rel ? lo_rel : hi_rel);
  if (shown) push(r.steps, "共通範囲", "それぞれの範囲の重なりを取る", shown, shown);
  return r;
}

// ---------------------------------------------------------------- 連立方程式（2 元 1 次）

// 「a x + b y = c」の形に整えたものを式木で返す（手順表示のため）
inline ex::E lin_eq_tree(const std::vector<ex::Rat>& a, const std::vector<std::string>& vars,
                         const ex::Rat& rhs) {
  using namespace ex;
  std::vector<E> ts;
  for (size_t i = 0; i < a.size(); ++i)
    if (!a[i].is_zero()) ts.push_back(mul_n({num(a[i]), sym(vars[i])}));
  const E l = ts.empty() ? num(Rat(0)) : add_n(ts);
  return eq(l, num(rhs));
}

inline Solution solve_system(const std::vector<ex::E>& rels, const std::string& want_var) {
  using namespace ex;
  Solution r;
  if (rels.size() != 2) { r.why = "2 つの式の連立だけ対応しています"; return r; }

  std::vector<std::string> vars;
  for (const E& e : rels) collect_syms(e, vars);
  // 答えは x, y の順に出す（出てきた順だと "y = 3, x = 2" と並ぶ。人は x から書く）
  std::sort(vars.begin(), vars.end());
  if (vars.size() != 2) {
    r.why = vars.size() < 2 ? "変数が 1 つしかありません" : "3 元以上の連立は未対応";
    return r;
  }
  (void)want_var;

  // 各式を a x + b y = c の形にする（左辺 - 右辺 を一次式として読む）
  std::vector<std::vector<Rat>> A(2);
  std::vector<Rat> C(2);
  for (int i = 0; i < 2; ++i) {
    Rat c0;
    if (!lin_coeffs(expand(sub(rels[(size_t)i]->kids[0], rels[(size_t)i]->kids[1])), vars,
                    A[(size_t)i], c0)) {
      r.why = "一次の連立方程式に落とせません";
      return r;
    }
    C[(size_t)i] = -c0;                            // a x + b y = -c0
  }

  // 0) 整理（入力が既にこの形なら手順に出さない）
  std::vector<E> norm{lin_eq_tree(A[0], vars, C[0]), lin_eq_tree(A[1], vars, C[1])};
  const E in_tree = sys(rels);
  const E norm_tree = sys(norm);
  if (!equal(in_tree, norm_tree))
    push(r.steps, "整理", "どちらも「x と y の項 = 数」の形に直す", in_tree, norm_tree);

  // 1) 分母を払う（式ごとに）
  for (int i = 0; i < 2; ++i) {
    long long l = C[(size_t)i].d;
    for (const Rat& q : A[(size_t)i]) l = std::lcm(l, q.d);
    if (l > 1) {
      for (Rat& q : A[(size_t)i]) q = q * Rat(l);
      C[(size_t)i] = C[(size_t)i] * Rat(l);
      const std::string which = i == 0 ? "1 つ目" : "2 つ目";
      const E before = sys({norm[0], norm[1]});
      norm[(size_t)i] = lin_eq_tree(A[(size_t)i], vars, C[(size_t)i]);
      push(r.steps, "分母を払う", which + "の式に " + std::to_string(l) + " をかける", before,
           sys({norm[0], norm[1]}));
    }
  }

  // 2) 解があるか（行列式）
  const Rat det = A[0][0] * A[1][1] - A[1][0] * A[0][1];
  if (det.is_zero()) {
    const Rat cross = A[0][0] * C[1] - A[1][0] * C[0];
    const Rat cross2 = A[0][1] * C[1] - A[1][1] * C[0];
    r.ok = true;
    if (cross.is_zero() && cross2.is_zero()) {
      r.kind = "dependent";
      push(r.steps, "係数を比べる", "2 つの式が同じものを表しているので、解は無限にある",
           norm_tree, norm_tree);
    } else {
      r.kind = "contradiction";
      push(r.steps, "係数を比べる",
           "x と y の係数の比が同じで右辺の比だけ違うので、同時に成り立つ値は無い", norm_tree,
           norm_tree);
    }
    return r;
  }

  // 3) 片方の式に文字が 1 つしか無いなら、消す作業は要らない（そのまま解ける）。
  //    ここを見落とすと、係数 0 の変数を消そうとして 0 で割ることになる（実際に踏んだ）。
  int single_i = -1, single_v = -1;
  for (int i = 0; i < 2 && single_i < 0; ++i) {
    int nz = 0, w = -1;
    for (int v = 0; v < 2; ++v)
      if (!A[(size_t)i][(size_t)v].is_zero()) { ++nz; w = v; }
    if (nz == 1) { single_i = i; single_v = w; }
  }

  // 4) 代入法が自然な形（片方が「y = …」と書かれている）ならそちらを使う。
  //    人は y = 2x - 1 を見たら代入する。加減法にすると手順が遠回りになる。
  int subst_i = -1, subst_v = -1;
  for (int i = 0; i < 2 && subst_i < 0; ++i)
    for (int v = 0; v < 2; ++v) {
      const E& lhs = rels[(size_t)i]->kids[0];
      if (is_sym(lhs) && lhs->name == vars[(size_t)v]) {
        std::vector<std::string> rs;
        collect_syms(rels[(size_t)i]->kids[1], rs);
        if (std::find(rs.begin(), rs.end(), vars[(size_t)v]) == rs.end()) {
          subst_i = i;
          subst_v = v;
          break;
        }
      }
    }

  E one_var;                                        // 1 変数になった式
  std::string solved_var;                           // その式の変数
  if (single_i >= 0) {
    one_var = norm[(size_t)single_i];
    solved_var = vars[(size_t)single_v];
    push(r.steps, "そのまま解ける",
         (single_i == 0 ? std::string("1 つ目") : std::string("2 つ目")) + "の式には " +
             solved_var + " しか無いので、先にこれを解く",
         sys({norm[0], norm[1]}), one_var);
  } else if (subst_i >= 0) {
    const int other = 1 - subst_i;
    const std::string sv = vars[(size_t)subst_v];
    const E val = rels[(size_t)subst_i]->kids[1];
    const E lhs2 = subst(rels[(size_t)other]->kids[0], sv, val);
    const E rhs2 = subst(rels[(size_t)other]->kids[1], sv, val);
    one_var = eq(lhs2, rhs2);
    solved_var = vars[(size_t)(1 - subst_v)];
    push(r.steps, "代入法",
         sv + " = " + to_infix(val) + " を" + (other == 0 ? "1 つ目" : "2 つ目") + "の式に入れる",
         sys({rels[0], rels[1]}), one_var);
  } else {
    // 加減法: 消す変数の係数の絶対値を揃えてから、辺々を足す／引く。
    // 消す変数は**係数を揃えるのが楽な方**（人もそうする）
    auto ab = [](long long v) { return v < 0 ? -v : v; };
    const int elim =
        std::lcm(ab(A[0][1].n), ab(A[1][1].n)) < std::lcm(ab(A[0][0].n), ab(A[1][0].n)) ? 1 : 0;
    const int keep = 1 - elim;
    const long long ea = ab(A[0][(size_t)elim].n), eb = ab(A[1][(size_t)elim].n);
    const long long L = std::lcm(ea, eb);
    const long long m0 = L / ea, m1 = L / eb;
    if (m0 != 1 || m1 != 1) {
      const E before = sys({norm[0], norm[1]});
      for (Rat& q : A[0]) q = q * Rat(m0);
      C[0] = C[0] * Rat(m0);
      for (Rat& q : A[1]) q = q * Rat(m1);
      C[1] = C[1] * Rat(m1);
      norm[0] = lin_eq_tree(A[0], vars, C[0]);
      norm[1] = lin_eq_tree(A[1], vars, C[1]);
      std::string note = vars[(size_t)elim] + " の係数を揃える（";
      note += m0 != 1 ? "1 つ目を " + std::to_string(m0) + " 倍" : "1 つ目はそのまま";
      note += m1 != 1 ? "、2 つ目を " + std::to_string(m1) + " 倍）" : "、2 つ目はそのまま）";
      push(r.steps, "係数を揃える", note, before, sys({norm[0], norm[1]}));
    }
    const bool same_sign = (A[0][(size_t)elim].n > 0) == (A[1][(size_t)elim].n > 0);
    std::vector<Rat> a2(2);
    Rat c2;
    if (same_sign) {
      for (int v = 0; v < 2; ++v) a2[(size_t)v] = A[0][(size_t)v] - A[1][(size_t)v];
      c2 = C[0] - C[1];
    } else {
      for (int v = 0; v < 2; ++v) a2[(size_t)v] = A[0][(size_t)v] + A[1][(size_t)v];
      c2 = C[0] + C[1];
    }
    one_var = lin_eq_tree(a2, vars, c2);
    solved_var = vars[(size_t)keep];
    push(r.steps, "加減法",
         std::string("辺々を") + (same_sign ? "引く" : "足す") + "と " + vars[(size_t)elim] +
             " が消える",
         sys({norm[0], norm[1]}), one_var);
  }

  // 5) 1 変数になったら、方程式の解き方をそのまま使う（手順もそのまま継ぎ足す）
  const Solution s1 = solve_eq(one_var, solved_var);
  if (!s1.ok || s1.roots.size() != 1) {
    r.why = s1.ok ? "連立の途中で 1 つに決まりませんでした" : s1.why;
    return r;
  }
  for (const Step& st : s1.steps) r.steps.push_back(st);
  const E v1 = s1.roots[0];

  // 6) もう片方は代入して求める。**入れる先は「もう片方の文字が入っている式」**
  //    （いつも 1 つ目に入れると、1 つ目がその文字を含まないとき 3 = 3 になって解けない）
  const std::string other_var = vars[0] == solved_var ? vars[1] : vars[0];
  const size_t ov = vars[0] == other_var ? 0 : 1;
  const size_t src = A[0][ov].is_zero() ? 1 : 0;
  const E base = rels[src];
  const E lhs3 = subst(base->kids[0], solved_var, v1);
  const E rhs3 = subst(base->kids[1], solved_var, v1);
  const E eq2 = eq(lhs3, rhs3);
  push(r.steps, "代入",
       solved_var + " = " + to_infix(v1) + " を" + (src == 0 ? "1 つ目" : "2 つ目") +
           "の式に入れる",
       eq(base->kids[0], base->kids[1]), eq2);
  const Solution s2 = solve_eq(eq2, other_var);
  if (!s2.ok || s2.roots.size() != 1) {
    r.why = s2.ok ? "連立の途中で 1 つに決まりませんでした" : s2.why;
    return r;
  }
  for (const Step& st : s2.steps) r.steps.push_back(st);

  r.kind = "system";
  r.vars = vars;
  r.vals.assign(2, num(Rat(0)));
  for (size_t i = 0; i < 2; ++i)
    r.vals[i] = vars[i] == solved_var ? v1 : s2.roots[0];
  r.ok = true;
  return r;
}

// ---------------------------------------------------------------- 入口

inline Solution solve(const ex::E& in, const std::string& want_var = "") {
  using namespace ex;
  Solution r;
  if (in->k == Kind::Sys) {
    int eqs = 0, ineqs = 0;
    for (const E& c : in->kids) {
      if (c->k != Kind::Rel) { r.why = "連立の中に関係式でないものがあります"; return r; }
      if (c->name == "=") ++eqs; else ++ineqs;
    }
    if (eqs && ineqs) { r.why = "方程式と不等式を混ぜた連立は未対応"; return r; }
    return ineqs ? solve_sys_ineq(in->kids, want_var) : solve_system(in->kids, want_var);
  }
  if (in->k != Kind::Rel) { r.why = "方程式ではありません（= も不等号もない）"; return r; }
  if (in->name != "=") return solve_ineq(in, want_var);
  return solve_eq(in, want_var);
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**。CLI・WASM・パリティテストが同じ関数を通る。
inline std::string show_e(const ex::E& e, bool latex) {
  return latex ? ex::to_latex(e) : ex::to_infix(e);
}

// 1 本ぶんの範囲の書き方
inline std::string one_range(const std::string& var, const Range& g, bool latex) {
  const std::string le = latex ? " \\le " : " <= ", lt = " < ";
  const std::string ge = latex ? " \\ge " : " >= ", gt = " > ";
  if (g.lo && g.hi)
    return show_e(g.lo, latex) + (g.lo_eq ? le : lt) + var + (g.hi_eq ? le : lt) +
           show_e(g.hi, latex);
  if (g.lo) return var + (g.lo_eq ? ge : gt) + show_e(g.lo, latex);
  if (g.hi) return var + (g.hi_eq ? le : lt) + show_e(g.hi, latex);
  return "すべての実数";
}

inline std::string range_text(const Solution& s, bool latex = false) {
  using namespace ex;
  // **答えが 2 つの範囲になることがある**（二次不等式の「または」）
  if (!s.ranges.empty()) {
    std::string out;
    for (size_t i = 0; i < s.ranges.size(); ++i) {
      if (i) out += " または ";
      out += one_range(s.var, s.ranges[i], latex);
    }
    return out;
  }
  // 不等号は中置と同じ書き方（LaTeX のときだけ記号を直す）
  const std::string le = latex ? " \\le " : " <= ", lt = " < ";
  const std::string ge = latex ? " \\ge " : " >= ", gt = " > ";
  if (s.lo && s.hi)
    return show_e(s.lo, latex) + (s.lo_eq ? le : lt) + s.var + (s.hi_eq ? le : lt) +
           show_e(s.hi, latex);
  if (s.lo) return s.var + (s.lo_eq ? ge : gt) + show_e(s.lo, latex);
  if (s.hi) return s.var + (s.hi_eq ? le : lt) + show_e(s.hi, latex);
  return "すべての実数";
}

inline std::vector<std::string> answer_lines(const Solution& s, bool latex = false) {
  using namespace ex;
  std::vector<std::string> out;
  if (!s.ok) { out.push_back(s.why); return out; }
  if (s.kind == "identity") { out.push_back("すべての値で成り立つ"); return out; }
  if (s.kind == "contradiction") { out.push_back("解なし（矛盾）"); return out; }
  if (s.kind == "dependent") {
    out.push_back("解は無限にある（2 つの式が同じものを表している）");
    return out;
  }
  if (s.kind == "all") { out.push_back("すべての実数で成り立つ"); return out; }
  if (s.kind == "empty") { out.push_back("解なし"); return out; }
  if (s.kind == "inequality") { out.push_back(range_text(s, latex)); return out; }
  if (s.kind == "system") {
    for (size_t i = 0; i < s.vars.size(); ++i)
      out.push_back(s.vars[i] + " = " + show_e(s.vals[i], latex));
    return out;
  }
  if (s.roots.empty()) { out.push_back("実数解なし"); return out; }
  for (const E& rt : s.roots) out.push_back(s.var + " = " + show_e(rt, latex));
  return out;
}

}  // namespace slv
