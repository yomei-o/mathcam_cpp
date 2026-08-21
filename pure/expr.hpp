// 数式そのもの — 木・厳密有理数・正規形・印字・構文解析。
//
// このファイルが決めることが、後の全部の契約になる:
//
//   * 認識側（写真 -> 記号 -> レイアウト解析）の出力はこの木である。
//   * 解く側（一次・二次方程式、将来の微分積分）はこの木を書き換える。
//   * 手順表示は「名前のついた書き換え」を記録したものである。
//
// 設計判断とその理由:
//
//   * **数は厳密有理数**（int64 の分子・分母、既約、分母は正）。1/3 を 0.333 にしたら
//     手順表示が嘘になる。double は最後の表示でしか使わない。
//   * **Add と Mul は可変長**（入れ子を平らにする）。正規形で同類項をまとめるのに必要で、
//     二項木のままだと (a+b)+c と a+(b+c) が別物になる。
//   * **木は不変で共有する**（shared_ptr<const Node>）。書き換えは新しい木を作る。
//     手順表示は「各段の木」を保持するので、破壊的更新だと過去の段が壊れる。
//   * **正規形は全順序でソートする**。そうすると「同じ式か」が構造の一致で判定でき、
//     x + 1 と 1 + x が同一になる。順序は決定的（種類 -> 名前 -> 子の数 -> 子）。
//   * **簡約は手順に出さない**。手順に出すのは solve が選んだ規則（「両辺から 3 を引く」
//     「解の公式」）だけ。正規化の 1 手 1 手を見せると、人間には読めないものになる。
//     Photomath 系アプリの価値は「読める手順」なので、ここは意図的に分けてある。
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <numeric>
#include <cstring>
#include <string>
#include <vector>

namespace ex {

// ---------------------------------------------------------------- 厳密有理数

struct Rat {
  long long n = 0, d = 1;

  Rat() = default;
  Rat(long long v) : n(v), d(1) {}
  Rat(long long num, long long den) : n(num), d(den) { norm(); }

  void norm() {
    if (d == 0) { n = 0; d = 1; return; }          // 0 除算は 0 に落とす（呼ぶ側で弾く）
    if (d < 0) { n = -n; d = -d; }
    long long g = std::gcd(n < 0 ? -n : n, d);
    if (g > 1) { n /= g; d /= g; }
    if (n == 0) d = 1;
  }
  bool is_int() const { return d == 1; }
  bool is_zero() const { return n == 0; }
  bool is_one() const { return n == 1 && d == 1; }
  bool neg() const { return n < 0; }
  double f() const { return (double)n / (double)d; }

  Rat operator+(const Rat& o) const { return Rat(n * o.d + o.n * d, d * o.d); }
  Rat operator-(const Rat& o) const { return Rat(n * o.d - o.n * d, d * o.d); }
  Rat operator*(const Rat& o) const { return Rat(n * o.n, d * o.d); }
  Rat operator/(const Rat& o) const { return Rat(n * o.d, d * o.n); }
  Rat operator-() const { Rat r; r.n = -n; r.d = d; return r; }
  bool operator==(const Rat& o) const { return n == o.n && d == o.d; }
  bool operator<(const Rat& o) const { return n * o.d < o.n * d; }

  std::string str() const {
    char b[64];
    if (d == 1) snprintf(b, sizeof b, "%lld", n);
    else snprintf(b, sizeof b, "%lld/%lld", n, d);
    return b;
  }
};

// 整数の冪。指数が負や分数のときは呼ばない（呼ぶ側が Pow のまま残す）
inline Rat rpow(const Rat& a, long long e) {
  if (e < 0) return Rat(1) / rpow(a, -e);
  Rat r(1), b = a;
  for (long long i = 0; i < e; ++i) r = r * b;
  return r;
}

// ---------------------------------------------------------------- 木

// Rel は関係式（= < <= > >=）で、**演算子は name に入れる**。Kind を 5 つに分けない理由は、
// cmp / simp / expand / 印字が全部同じ形で書けるから（既定の cmp が name も比べている）。
// Sys は連立（関係式の列）。並びは書かれた順のまま保つ（人が書いた順で手順を見せるため）。
enum class Kind { Num, Sym, Add, Mul, Pow, Fn, Rel, Sys };

struct Node;
using E = std::shared_ptr<const Node>;

struct Node {
  Kind k = Kind::Num;
  Rat num;                    // Num
  std::string name;           // Sym の変数名 / Fn の関数名 / Rel の演算子
  std::vector<E> kids;        // Add/Mul は 2 個以上、Pow と Rel は 2 個、Fn は引数、Sys は関係式
};

inline E mk(Kind k) { auto n = std::make_shared<Node>(); n->k = k; return n; }
inline E num(const Rat& r) { auto n = std::make_shared<Node>(); n->k = Kind::Num; n->num = r; return n; }
inline E num(long long v) { return num(Rat(v)); }
inline E sym(const std::string& s) {
  auto n = std::make_shared<Node>(); n->k = Kind::Sym; n->name = s; return n;
}
inline E raw(Kind k, std::vector<E> kids, const std::string& name = "") {
  auto n = std::make_shared<Node>();
  n->k = k; n->name = name; n->kids = std::move(kids);
  return n;
}

inline bool is_num(const E& e) { return e->k == Kind::Num; }
inline bool is_sym(const E& e) { return e->k == Kind::Sym; }

// ---------------------------------------------------------------- 全順序

// 決定的な順序。正規形のソートに使い、同じ式が構造として一致するようにする。
inline int cmp(const E& a, const E& b) {
  if (a->k != b->k) return (int)a->k < (int)b->k ? -1 : 1;
  switch (a->k) {
    case Kind::Num:
      if (a->num == b->num) return 0;
      return a->num < b->num ? -1 : 1;
    case Kind::Sym:
      return a->name < b->name ? -1 : (a->name == b->name ? 0 : 1);
    default: {
      if (a->name != b->name) return a->name < b->name ? -1 : 1;
      if (a->kids.size() != b->kids.size()) return a->kids.size() < b->kids.size() ? -1 : 1;
      for (size_t i = 0; i < a->kids.size(); ++i) {
        int c = cmp(a->kids[i], b->kids[i]);
        if (c) return c;
      }
      return 0;
    }
  }
}
inline bool equal(const E& a, const E& b) { return cmp(a, b) == 0; }

// ---------------------------------------------------------------- 正規形

E simp(const E& e);

inline void flatten(Kind k, const E& e, std::vector<E>& out) {
  if (e->k == k) { for (const E& c : e->kids) flatten(k, c, out); }
  else out.push_back(e);
}

// 項を「係数 × 残り」に割る（同類項をまとめるため）
inline void split_coeff(const E& t, Rat& c, E& rest) {
  c = Rat(1);
  if (t->k == Kind::Num) { c = t->num; rest = num(Rat(1)); return; }
  if (t->k != Kind::Mul) { rest = t; return; }
  std::vector<E> others;
  for (const E& f : t->kids) {
    if (f->k == Kind::Num) c = c * f->num;
    else others.push_back(f);
  }
  if (others.empty()) rest = num(Rat(1));
  else if (others.size() == 1) rest = others[0];
  else rest = raw(Kind::Mul, others);
}

// 因子を「底 ^ 指数」に割る（同じ底をまとめるため）
inline void split_pow(const E& f, E& base, E& expo) {
  if (f->k == Kind::Pow) { base = f->kids[0]; expo = f->kids[1]; }
  else { base = f; expo = num(Rat(1)); }
}

inline E add_n(std::vector<E> xs) {
  std::vector<E> flat;
  for (E& x : xs) flatten(Kind::Add, simp(x), flat);
  Rat konst(0);
  std::vector<std::pair<E, Rat>> terms;              // 残り -> 係数の合計
  for (const E& t : flat) {
    if (t->k == Kind::Num) { konst = konst + t->num; continue; }
    Rat c; E rest;
    split_coeff(t, c, rest);
    bool merged = false;
    for (auto& pr : terms)
      if (equal(pr.first, rest)) { pr.second = pr.second + c; merged = true; break; }
    if (!merged) terms.emplace_back(rest, c);
  }
  std::vector<E> out;
  for (auto& pr : terms) {
    if (pr.second.is_zero()) continue;
    if (pr.second.is_one()) out.push_back(pr.first);
    else out.push_back(simp(raw(Kind::Mul, {num(pr.second), pr.first})));
  }
  if (!konst.is_zero()) out.push_back(num(konst));
  if (out.empty()) return num(Rat(0));
  if (out.size() == 1) return out[0];
  std::sort(out.begin(), out.end(), [](const E& a, const E& b) { return cmp(a, b) < 0; });
  return raw(Kind::Add, out);
}

inline E mul_n(std::vector<E> xs) {
  std::vector<E> flat;
  for (E& x : xs) flatten(Kind::Mul, simp(x), flat);
  Rat coef(1);
  std::vector<std::pair<E, std::vector<E>>> bases;   // 底 -> 指数たち
  for (const E& f : flat) {
    if (f->k == Kind::Num) {
      coef = coef * f->num;
      if (coef.is_zero()) return num(Rat(0));
      continue;
    }
    E b, p;
    split_pow(f, b, p);
    bool merged = false;
    for (auto& pr : bases)
      if (equal(pr.first, b)) { pr.second.push_back(p); merged = true; break; }
    if (!merged) bases.emplace_back(b, std::vector<E>{p});
  }
  std::vector<E> out;
  for (auto& pr : bases) {
    E e = pr.second.size() == 1 ? pr.second[0] : add_n(pr.second);
    if (is_num(e) && e->num.is_zero()) continue;                 // x^0 = 1
    if (is_num(e) && e->num.is_one()) { out.push_back(pr.first); continue; }
    out.push_back(raw(Kind::Pow, {pr.first, e}));
  }
  if (out.empty()) return num(coef);
  if (!coef.is_one()) out.insert(out.begin(), num(coef));
  if (out.size() == 1) return out[0];
  std::sort(out.begin(), out.end(), [](const E& a, const E& b) { return cmp(a, b) < 0; });
  return raw(Kind::Mul, out);
}

inline E pow_e(const E& b_in, const E& e_in) {
  E b = simp(b_in), p = simp(e_in);
  if (is_num(p)) {
    if (p->num.is_zero()) return num(Rat(1));
    if (p->num.is_one()) return b;
    if (is_num(b) && p->num.is_int()) {
      const long long e = p->num.n;
      if (e > -32 && e < 32 && !(b->num.is_zero() && e < 0)) return num(rpow(b->num, e));
    }
    // 分数指数のとき、まず**根号の中の完全冪を外に出す**: sqrt(8) は 2*sqrt(2) にする。
    // これをやらないと x^2 = 2 の答えが 1/2*sqrt(8) と出て、厳密に計算している意味が薄れる。
    if (is_num(b) && !p->num.is_int() && !b->num.neg() && p->num.n > 0) {
      const long long q = p->num.d;
      if (q > 1 && q <= 8) {
        auto pull = [q](long long v, long long& outside, long long& inside) {
          outside = 1; inside = v;
          for (long long f = 2; f * f <= inside && f < 4096; ++f) {
            long long pw = 1;
            for (long long i = 0; i < q; ++i) pw *= f;      // f^q
            if (pw <= 1) break;
            while (inside % pw == 0) { inside /= pw; outside *= f; }
          }
        };
        long long on = 1, in_n = b->num.n, od = 1, in_d = b->num.d;
        pull(b->num.n, on, in_n);
        pull(b->num.d, od, in_d);
        if (on != 1 || od != 1) {
          const Rat coef = rpow(Rat(on, od), p->num.n);       // 外に出た分（指数の分子は乗る）
          const E rest = raw(Kind::Pow, {num(Rat(in_n, in_d)), p});
          if (in_n == 1 && in_d == 1) return num(coef);
          return mul_n({num(coef), rest});
        }
      }
    }
    // 厳密に閉じるなら畳む: sqrt(4) は 2 であって 4^(1/2) のまま残す理由がない。
    // 閉じないもの（sqrt(2)）は Pow のまま置く。整数根が取れるかを実際に試して確かめる。
    if (is_num(b) && !p->num.is_int() && b->num.d != 0) {
      const long long root = p->num.d, up = p->num.n;
      if (root > 1 && root <= 8 && up > -32 && up < 32 && !b->num.neg()) {
        auto iroot = [](long long v, long long k, long long& out) {
          if (v < 0) return false;
          long long r = (long long)std::llround(std::pow((double)v, 1.0 / (double)k));
          for (long long c = r > 2 ? r - 2 : 0; c <= r + 2; ++c) {
            long long q = 1;
            bool ovf = false;
            for (long long i = 0; i < k; ++i) { q *= c; if (q > (1LL << 40)) { ovf = true; break; } }
            if (!ovf && q == v) { out = c; return true; }
          }
          return false;
        };
        long long rn = 0, rd = 0;
        if (iroot(b->num.n, root, rn) && iroot(b->num.d, root, rd))
          return num(rpow(Rat(rn, rd), up));
      }
    }
  }
  if (b->k == Kind::Pow) {                                      // (a^m)^n = a^(mn)
    const E& in = b->kids[1];
    if (is_num(in) && is_num(p) && in->num.is_int() && p->num.is_int())
      return pow_e(b->kids[0], num(in->num * p->num));
  }
  if (b->k == Kind::Mul && is_num(p) && p->num.is_int()) {       // (ab)^n = a^n b^n
    std::vector<E> fs;
    for (const E& f : b->kids) fs.push_back(pow_e(f, p));
    return mul_n(fs);
  }
  return raw(Kind::Pow, {b, p});
}

// 関数。数値で閉じるものだけ畳む（sqrt(4)=2 など）。それ以外は Fn のまま。
inline E fn_e(const std::string& name, std::vector<E> args) {
  for (E& a : args) a = simp(a);
  if (name == "sqrt" && args.size() == 1) return pow_e(args[0], num(Rat(1, 2)));
  // 小学校の書き方を「1 つのテキスト」で表すための記法。値としては割り算と足し算に畳む
  // （絵のほうは ts::present_arith が書かれたとおりに描く）。
  //   frac(a,b)      縦の分数
  //   mixed(w,a,b)   帯分数（w + a/b）
  if (name == "frac" && args.size() == 2)
    return mul_n({args[0], pow_e(args[1], num(Rat(-1)))});
  if (name == "mixed" && args.size() == 3)
    return add_n({args[0], mul_n({args[1], pow_e(args[2], num(Rat(-1)))})});
  if (args.size() == 1 && is_num(args[0])) {
    const Rat& r = args[0]->num;
    if (name == "abs") return num(r.neg() ? -r : r);
    if (name == "ln" && r.is_one()) return num(Rat(0));
    if ((name == "sin" || name == "tan") && r.is_zero()) return num(Rat(0));
    if (name == "cos" && r.is_zero()) return num(Rat(1));
    if (name == "exp" && r.is_zero()) return num(Rat(1));
  }
  return raw(Kind::Fn, args, name);
}

inline E simp(const E& e) {
  switch (e->k) {
    case Kind::Num:
    case Kind::Sym:
      return e;
    case Kind::Add: return add_n(e->kids);
    case Kind::Mul: return mul_n(e->kids);
    case Kind::Pow: return pow_e(e->kids[0], e->kids[1]);
    case Kind::Fn: return fn_e(e->name, e->kids);
    case Kind::Rel: return raw(Kind::Rel, {simp(e->kids[0]), simp(e->kids[1])}, e->name);
    case Kind::Sys: {
      std::vector<E> ks;
      for (const E& c : e->kids) ks.push_back(simp(c));
      return raw(Kind::Sys, ks);
    }
  }
  return e;
}

// 使いやすい別名（呼ぶ側は simp 済みの木を受け取る）
inline E add(const E& a, const E& b) { return add_n({a, b}); }
inline E sub(const E& a, const E& b) { return add_n({a, mul_n({num(Rat(-1)), b})}); }
inline E mul(const E& a, const E& b) { return mul_n({a, b}); }
inline E div(const E& a, const E& b) { return mul_n({a, pow_e(b, num(Rat(-1)))}); }
inline E neg(const E& a) { return mul_n({num(Rat(-1)), a}); }

// 関係式。`op` は "=" "<" "<=" ">" ">=" のどれか。
inline E rel(const std::string& op, const E& a, const E& b) {
  return raw(Kind::Rel, {simp(a), simp(b)}, op);
}
inline E eq(const E& a, const E& b) { return rel("=", a, b); }
inline bool is_rel(const E& e) { return e->k == Kind::Rel; }
inline bool is_eq(const E& e) { return e->k == Kind::Rel && e->name == "="; }

// 不等号の向きを裏返す。**負の数を両辺にかける／割るときに必ず要る**（中学生が最も間違える所で、
// 手順表示でもここだけは理由を書く）。
inline std::string flip_op(const std::string& op) {
  if (op == "<") return ">";
  if (op == "<=") return ">=";
  if (op == ">") return "<";
  if (op == ">=") return "<=";
  return op;                                       // "=" は裏返しても "="
}

// 連立（関係式の列）。1 本だけならそのまま返す（Sys で包むと印字が変わってしまう）
inline E sys(const std::vector<E>& rels) {
  if (rels.size() == 1) return simp(rels[0]);
  std::vector<E> ks;
  for (const E& c : rels) ks.push_back(simp(c));
  return raw(Kind::Sys, ks);
}

// ---------------------------------------------------------------- 展開
//
// 分配法則を simp に入れない理由: (x+1)^100 のような式で爆発するし、「くくった形」を保ちたい
// 場面（因数分解の手順表示）で邪魔になる。展開が必要なのは
//   * 同類項をまとめて ax + b = 0 の形にするとき（solve）
//   * 人が期待する「答えの形」にするとき（eval）
// なので、そのときだけ明示的に呼ぶ。指数は整数かつ小さいものだけ展開する。
inline E expand(const E& e);

inline E expand_mul(std::vector<E> fs) {
  std::vector<E> sum{num(Rat(1))};                 // 部分積の集まり（=和の項）
  for (const E& f : fs) {
    std::vector<E> terms;
    if (f->k == Kind::Add) terms = f->kids;
    else terms.push_back(f);
    std::vector<E> next;
    next.reserve(sum.size() * terms.size());
    for (const E& a : sum)
      for (const E& b : terms) next.push_back(mul_n({a, b}));
    sum = std::move(next);
  }
  return add_n(sum);
}

inline E expand(const E& e) {
  switch (e->k) {
    case Kind::Num:
    case Kind::Sym:
      return e;
    case Kind::Add: {
      std::vector<E> xs;
      for (const E& c : e->kids) xs.push_back(expand(c));
      return add_n(xs);
    }
    case Kind::Mul: {
      std::vector<E> xs;
      for (const E& c : e->kids) xs.push_back(expand(c));
      return expand_mul(xs);
    }
    case Kind::Pow: {
      E b = expand(e->kids[0]);
      E p = expand(e->kids[1]);
      if (b->k == Kind::Add && is_num(p) && p->num.is_int() && p->num.n > 1 && p->num.n <= 8) {
        std::vector<E> fs((size_t)p->num.n, b);     // (a+b)^n を n 個の積に開く
        return expand_mul(fs);
      }
      return pow_e(b, p);
    }
    case Kind::Fn: {
      std::vector<E> xs;
      for (const E& c : e->kids) xs.push_back(expand(c));
      return fn_e(e->name, xs);
    }
    case Kind::Rel:
      return raw(Kind::Rel, {expand(e->kids[0]), expand(e->kids[1])}, e->name);
    case Kind::Sys: {
      std::vector<E> ks;
      for (const E& c : e->kids) ks.push_back(expand(c));
      return raw(Kind::Sys, ks);
    }
  }
  return e;
}

// ---------------------------------------------------------------- 印字

// 表示のための次数。内部の正規順序（cmp）は「同じ式か」を判定するためのもので、
// 読みやすさは別問題。人は x^2 - 5x + 6 の順で書くので、表示だけ次数の降順に並べ替える。
inline long long disp_degree(const E& e) {
  switch (e->k) {
    case Kind::Num: return 0;
    case Kind::Sym: return 1;
    case Kind::Pow: {
      const E& p = e->kids[1];
      if (is_num(p) && p->num.is_int()) return disp_degree(e->kids[0]) * p->num.n;
      return 1;
    }
    case Kind::Mul: {
      long long d = 0;
      for (const E& c : e->kids) d += disp_degree(c);
      return d;
    }
    case Kind::Add: {
      long long d = 0;
      for (const E& c : e->kids) d = std::max(d, disp_degree(c));
      return d;
    }
    default: return 1;
  }
}

// 項に出てくる変数のうち、辞書順で最初のもの（表示の並び替えに使う）
inline std::string disp_var(const E& e) {
  if (e->k == Kind::Sym) return e->name;
  std::string best;
  for (const E& c : e->kids) {
    const std::string v = disp_var(c);
    if (v.empty()) continue;
    if (best.empty() || v < best) best = v;
  }
  return best;
}

// 項の中の「変数 -> 次数」（表示の並び替え用。変数名の順に並べて返す）
inline void term_degs(const E& e, std::vector<std::pair<std::string, long long>>& out) {
  if (e->k == Kind::Sym) {
    for (std::pair<std::string, long long>& p : out)
      if (p.first == e->name) { p.second += 1; return; }
    out.push_back({e->name, 1});
    return;
  }
  if (e->k == Kind::Pow && is_sym(e->kids[0]) && is_num(e->kids[1]) &&
      e->kids[1]->num.is_int()) {
    const long long d = e->kids[1]->num.n;
    for (std::pair<std::string, long long>& p : out)
      if (p.first == e->kids[0]->name) { p.second += d; return; }
    out.push_back({e->kids[0]->name, d});
    return;
  }
  for (const E& c : e->kids) term_degs(c, out);
}

inline long long deg_of(const std::vector<std::pair<std::string, long long>>& v,
                       const std::string& name) {
  for (const std::pair<std::string, long long>& p : v)
    if (p.first == name) return p.second;
  return 0;
}

// 和の項を表示順に並べたもの。
//
//   1. 次数の降順（人は x^2 - 5x + 6 の順で書く）
//   2. 同じ次数なら、**変数ごとの次数を変数名の順に見て、次数の大きい方を先**にする
//      （教科書は x^2 + 12xy + 36y^2 の順。正規順序だけだと係数の大小で並んで
//        `2x - y` が `-y + 2*x` と出る。実写の `(2x - y)^2` を読んだときに出た）
//   3. それでも決まらなければ正規順序（決定的にするため）
inline std::vector<E> disp_terms(const E& e) {
  std::vector<E> ts = e->kids;
  std::stable_sort(ts.begin(), ts.end(), [](const E& a, const E& b) {
    const long long da = disp_degree(a), db = disp_degree(b);
    if (da != db) return da > db;
    std::vector<std::pair<std::string, long long>> va, vb;
    term_degs(a, va);
    term_degs(b, vb);
    std::vector<std::string> names;
    for (const std::pair<std::string, long long>& p : va) names.push_back(p.first);
    for (const std::pair<std::string, long long>& p : vb) names.push_back(p.first);
    std::sort(names.begin(), names.end());
    names.erase(std::unique(names.begin(), names.end()), names.end());
    for (const std::string& n : names) {
      const long long ea = deg_of(va, n), eb = deg_of(vb, n);
      if (ea != eb) return ea > eb;
    }
    return cmp(a, b) < 0;
  });
  return ts;
}

// 演算子の優先順位。括弧を出しすぎず、足りなくもしないため
inline int prec(const E& e) {
  switch (e->k) {
    case Kind::Sys: return -1;
    case Kind::Rel: return 0;
    case Kind::Add: return 1;
    case Kind::Mul: return 2;
    case Kind::Pow: return 3;
    default: return 4;
  }
}

// 積を「分子の因子」と「分母の因子」に分ける。**印字のためだけ**の処理で、意味の木は変えない。
// 組版側（typeset.hpp の split_frac）と同じ考え方: 指数が負のものと、有理数の分母が分母に行く。
// これをやらないと 2/(3x) が "2/3*1/x" と出る（読めない）。
inline void split_num_den(const E& e, std::vector<E>& up, std::vector<E>& down) {
  std::vector<E> fs;
  if (e->k == Kind::Mul) fs = e->kids; else fs.push_back(e);
  for (const E& f : fs) {
    if (f->k == Kind::Pow && is_num(f->kids[1]) && f->kids[1]->num.neg()) {
      const Rat q = f->kids[1]->num;
      down.push_back(q.n == -1 && q.d == 1 ? f->kids[0] : pow_e(f->kids[0], num(-q)));
    } else if (is_num(f) && !f->num.is_int()) {
      if (f->num.n != 1) up.push_back(num(Rat(f->num.n)));
      down.push_back(num(Rat(f->num.d)));
    } else {
      up.push_back(f);
    }
  }
}

inline std::string to_infix(const E& e, int parent = 0);

inline std::string wrap(const E& e, int p) {
  const std::string s = to_infix(e, p);
  return prec(e) < p ? "(" + s + ")" : s;
}

inline std::string to_infix(const E& e, int parent) {
  (void)parent;
  switch (e->k) {
    case Kind::Num: return e->num.str();
    case Kind::Sym: return e->name;
    case Kind::Add: {
      std::string s;
      const std::vector<E> ts = disp_terms(e);
      for (size_t i = 0; i < ts.size(); ++i) {
        const E& t = ts[i];
        // 負の項は "+ -3" ではなく "- 3" と書く
        Rat c; E rest;
        split_coeff(t, c, rest);
        const bool minus = c.neg();
        if (i == 0) { if (minus) s += "-"; }
        else s += minus ? " - " : " + ";
        Rat ac = minus ? -c : c;
        E body = ac.is_one() && !is_num(rest) ? rest
                 : (is_num(rest) && rest->num.is_one() ? num(ac) : mul_n({num(ac), rest}));
        s += wrap(body, 1);
      }
      return s;
    }
    case Kind::Mul: {
      {
        std::vector<E> up, down;
        split_num_den(e, up, down);
        if (!down.empty()) {
          const E nu = up.empty() ? num(Rat(1)) : (up.size() == 1 ? up[0] : mul_n(up));
          const E de = down.size() == 1 ? down[0] : mul_n(down);
          return wrap(nu, 2) + "/" + wrap(de, 3);
        }
      }
      // 係数 -1 は "-1*x" ではなく "-x" と書く（人はそう書く）
      std::string s;
      size_t start = 0;
      if (is_num(e->kids[0]) && e->kids[0]->num.n == -1 && e->kids[0]->num.d == 1 &&
          e->kids.size() > 1) {
        s += "-";
        start = 1;
      }
      for (size_t i = start; i < e->kids.size(); ++i) {
        if (i > start) s += "*";
        s += wrap(e->kids[i], 2);
      }
      return s;
    }
    case Kind::Pow: {
      const E& b = e->kids[0];
      const E& p = e->kids[1];
      if (is_num(p) && p->num == Rat(1, 2)) return "sqrt(" + to_infix(b) + ")";
      // 負の指数は分数で書く（LaTeX 側と組版側は分数なのに、中置だけ x^(-1) と出ていた）
      if (is_num(p) && p->num.neg()) {
        const std::string den = p->num.n == -1 && p->num.d == 1
                                    ? wrap(b, 3)
                                    : wrap(pow_e(b, num(-p->num)), 3);
        return "1/" + den;
      }
      // 指数が整数でない数のときは括弧が必須。"2^1/2" は自分のパーサで (2^1)/2 に読めてしまう
      // ので、印字したものを読み直せなくなる（往復不変が壊れる）。
      const bool need = !is_num(p) || !p->num.is_int() || p->num.neg();
      const std::string ps = need ? "(" + to_infix(p) + ")" : to_infix(p);
      return wrap(b, 4) + "^" + ps;
    }
    case Kind::Fn: {
      std::string s = e->name + "(";
      for (size_t i = 0; i < e->kids.size(); ++i) { if (i) s += ", "; s += to_infix(e->kids[i]); }
      return s + ")";
    }
    case Kind::Rel:
      return to_infix(e->kids[0]) + " " + e->name + " " + to_infix(e->kids[1]);
    case Kind::Sys: {
      // 連立は ", " で並べる。**この形をパーサが読み戻せる**（往復不変を Sys でも保つ）
      std::string s;
      for (size_t i = 0; i < e->kids.size(); ++i) {
        if (i) s += ", ";
        s += to_infix(e->kids[i]);
      }
      return s;
    }
  }
  return "?";
}

// LaTeX。デモの表示と、学習データを描くレンダラの入力に使う
inline std::string to_latex(const E& e, int parent = 0) {
  switch (e->k) {
    case Kind::Num:
      if (e->num.is_int()) return e->num.str();
      return "\\frac{" + std::to_string(e->num.n) + "}{" + std::to_string(e->num.d) + "}";
    case Kind::Sym: return e->name;
    case Kind::Add: {
      std::string s;
      const std::vector<E> ts = disp_terms(e);
      for (size_t i = 0; i < ts.size(); ++i) {
        Rat c; E rest;
        split_coeff(ts[i], c, rest);
        const bool minus = c.neg();
        if (i == 0) { if (minus) s += "-"; }
        else s += minus ? " - " : " + ";
        Rat ac = minus ? -c : c;
        E body = ac.is_one() && !is_num(rest) ? rest
                 : (is_num(rest) && rest->num.is_one() ? num(ac) : mul_n({num(ac), rest}));
        s += to_latex(body, 1);
      }
      return s;
    }
    case Kind::Mul: {
      // 有理数の係数は分数として前に出す（\frac{2}{3}x のように）
      {
        std::vector<E> up, down;
        split_num_den(e, up, down);
        if (!down.empty()) {
          const E nu = up.empty() ? num(Rat(1)) : (up.size() == 1 ? up[0] : mul_n(up));
          const E de = down.size() == 1 ? down[0] : mul_n(down);
          return "\\frac{" + to_latex(nu) + "}{" + to_latex(de) + "}";
        }
      }
      std::string s;
      size_t start = 0;
      if (is_num(e->kids[0]) && e->kids[0]->num.n == -1 && e->kids[0]->num.d == 1 &&
          e->kids.size() > 1) {
        s += "-";
        start = 1;
      }
      for (size_t i = start; i < e->kids.size(); ++i) {
        const E& f = e->kids[i];
        std::string t = to_latex(f, 2);
        if (f->k == Kind::Add) t = "(" + t + ")";
        s += (i > start ? " " : "") + t;
      }
      return s;
    }
    case Kind::Pow: {
      const E& b = e->kids[0];
      const E& p = e->kids[1];
      if (is_num(p) && p->num == Rat(1, 2)) return "\\sqrt{" + to_latex(b) + "}";
      // 負の指数は分数で書く（-1 だけでなく -1/2 なども。往復で表示が変わらないように）
      if (is_num(p) && p->num.neg())
        return "\\frac{1}{" +
               to_latex(p->num.n == -1 && p->num.d == 1 ? b : pow_e(b, num(-p->num))) + "}";
      std::string bs = to_latex(b, 4);
      if (b->k == Kind::Add || b->k == Kind::Mul || b->k == Kind::Pow) bs = "(" + bs + ")";
      return bs + "^{" + to_latex(p) + "}";
    }
    case Kind::Fn: {
      std::string s = "\\" + e->name + "(";
      for (size_t i = 0; i < e->kids.size(); ++i) { if (i) s += ", "; s += to_latex(e->kids[i]); }
      return s + ")";
    }
    case Kind::Rel: {
      const std::string op = e->name == "<=" ? "\\le" : e->name == ">=" ? "\\ge" : e->name;
      return to_latex(e->kids[0]) + " " + op + " " + to_latex(e->kids[1]);
    }
    case Kind::Sys: {
      std::string s = "\\begin{cases}";
      for (size_t i = 0; i < e->kids.size(); ++i) {
        if (i) s += " \\\\ ";
        else s += " ";
        s += to_latex(e->kids[i]);
      }
      return s + " \\end{cases}";
    }
  }
  (void)parent;
  return "?";
}

// ---------------------------------------------------------------- 構文解析
//
// 認識器ができるまでの入口であり、テストの入口でもある。暗黙の掛け算（5x, 2(x+1)）を
// 受けるのは、写真から読んだ式がそう書かれているから。

// 関数として扱う名前（これ以外の名前 + 括弧は掛け算）
inline bool is_fn_name(const std::string& n) {
  return n == "sqrt" || n == "frac" || n == "mixed" || n == "sin" || n == "cos" || n == "tan" || n == "ln" || n == "exp" ||
         n == "abs";
}

struct Parser {
  std::string s;
  size_t i = 0;
  std::string err;

  explicit Parser(std::string src) : s(std::move(src)) {}

  void ws() { while (i < s.size() && (s[i] == ' ' || s[i] == '\t')) ++i; }
  bool eat(char c) { ws(); if (i < s.size() && s[i] == c) { ++i; return true; } return false; }
  bool peek(char c) { ws(); return i < s.size() && s[i] == c; }

  E parse_all() {
    std::vector<E> rels{parse_rel()};
    for (;;) {
      ws();
      if (peek(',') || peek(';')) {                  // 連立は "," か ";" で区切る
        if (!eat(',')) eat(';');
        rels.push_back(parse_rel());
        continue;
      }
      break;
    }
    ws();
    if (i < s.size() && err.empty()) err = "余分な文字: " + s.substr(i);
    if (rels.size() == 1) return rels[0];
    return raw(Kind::Sys, rels);
  }
  // 関係演算子は 1 段だけ（a < b < c のような連鎖は受けない。中学の書き方に無いので、
  // 受けると「読めているつもりで別の意味」になる）
  E parse_rel() {
    E l = parse_add();
    ws();
    if (i + 1 < s.size() && (s[i] == '<' || s[i] == '>') && s[i + 1] == '=') {
      const std::string op = std::string(1, s[i]) + "=";
      i += 2;
      return raw(Kind::Rel, {l, parse_add()}, op);
    }
    if (eat('<')) return raw(Kind::Rel, {l, parse_add()}, "<");
    if (eat('>')) return raw(Kind::Rel, {l, parse_add()}, ">");
    if (eat('=')) return raw(Kind::Rel, {l, parse_add()}, "=");
    return l;
  }
  E parse_add() {
    E l = parse_mul();
    for (;;) {
      ws();
      if (eat('+')) l = add_n({l, parse_mul()});
      else if (eat('-')) l = add_n({l, mul_n({num(Rat(-1)), parse_mul()})});
      else return l;
    }
  }
  // 小学校の計算では × と ÷ が字として書かれる（UTF-8 で 2 バイト）。読めるようにしておく
  bool eat_utf8(const char* seq) {
    ws();
    const size_t n = strlen(seq);
    if (s.compare(i, n, seq) == 0) { i += n; return true; }
    return false;
  }

  E parse_mul() {
    E l = parse_unary();
    for (;;) {
      ws();
      if (eat('*') || eat_utf8("\xc3\x97")) l = mul_n({l, parse_unary()});           // * ×
      else if (eat('/') || eat_utf8("\xc3\xb7"))                                     // / ÷
        l = mul_n({l, pow_e(parse_unary(), num(Rat(-1)))});
      else if (i < s.size() && (isalpha((unsigned char)s[i]) || s[i] == '(' || s[i] == '{' ||
                                isdigit((unsigned char)s[i]))) {
        // 暗黙の掛け算。ただし数のあとに数が来る形（"2 3"）は書き間違いとして扱う
        if (isdigit((unsigned char)s[i]) && is_num(l)) { err = "数が続いています"; return l; }
        l = mul_n({l, parse_unary()});
      } else return l;
    }
  }
  E parse_unary() {
    ws();
    if (eat('-')) return mul_n({num(Rat(-1)), parse_unary()});
    if (eat('+')) return parse_unary();
    return parse_pow();
  }
  E parse_pow() {
    E b = parse_atom();
    ws();
    if (eat('^')) return pow_e(b, parse_unary());     // 右結合
    return b;
  }
  E parse_atom() {
    ws();
    if (i >= s.size()) { err = "式が途中で終わっています"; return num(Rat(0)); }
    if (eat('(')) {
      E e = parse_add();
      if (!eat(')')) err = "閉じ括弧がありません";
      return e;
    }
    if (eat('{')) {                                  // 小学校の計算は { } も使う
      E e = parse_add();
      if (!eat('}')) err = "閉じ中括弧がありません";
      return e;
    }
    if (isdigit((unsigned char)s[i])) {
      long long v = 0;
      while (i < s.size() && isdigit((unsigned char)s[i])) v = v * 10 + (s[i++] - '0');
      if (i < s.size() && s[i] == '.') {              // 小数は有理数に直す（0.25 -> 1/4）
        ++i;
        long long f = 0, den = 1;
        while (i < s.size() && isdigit((unsigned char)s[i])) { f = f * 10 + (s[i++] - '0'); den *= 10; }
        return num(Rat(v * den + f, den));
      }
      return num(Rat(v));
    }
    if (isalpha((unsigned char)s[i])) {
      // 名前は**英字の連なりだけ**（数字は含めない。`x2` は x*2 と読む）
      std::string name;
      while (i < s.size() && isalpha((unsigned char)s[i])) name += s[i++];
      // **関数呼び出しは名前が関数のときだけ**。そうしないと `2x(x - 1)` の `x(...)` が
      // 「関数 x の呼び出し」になり、`2x(x-1) = 5` が展開できない式として残る
      // （実写の写真でこの形が出て、答えが出せなかった）。数式では変数のあとの括弧は掛け算。
      if (peek('(') && is_fn_name(name)) {
        eat('(');
        std::vector<E> args{parse_add()};
        while (eat(',')) args.push_back(parse_add());
        if (!eat(')')) err = "関数の閉じ括弧がありません";
        return fn_e(name, args);
      }
      // **英字が続いたら 1 文字ずつの変数の積**（`12xy` は 12*x*y。教科書はそう書く）。
      // 1 つの変数 "xy" にしていたら、次数が 1 と数えられて表示順も展開も狂った。
      if (name.size() > 1) {
        std::vector<E> fs;
        for (char c : name) fs.push_back(sym(std::string(1, c)));
        return mul_n(fs);
      }
      return sym(name);
    }
    err = std::string("読めない文字: ") + s[i];
    ++i;
    return num(Rat(0));
  }
};

// 失敗したら why に理由が入り、戻り値は 0 になる
inline E parse(const std::string& src, std::string* why = nullptr) {
  Parser p(src);
  E e = p.parse_all();
  if (why) *why = p.err;
  return simp(e);
}

// ---------------------------------------------------------------- 補助

// 出現する変数（並びは決定的）
inline void collect_syms(const E& e, std::vector<std::string>& out) {
  if (e->k == Kind::Sym) {
    if (std::find(out.begin(), out.end(), e->name) == out.end()) out.push_back(e->name);
  }
  for (const E& c : e->kids) collect_syms(c, out);
}

// 変数を式で置き換える（代入法、連立の後半、将来の微分の合成に使う）。
// 置き換えた後は simp を通すので、結果は正規形。
inline E subst(const E& e, const std::string& var, const E& val) {
  if (e->k == Kind::Sym) return e->name == var ? val : e;
  if (e->kids.empty()) return e;
  std::vector<E> ks;
  for (const E& c : e->kids) ks.push_back(subst(c, var, val));
  return simp(raw(e->k, ks, e->name));
}

// 数値評価（表示の最後だけで使う。厳密に閉じない sqrt などのため）
inline double approx(const E& e) {
  switch (e->k) {
    case Kind::Num: return e->num.f();
    case Kind::Sym: return 0.0;                        // 未知数は 0 とみなす（呼ぶ側で弾く）
    case Kind::Add: { double s = 0; for (const E& c : e->kids) s += approx(c); return s; }
    case Kind::Mul: { double s = 1; for (const E& c : e->kids) s *= approx(c); return s; }
    case Kind::Pow: return std::pow(approx(e->kids[0]), approx(e->kids[1]));
    case Kind::Fn: {
      const double a = e->kids.empty() ? 0.0 : approx(e->kids[0]);
      if (e->name == "sin") return std::sin(a);
      if (e->name == "cos") return std::cos(a);
      if (e->name == "tan") return std::tan(a);
      if (e->name == "ln") return std::log(a);
      if (e->name == "exp") return std::exp(a);
      if (e->name == "abs") return std::fabs(a);
      return a;
    }
    case Kind::Rel: return approx(e->kids[0]) - approx(e->kids[1]);
    case Kind::Sys: return 0.0;                        // 連立に数値はない（呼ぶ側で弾く）
  }
  return 0.0;
}

}  // namespace ex
