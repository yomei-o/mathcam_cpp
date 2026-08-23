// 数列と Σ — 高校の数学 B の範囲を「名前のついた書き換え」で解く。
//
// solve.hpp / calc.hpp と同じ考え方: **答えだけでなく手順を出す**。手順の名前は教科書の
// 言い方（「和の分解」「Σk^2 の公式」「等比数列の和」）にする。
//
// 何ができるか:
//   Σ      Σ[k=1..n] の多項式（k^3 まで）と等比（c r^(ak+b)）、その和。下端が 1 でなくても解く
//   数列    項の並びから 等差・等比・階差 を見分けて、一般項 a_n と 和 S_n を出す
//
// **答えは展開したままにしない**。Σk^2 の答えは n(n+1)(2n+1)/6 であって
// 1/3 n^3 + 1/2 n^2 + 1/6 n ではない。有理根定理で一次因数に分けてから印字する
// （factor_poly）。これをやらないと「合っているのに教科書と違う答え」になる。
#pragma once
#include "expr.hpp"
#include "solve.hpp"
#include <string>
#include <vector>

namespace seqs {

struct Step {
  std::string rule;      // 規則の名前（「Σk^2 の公式」「等比数列の和」…）
  std::string note;      // 一言説明
  ex::E before, after;   // その手の前後
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

// Σ の木。kids = {束縛変数, 下端, 上端, 中身}。印字は to_latex が \sum_{k=1}^{n} にする
inline ex::E sum_e(const std::string& var, const ex::E& lo, const ex::E& hi, const ex::E& body) {
  return ex::raw(ex::Kind::Fn, {ex::sym(var), lo, hi, body}, "sum");
}

inline bool is_sum(const ex::E& e) {
  return e->k == ex::Kind::Fn && e->name == "sum" && e->kids.size() == 4;
}

struct Sum {
  bool ok = false;
  std::string why;
  ex::E value;                  // 閉じた式（n の式、または数）
  std::vector<Step> steps;
  std::string var;
  ex::E lo, hi;
};

// ---------------------------------------------------------------- 因数分解（答えの見た目）

inline long long llgcd(long long a, long long b) {
  if (a < 0) a = -a;
  if (b < 0) b = -b;
  while (b) { const long long t = a % b; a = b; b = t; }
  return a;
}

inline void divisors(long long v, std::vector<long long>& out) {
  if (v < 0) v = -v;
  if (v == 0) { out.push_back(1); return; }
  for (long long d = 1; d * d <= v; ++d)
    if (v % d == 0) {
      out.push_back(d);
      if (d != v / d) out.push_back(v / d);
    }
  std::sort(out.begin(), out.end());
}

// 係数の並び（低次から）を「有理数 × 一次式の積 × 残り」に直す。
// 有理根定理で根を**小さい分母・小さい分子から順に**探す（並べる順を決めておかないと
// 言語によって因数の出方が変わる）。割り切れた分だけ取り出し、残りはそのまま置く。
inline ex::E factor_poly(std::vector<ex::Rat> c, const std::string& var) {
  using namespace ex;
  while (c.size() > 1 && c.back().is_zero()) c.pop_back();
  if (c.empty()) return num(Rat(0));
  if (c.size() == 1) return num(c[0]);

  long long L = 1;                                   // 分母を払って整数係数にする
  for (const Rat& q : c) L = L / llgcd(L, q.d) * q.d;
  std::vector<long long> a;
  for (const Rat& q : c) a.push_back(q.n * (L / q.d));
  long long g = 0;
  for (long long v : a) g = llgcd(g, v);
  if (g == 0) return num(Rat(0));
  for (long long& v : a) v /= g;
  if (a.back() < 0) { for (long long& v : a) v = -v; g = -g; }   // 先頭の係数を正にそろえる
  Rat lead(g, L);

  std::vector<E> fs;
  for (;;) {
    if (a.size() <= 1) break;
    if (a[0] == 0) {                                 // 定数項が 0 なら var でくくれる
      fs.push_back(sym(var));
      a.erase(a.begin());
      continue;
    }
    std::vector<long long> qs, ps;
    divisors(a.back(), qs);
    divisors(a[0], ps);
    bool found = false;
    for (size_t qi = 0; qi < qs.size() && !found; ++qi)
      for (size_t pi = 0; pi < ps.size() && !found; ++pi)
        for (int s = 1; s >= -1 && !found; s -= 2) {
          const long long q = qs[qi], p = s * ps[pi];
          if (llgcd(p, q) != 1) continue;
          Rat v(0);                                  // a(p/q) を厳密に計算する
          const Rat r(p, q);
          Rat pw(1);
          for (size_t i = 0; i < a.size(); ++i) { v = v + Rat(a[i]) * pw; pw = pw * r; }
          if (!v.is_zero()) continue;
          // (q x - p) で割る（整数係数のまま割り切れる）
          const size_t d = a.size() - 1;
          std::vector<long long> b(d, 0);
          b[d - 1] = a[d] / q;
          for (size_t i = d - 1; i >= 1; --i) b[i - 1] = (a[i] + p * b[i]) / q;
          fs.push_back(q == 1 ? add_n({sym(var), num(Rat(-p))})
                              : add_n({mul_n({num(Rat(q)), sym(var)}), num(Rat(-p))}));
          a = b;
          found = true;
        }
    if (!found) break;
  }
  std::vector<Rat> rest;
  for (long long v : a) rest.push_back(Rat(v));
  std::vector<E> parts;
  const E rp = slv::from_coeffs(rest, var);
  if (!(is_num(rp) && rp->num.is_one())) parts.push_back(rp);
  for (const E& f : fs) parts.push_back(f);
  if (!lead.is_one()) parts.insert(parts.begin(), num(lead));
  if (parts.empty()) return num(Rat(1));
  return mul_n(parts);
}

// 答えの見た目を整える: 1 変数の多項式なら因数の積に、そうでなければ展開したまま
inline ex::E nice(const ex::E& e) {
  using namespace ex;
  const E x = expand(e);
  std::vector<std::string> vs;
  collect_syms(x, vs);
  if (vs.size() != 1) return x;
  std::vector<Rat> c;
  if (!slv::poly_coeffs(x, vs[0], c)) return x;
  return factor_poly(c, vs[0]);
}

// ---------------------------------------------------------------- Σ

// 公式の説明に埋める上端の書き方（n - 1 のような式は括弧でくくる）
inline std::string mstr(const ex::E& m) {
  const std::string t = ex::to_infix(m);
  return (m->k == ex::Kind::Add || m->k == ex::Kind::Mul) ? "(" + t + ")" : t;
}

// Σ[k=1..m] k^p の公式（p = 0,1,2,3）。教科書の形のまま作る
inline ex::E power_sum(int p, const ex::E& m) {
  using namespace ex;
  const E half = mul_n({num(Rat(1, 2)), m, add_n({m, num(Rat(1))})});
  if (p == 0) return m;
  if (p == 1) return half;
  if (p == 2)
    return mul_n({num(Rat(1, 6)), m, add_n({m, num(Rat(1))}),
                  add_n({mul_n({num(Rat(2)), m}), num(Rat(1))})});
  return pow_e(half, num(Rat(2)));                   // p == 3
}

inline std::string power_rule(int p) {
  if (p == 0) return "定数の和";
  if (p == 1) return "Σk の公式";
  if (p == 2) return "Σk^2 の公式";
  return "Σk^3 の公式";
}

// 公式の説明。**上端を入れた形で書く**（「Σk = n(n+1)/2」の n を実際の上端に置き換える）。
// 上端が n - 1 のとき「(n-1)((n-1)+1)/2」と書くと読めないので、足し算は先に済ませる。
inline std::string power_note(int p, const ex::E& m) {
  using namespace ex;
  const std::string m1 = mstr(simp(add_n({m, num(Rat(1))})));
  const std::string m2 = mstr(simp(add_n({mul_n({num(Rat(2)), m}), num(Rat(1))})));
  if (p == 0) return "Σ 1 = " + mstr(m) + " （項の個数だけ足す）";
  if (p == 1) return "Σk = " + mstr(m) + m1 + "/2";
  if (p == 2) return "Σk^2 = " + mstr(m) + m1 + m2 + "/6";
  return "Σk^3 = {" + mstr(m) + m1 + "/2}^2";
}

// 項が c * r^(a*var + b) の形か（等比）。そうなら c, r, a, b を返す
inline bool geom_term(const ex::E& t, const std::string& var, ex::Rat& c, ex::Rat& r,
                      long long& a, long long& b) {
  using namespace ex;
  c = Rat(1);
  bool got = false;
  std::vector<E> fs;
  if (t->k == Kind::Mul) fs = t->kids; else fs.push_back(t);
  for (const E& f : fs) {
    if (is_num(f)) { c = c * f->num; continue; }
    if (f->k != Kind::Pow || !is_num(f->kids[0])) return false;
    if (got) return false;                           // 2^k * 3^k は扱わない（1 つにまとめてから）
    std::vector<Rat> lc;
    if (!slv::poly_coeffs(f->kids[1], var, lc)) return false;
    if (lc.size() != 2 || !lc[1].is_int() || !lc[0].is_int() || lc[1].is_zero()) return false;
    r = f->kids[0]->num;
    a = lc[1].n;
    b = lc[0].n;
    got = true;
  }
  return got;
}

// 1 項ぶんの Σ[var=1..m]。解けたら out に入れて true
inline bool sum_term(const ex::E& t, const std::string& var, const ex::E& m, ex::E& out,
                     std::string& rule, std::string& note) {
  using namespace ex;
  std::vector<Rat> c;
  if (slv::poly_coeffs(t, var, c)) {
    while (c.size() > 1 && c.back().is_zero()) c.pop_back();
    const int p = (int)c.size() - 1;
    if (p > 3) return false;                         // 4 乗以上の公式は教科書に無い
    if (p == 0 || c[p].is_zero()) {
      out = mul_n({num(c.empty() ? Rat(0) : c[0]), m});
      rule = power_rule(0);
      note = power_note(0, m);
      return true;
    }
    // 単項でないなら呼ぶ側が項ごとに分けているはず。ここに来るのは c[p] x^p だけの形
    for (int i = 0; i < p; ++i)
      if (!c[i].is_zero()) return false;
    out = c[p].is_one() ? power_sum(p, m) : mul_n({num(c[p]), power_sum(p, m)});
    rule = power_rule(p);
    note = power_note(p, m);
    if (!c[p].is_one()) note = "係数 " + c[p].str() + " を外に出して " + note;
    return true;
  }
  Rat cc, r;
  long long a = 0, b = 0;
  if (geom_term(t, var, cc, r, a, b)) {
    if (r.is_zero()) return false;
    const Rat ratio = rpow(r, a);                       // 公比（a が負でも rpow が扱う）
    const Rat first = cc * rpow(r, a + b);              // var = 1 のときの値
    if (ratio.is_one()) { out = mul_n({num(first), m}); rule = "定数の和";
                          note = "公比が 1 なので同じ数を " + mstr(m) + " 個足す"; return true; }
    // a(r^m - 1)/(r - 1)
    out = mul_n({num(first / (ratio - Rat(1))),
                 add_n({pow_e(num(ratio), m), num(Rat(-1))})});
    rule = "等比数列の和";
    note = "初項 " + first.str() + "、公比 " + ratio.str() + " の等比数列の和 a(r^n - 1)/(r - 1)";
    return true;
  }
  return false;
}

// Σ[var=lo..hi] body
inline Sum sigma(const ex::E& body_in, const std::string& var, const ex::E& lo, const ex::E& hi) {
  using namespace ex;
  Sum r;
  r.var = var;
  r.lo = lo;
  r.hi = hi;
  const E whole = sum_e(var, lo, hi, body_in);
  if (!is_num(lo) || !lo->num.is_int()) {
    r.why = "Σ の下端は整数でないと解けません";
    return r;
  }
  const long long L = lo->num.n;
  if (is_num(hi) && hi->num.is_int() && hi->num.n < L) {   // 項が無い
    r.ok = true;
    r.value = num(Rat(0));
    push(r.steps, "項が無い", "上端が下端より小さいので和は 0", whole, num(Rat(0)));
    return r;
  }

  // 下端を 1 にそろえる。公式は Σ[k=1..m] の形でしか書かれていないので、そこに寄せる
  const E m = hi;
  std::vector<E> extra;                              // 下端が 0 以下のときに書き出す項
  const bool cut_head = L >= 2;                      // 下端が 2 以上なら Σ[1..L-1] を引く
  if (cut_head) {
    const E shown = add_n({sum_e(var, num(Rat(1)), hi, body_in),
                           neg(sum_e(var, num(Rat(1)), num(Rat(L - 1)), body_in))});
    push(r.steps, "下端をずらす",
         "公式は k = 1 から。Σ[k=" + std::to_string(L) + "..] = Σ[k=1..] - Σ[k=1.." +
             std::to_string(L - 1) + "]",
         whole, shown);
  } else if (L <= 0) {
    if (1 - L > 32) { r.why = "Σ の下端が小さすぎます"; return r; }
    std::vector<E> xs;
    for (long long k = L; k <= 0; ++k) xs.push_back(simp(subst(body_in, var, num(Rat(k)))));
    extra = xs;
    xs.push_back(sum_e(var, num(Rat(1)), hi, body_in));
    push(r.steps, "下端をずらす", "k が 0 以下の項は書き出して、残りを公式で足す", whole,
         add_n(xs));
  }

  // 中身を項に分ける
  const E body = expand(body_in);
  std::vector<E> ts;
  if (body->k == Kind::Add) ts = disp_terms(body); else ts.push_back(body);
  if (ts.size() > 1) {
    std::vector<E> xs;
    for (const E& t : ts) xs.push_back(sum_e(var, num(Rat(1)), m, t));
    push(r.steps, "和の分解", "Σ は項ごとに分けられる", sum_e(var, num(Rat(1)), m, body),
         add_n(xs));
  }

  std::vector<E> parts;
  for (const E& t : ts) {
    E s;
    std::string rule, note;
    if (!sum_term(t, var, m, s, rule, note)) {
      r.why = to_infix(t) + " の Σ は未対応（k^4 以上や k·2^k のような形）";
      return r;
    }
    s = simp(s);
    push(r.steps, rule, note, sum_e(var, num(Rat(1)), m, t), s);
    parts.push_back(s);
  }
  E total = add_n(parts);

  if (cut_head) {                                    // Σ[1..L-1] を引く
    E cut = num(Rat(0));
    for (const E& t : ts) {
      E s;
      std::string rule, note;
      sum_term(t, var, num(Rat(L - 1)), s, rule, note);
      cut = add_n({cut, s});
    }
    const E before = add_n({total, neg(cut)});
    push(r.steps, "引く分を計算する",
         "Σ[k=1.." + std::to_string(L - 1) + "] = " + to_infix(simp(cut)), before, before);
    total = add_n({total, neg(cut)});
  }
  for (const E& x : extra) total = add_n({total, x});

  const E v = nice(total);
  push(r.steps, "まとめる", "通分して因数でくくる", total, v);
  r.ok = true;
  r.value = v;
  return r;
}

// ---------------------------------------------------------------- 数列（項の並びから）

struct Seq {
  bool ok = false;
  std::string why;
  std::string type;             // "等差数列" / "等比数列" / "階差数列"
  std::string var = "n";
  ex::E term;                   // 一般項 a_n
  ex::E sum;                    // 初項から第 n 項までの和 S_n（出せないときは空）
  ex::E nth;                    // --nth で指定した項の値（空なら未指定）
  long long nth_i = 0;
  std::vector<Step> steps;
  std::vector<ex::Rat> given;
  ex::Rat first, delta, ratio;  // 初項・公差・公比（型に応じて）
};

// 等差か（差が一定）
inline bool arith_of(const std::vector<ex::Rat>& a, ex::Rat& d) {
  if (a.size() < 3) return false;
  d = a[1] - a[0];
  for (size_t i = 2; i < a.size(); ++i)
    if (!(a[i] - a[i - 1] == d)) return false;
  return true;
}

// 等比か（比が一定）
inline bool geom_of(const std::vector<ex::Rat>& a, ex::Rat& r) {
  if (a.size() < 3) return false;
  for (const ex::Rat& v : a)
    if (v.is_zero()) return false;
  r = a[1] / a[0];
  for (size_t i = 2; i < a.size(); ++i)
    if (!(a[i] / a[i - 1] == r)) return false;
  return true;
}

inline std::string list_str(const std::vector<ex::Rat>& a) {
  std::string s;
  for (size_t i = 0; i < a.size(); ++i) { if (i) s += ", "; s += a[i].str(); }
  return s;
}

// 一般項が与えられた項を全部再現するか（見分けを間違えたまま答えを出さないための確認）
inline bool matches(const ex::E& term, const std::string& var, const std::vector<ex::Rat>& a) {
  using namespace ex;
  for (size_t i = 0; i < a.size(); ++i) {
    const E v = simp(subst(term, var, num(Rat((long long)i + 1))));
    if (!is_num(v) || !(v->num == a[i])) return false;
  }
  return true;
}

inline Seq analyze(const std::vector<ex::Rat>& a, const std::string& var = "n") {
  using namespace ex;
  Seq s;
  s.var = var;
  s.given = a;
  if (a.size() < 3) { s.why = "項が 3 つ以上ないと数列を見分けられません"; return s; }
  const E n = sym(var);
  s.first = a[0];

  Rat d, r;
  if (arith_of(a, d)) {
    s.type = "等差数列";
    s.delta = d;
    push(s.steps, "階差を取る", "となり合う項の差は " + d.str() + " で一定",
         num(a[1] - a[0]), num(d));
    s.term = nice(add_n({num(a[0]), mul_n({num(d), add_n({n, num(Rat(-1))})})}));
    push(s.steps, "等差数列の一般項", "a_n = 初項 + (n - 1) × 公差 = " + a[0].str() + " + (n - 1)×" +
         d.str(), s.term, s.term);
  } else if (geom_of(a, r)) {
    s.type = "等比数列";
    s.ratio = r;
    push(s.steps, "比を取る", "となり合う項の比は " + r.str() + " で一定", num(a[1]), num(r));
    s.term = simp(mul_n({num(a[0]), pow_e(num(r), add_n({n, num(Rat(-1))}))}));
    push(s.steps, "等比数列の一般項", "a_n = 初項 × 公比^(n - 1) = " + a[0].str() + "×" + r.str() +
         "^(n - 1)", s.term, s.term);
  } else {
    // 階差数列: b_k = a_(k+1) - a_k を作って、それが等差か等比なら a_n = a_1 + Σ[k=1..n-1] b_k
    if (a.size() < 4) { s.why = "等差でも等比でもありません（階差を見るには 4 項必要）"; return s; }
    std::vector<Rat> b;
    for (size_t i = 1; i < a.size(); ++i) b.push_back(a[i] - a[i - 1]);
    Rat bd, br;
    E bk;
    const E k = sym("k");
    if (arith_of(b, bd))
      bk = simp(add_n({num(b[0]), mul_n({num(bd), add_n({k, num(Rat(-1))})})}));
    else if (geom_of(b, br))
      bk = simp(mul_n({num(b[0]), pow_e(num(br), add_n({k, num(Rat(-1))}))}));
    else { s.why = "等差でも等比でもありません（階差も一定になりません）"; return s; }
    s.type = "階差数列";
    push(s.steps, "階差を取る", "差の数列 b_k は " + list_str(b) + " で、これが等差か等比になる",
         num(b[0]), bk);
    const E hi = add_n({n, num(Rat(-1))});
    const Sum sm = sigma(bk, "k", num(Rat(1)), hi);
    if (!sm.ok) { s.why = sm.why; return s; }
    push(s.steps, "階差数列の一般項", "a_n = a_1 + Σ[k=1..n-1] b_k （n ≥ 2）",
         sum_e("k", num(Rat(1)), hi, bk), sm.value);
    for (const Step& st : sm.steps) s.steps.push_back(st);
    s.term = nice(add_n({num(a[0]), sm.value}));
  }

  if (!matches(s.term, var, a)) {
    s.why = "一般項が与えられた項に合いません（数列を見分けられませんでした）";
    return s;
  }
  const Sum tot = sigma(subst(s.term, var, sym("k")), "k", num(Rat(1)), sym(var));
  if (tot.ok) {
    s.sum = tot.value;
    push(s.steps, "初項から第 n 項までの和", "S_n = Σ[k=1..n] a_k = " + to_infix(tot.value),
         sum_e("k", num(Rat(1)), sym(var), s.term), tot.value);
  }
  s.ok = true;
  return s;
}

// ---------------------------------------------------------------- 答えの文字列
//
// **答えの文言はここだけ**（CLI も WASM も Python も同じ文を出す）。
inline std::string show_e(const ex::E& e, bool latex) {
  return latex ? ex::to_latex(e) : ex::to_infix(e);
}

inline std::vector<std::string> answer_lines(const Sum& s, bool latex = false) {
  std::vector<std::string> out;
  if (!s.ok) { out.push_back(s.why); return out; }
  out.push_back(show_e(s.value, latex));
  return out;
}

inline std::vector<std::string> answer_lines(const Seq& s, bool latex = false) {
  std::vector<std::string> out;
  if (!s.ok) { out.push_back(s.why); return out; }
  if (s.type == "等差数列")
    out.push_back("等差数列（初項 " + s.first.str() + "、公差 " + s.delta.str() + "）");
  else if (s.type == "等比数列")
    out.push_back("等比数列（初項 " + s.first.str() + "、公比 " + s.ratio.str() + "）");
  else
    out.push_back("階差数列（初項 " + s.first.str() + "）");
  out.push_back("一般項: a_" + s.var + " = " + show_e(s.term, latex));
  if (s.sum) out.push_back("和: S_" + s.var + " = " + show_e(s.sum, latex));
  if (s.nth) out.push_back("第 " + std::to_string(s.nth_i) + " 項: " + show_e(s.nth, latex));
  return out;
}

}  // namespace seqs
