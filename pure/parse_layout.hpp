// レイアウト解析 — 記号の枠の列を式木に戻す。
//
// 認識の後半である。検出器が出すのは「クラスと枠」の集まりで、そこには**構造が無い**。
// x^2 と x2、a/b と ab の違いは位置関係だけで決まる。ここがその位置関係を読む場所。
//
// なぜ規則ベースか: 合成データには**正解の式**があるので、この解析器の正解率を単体で測れる
// （`mathcam selftest`）。学習モデルにすると「検出器の誤りか解析器の誤りか」が切り分けられない。
//
// **設計（1 度目の書き方を捨てた理由）**
// 最初は「分数を探す -> 根号を探す -> 残りを ± で割る」の順に書いたが、これは順序が逆で、
// 切り出した分数の左右に残った記号の扱いが場当たりになり、正解率 39% で止まった
// （`t/3 + 1 = -2` が「解釈できない記号: +」で落ちるなど）。正しい形は:
//
//   1. **構造を畳む**。分数（横線）・根号（上線）・括弧を見つけ、その中身を再帰的に解析して、
//      **1 個の原子**（すでに式が入っている疑似記号）に置き換える。外側から内側へ。
//   2. 残った平らな列を、**優先順位どおり**に割る: `=` -> `±` -> 並置（掛け算）と上付き。
//
// こうすると、± の分割は「同じ深さの平らな列」に対してだけ行われ、分数の中の + と外の + を
// 取り違えることがなくなる。
#pragma once
#include "expr.hpp"
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

namespace pl {

struct Sym {
  std::string cls;                      // "0".."9", "x", "+", "-", "=", "(", ")", "sqrt", "frac"
  int x0 = 0, y0 = 0, x1 = 0, y1 = 0;   // 画素（y は下向き）
  // **ベースラインの y**。上付きの判定は箱の下端ではなくこれで行う。
  // 箱の下端で判定すると、分数（下に伸びる）は上付きに見えず、括弧（下に伸びる）の次の記号が
  // 上付きに見える。実測: 7x^(3/2) が 7*x*(3/2)、(x+5)x^3 が (x+5)^(x^3) に化けた。
  int base_y = 0;
  // 構造を畳んだ原子。set なら cls は "@" で、e に解析済みの式が入っている
  bool atom = false;
  // **その原子が縦の分数だったか**。帯分数（2 5/8 = 2 + 5/8）の判定に要る。
  // 数のすぐ右に分数が来たら、掛け算ではなく足し算になる（小学校の書き方）。
  bool from_frac = false;
  // **その原子が括弧の塊だったか**。関数呼び出し（sin(x)）の判定に要る。
  bool from_paren = false;
  // 検出器が付けた確からしさ（0..1）。**式の読み方には使わない**（表示と実験のため）。
  // ブラウザのデモで枠に出すと、どの記号が危ういのかがすぐ分かる。
  float score = 0.f;
  ex::E e;
  int cx() const { return (x0 + x1) / 2; }
  int cy() const { return (y0 + y1) / 2; }
  int w() const { return x1 - x0; }
  int h() const { return y1 - y0; }
};

struct Result {
  bool ok = false;
  std::string why;
  ex::E e;
  std::string text;
};

// 閾値（記号の大きさに対する比。実測で詰める）
enum : int {
  T_SUP_RISE = 30,        // 上付きと見なす持ち上がり（基準の高さに対する %）
  T_SUP_SMALL = 90,       // 上付きは基準より小さい（高さの比が % 以下）
  T_SAME_LINE = 35,       // 同じ行と見なす中心のずれ（高さに対する %）
  // 桁をつなぐ隙間の上限（高さに対する %）。**教科書体は字の幅に対して送りが広い**ので、
  // 40% では `111` が 3 つの数に割れ、小数点も繋がらなかった（実測: 教科書体の字で
  // 計算問題の解析が 73%。55% で 85%、65% で 96%、75% で 100%）。実写の教科書でも
  // 数字どうしの隙間は 41% あった。合成の 100% は 75% でも落ちない。
  T_DIGIT_GAP = 75,
};

inline bool by_x(const Sym& a, const Sym& b) { return a.x0 < b.x0; }

// 基準の高さ。**畳んだ原子は数えない**（分数や括弧を含む原子は縦に長いので、これを基準に
// すると上付きの閾値が大きくなりすぎ、(x - 9/4)^3 の 3 を拾えなくなる）。
inline int median_h(const std::vector<Sym>& v) {
  std::vector<int> hs;
  for (const Sym& s : v)
    if (!s.atom && s.cls != "-" && s.cls != "frac" && s.cls != "=") hs.push_back(s.h());
  // 全部が原子のとき（`(1/3)^(1/4)` のように分数だけが並ぶ）は**いちばん小さい原子**を基準に
  // する。先頭の原子にすると、土台が大きいほど上付きの閾値も大きくなり、指数を拾えない
  // （実測: `1/3 * 1/4 = 1/12` と読んだ。selftest が捕まえた）。
  if (hs.empty()) {
    if (v.empty()) return 1;
    int m = v[0].h();
    for (const Sym& s : v) m = std::min(m, s.h());
    return std::max(1, m);
  }
  std::sort(hs.begin(), hs.end());
  return std::max(1, hs[hs.size() / 2]);
}

// **畳まないで読むか**。小学校の計算の手順（ar::eval_steps）を出すのに要る。
// 畳んで読むと `1.8 × 3.5 - (10.2 - 6.8)` は `2.9` になり、どこを先に計算したか消える。
inline bool& raw_mode() {
  static bool v = false;
  return v;
}
inline ex::E mk_add(const ex::E& a, const ex::E& b) {
  return raw_mode() ? ex::raw(ex::Kind::Fn, {a, b}, "op_add") : ex::add(a, b);
}
inline ex::E mk_sub(const ex::E& a, const ex::E& b) {
  return raw_mode() ? ex::raw(ex::Kind::Fn, {a, b}, "op_sub") : ex::sub(a, b);
}
inline ex::E mk_mul(const ex::E& a, const ex::E& b) {
  return raw_mode() ? ex::raw(ex::Kind::Fn, {a, b}, "op_mul") : ex::mul(a, b);
}
inline ex::E mk_div(const ex::E& a, const ex::E& b) {
  // 縦の分数は**1 つの数**として畳む（割り算をする所ではない）。÷ の記号だけ演算に残す
  if (raw_mode() && ex::is_num(a) && ex::is_num(b) && !b->num.is_zero())
    return ex::num(a->num / b->num);
  return raw_mode() ? ex::raw(ex::Kind::Fn, {a, b}, "op_div") : ex::div(a, b);
}
inline ex::E mk_neg(const ex::E& a) {
  return raw_mode() ? ex::raw(ex::Kind::Fn, {a}, "op_neg") : ex::neg(a);
}

// ---------------------------------------------------------------- 横棒を直す
//
// 検出器から見ると、**マイナス（U+2212）・分数線・根号の上線・= の 2 本**はどれも
// 「細長い横棒」で、字の形だけでは区別できない（実測: 実写で `=` が sqrt 2 個、
// マイナスが sqrt や frac になった）。見分けるのは**構造**の仕事:
//
//   * 同じ x の範囲に上下 2 本 -> `=`
//   * 上下に中身がある 1 本 -> 分数線（collapse_one が判定する）
//   * 下に中身がある + 左に根号の字 -> 根号の上線（同上）
//   * それ以外の 1 本 -> マイナス
//
// ここでは「2 本 -> =」と「同じ棒が 2 つに割れて検出された」だけを直す。残りは collapse_one。
inline bool bar_like(const Sym& s) {
  return !s.atom && (s.cls == "-" || s.cls == "frac" || s.cls == "sqrt" || s.cls == "=") &&
         s.w() >= s.h() * 3;
}

inline void fix_bars(std::vector<Sym>& v, int h_ref) {
  // 1) 同じ棒が 2 つに割れて検出されたものをつなぐ（縦の位置がほぼ同じで、横が重なる）
  for (size_t i = 0; i < v.size(); ++i) {
    if (!bar_like(v[i])) continue;
    for (size_t j = i + 1; j < v.size();) {
      if (!bar_like(v[j])) { ++j; continue; }
      const int dy = std::abs(v[i].cy() - v[j].cy());
      const int ov = std::min(v[i].x1, v[j].x1) - std::max(v[i].x0, v[j].x0);
      const int shorter = std::min(v[i].w(), v[j].w());
      if (dy * 100 <= std::max(4, h_ref * 12) && ov * 100 > shorter * 40) {
        v[i].x0 = std::min(v[i].x0, v[j].x0);
        v[i].x1 = std::max(v[i].x1, v[j].x1);
        v[i].y0 = std::min(v[i].y0, v[j].y0);
        v[i].y1 = std::max(v[i].y1, v[j].y1);
        v.erase(v.begin() + (long)j);
        continue;
      }
      ++j;
    }
  }
  // 2) 同じ x に上下 2 本あって、**間に何も無く、長さもほぼ同じ**なら `=`。
  //    条件を緩くすると入れ子の分数（分子が分数）を = と読んでしまう（実測で 4 件壊した）。
  for (size_t i = 0; i < v.size(); ++i) {
    if (!bar_like(v[i])) continue;
    for (size_t j = i + 1; j < v.size(); ++j) {
      if (!bar_like(v[j])) continue;
      const int ov = std::min(v[i].x1, v[j].x1) - std::max(v[i].x0, v[j].x0);
      const int shorter = std::min(v[i].w(), v[j].w());
      const int longer = std::max(v[i].w(), v[j].w());
      const int dy = std::abs(v[i].cy() - v[j].cy());
      const int lo = std::max(v[i].x0, v[j].x0), hi = std::min(v[i].x1, v[j].x1);
      const int top = std::min(v[i].cy(), v[j].cy()), bot = std::max(v[i].cy(), v[j].cy());
      bool between = false;                            // 2 本の間に字があるか（分数の分子など）
      for (size_t k = 0; k < v.size(); ++k) {
        if (k == i || k == j) continue;
        if (v[k].cx() >= lo && v[k].cx() <= hi && v[k].cy() > top && v[k].cy() < bot)
          between = true;
      }
      if (ov * 100 > shorter * 60 && shorter * 100 >= longer * 70 && !between && dy > 0 &&
          dy * 100 <= std::max(8, h_ref * 45)) {
        Sym eq = v[i];
        eq.cls = "=";
        eq.x0 = std::min(v[i].x0, v[j].x0);
        eq.x1 = std::max(v[i].x1, v[j].x1);
        eq.y0 = std::min(v[i].y0, v[j].y0);
        eq.y1 = std::max(v[i].y1, v[j].y1);
        eq.base_y = eq.y1;
        v[i] = eq;
        v.erase(v.begin() + (long)j);
        break;
      }
    }
  }
}

ex::E parse_flat(std::vector<Sym> v, std::string* why);

inline Sym make_atom(const ex::E& e, int x0, int y0, int x1, int y1, int base_y) {
  Sym s;
  s.cls = "@";
  s.atom = true;
  s.e = e;
  s.x0 = x0; s.y0 = y0; s.x1 = x1; s.y1 = y1;
  s.base_y = base_y;
  return s;
}

// 記号列のベースライン（いちばん下にあるベースライン）。畳んだ原子に持たせる値
inline int run_baseline(const std::vector<Sym>& v) {
  int b = 0;
  bool any = false;
  for (const Sym& s : v) {
    if (s.cls == "frac" || s.cls == "sqrt") continue;      // 線はベースラインを持たない
    if (!any || s.base_y > b) { b = s.base_y; any = true; }
  }
  return any ? b : (v.empty() ? 0 : v[0].y1);
}

// ---------------------------------------------------------------- 1) 構造を畳む

// 分数線のうち、いちばん幅の広いもの（外側から処理するため）
inline int widest_frac(const std::vector<Sym>& v) {
  int best = -1;
  for (size_t i = 0; i < v.size(); ++i)
    if (!v[i].atom && v[i].cls == "frac" && (best < 0 || v[i].w() > v[(size_t)best].w()))
      best = (int)i;
  return best;
}

// 根号の上線（幅の広い "sqrt"）。根号記号そのものは幅が狭いので、幅で見分ける
inline int widest_sqrt_bar(const std::vector<Sym>& v) {
  int best = -1;
  for (size_t i = 0; i < v.size(); ++i)
    if (!v[i].atom && v[i].cls == "sqrt" && v[i].h() * 3 < v[i].w() &&
        (best < 0 || v[i].w() > v[(size_t)best].w()))
      best = (int)i;
  return best;
}

// 括弧の開き（小学校の計算は { } も使う。どちらも同じ扱い）
inline bool is_open(const Sym& s) { return !s.atom && (s.cls == "(" || s.cls == "brace_l"); }
inline bool is_close(const Sym& s) { return !s.atom && (s.cls == ")" || s.cls == "brace_r"); }

inline int first_open_paren(const std::vector<Sym>& v) {
  for (size_t i = 0; i < v.size(); ++i)
    if (is_open(v[i])) return (int)i;
  return -1;
}

inline int match_close(const std::vector<Sym>& v, int i) {
  int depth = 0;
  for (size_t k = (size_t)i; k < v.size(); ++k) {
    if (v[k].atom) continue;
    if (is_open(v[k])) ++depth;
    else if (is_close(v[k])) { if (--depth == 0) return (int)k; }
  }
  return -1;
}

// 構造を 1 つ畳む。畳んだら true。無ければ false。
//
// **外側の構造から畳む。** 分数線と根号の上線のうち**幅の広い方**を先に処理する。
// 内側から畳むと、外側の構造の一部（根号の上線など）が内側の集合に混ざり、外側に記号だけが
// 取り残される（実測: `sqrt(7/48)` で分子の集合に上線が入り、根号記号が余って
// 「解釈できない記号: sqrt」になった）。
inline bool collapse_one(std::vector<Sym>& v, std::string* why) {
  using namespace ex;

  const int fi_c = widest_frac(v);
  const int bi_c = widest_sqrt_bar(v);
  const int fw = fi_c >= 0 ? v[(size_t)fi_c].w() : -1;
  const int bw = bi_c >= 0 ? v[(size_t)bi_c].w() : -1;

  // --- 分数（根号の上線より広いときだけ先に） ---
  const int fi = (fw >= bw) ? fi_c : -1;
  if (fi >= 0) {
    const Sym bar = v[(size_t)fi];
    std::vector<Sym> up, down, rest;
    int ux0 = bar.x0, uy0 = bar.y0, ux1 = bar.x1, uy1 = bar.y1;
    for (size_t i = 0; i < v.size(); ++i) {
      if ((int)i == fi) continue;
      const Sym& s = v[i];
      const bool inside = s.cx() >= bar.x0 - 2 && s.cx() <= bar.x1 + 2;
      if (!inside) { rest.push_back(s); continue; }
      (s.cy() < bar.cy() ? up : down).push_back(s);
      ux0 = std::min(ux0, s.x0); uy0 = std::min(uy0, s.y0);
      ux1 = std::max(ux1, s.x1); uy1 = std::max(uy1, s.y1);
    }
    // **上か下に何も無い横棒はマイナス**。検出器から見ると分数線とマイナス（U+2212）は
    // どちらも「細長い横棒」で、字だけでは区別できない（実測: 実写の `x^2 − 6x + 5 = 0` で
    // マイナスが frac になり、解析が「分数の上か下が空です」で落ちた）。
    // 見分けるのは**構造**の仕事: 分数線は上下に中身がある。
    if (up.empty() || down.empty()) {
      v[(size_t)fi].cls = "-";
      return true;                                    // ラベルを直してもう一度回す
    }
    const E nu = parse_flat(up, why);
    if (!why->empty()) return false;
    const E de = parse_flat(down, why);
    if (!why->empty()) return false;
    Sym fr = make_atom(mk_div(nu, de), ux0, uy0, ux1, uy1, bar.cy());
    fr.from_frac = true;                            // 帯分数の判定に使う
    rest.push_back(fr);
    // 原子を末尾に足したので**必ず並べ直す**。これを忘れると、以降の = や ± の分割が
    // 位置と無関係な順序で行われる（実測: `x/4 + 5 = 2` が `5 = (x/4)^2` に化けた）
    std::sort(rest.begin(), rest.end(), by_x);
    v = rest;
    return true;
  }

  // --- 根号 ---
  const int bi = bi_c;
  if (bi >= 0) {
    const Sym bar = v[(size_t)bi];
    std::vector<Sym> in, rest;
    int ux0 = bar.x0, uy0 = bar.y0, ux1 = bar.x1, uy1 = bar.y1;
    for (size_t i = 0; i < v.size(); ++i) {
      if ((int)i == bi) continue;
      const Sym& s = v[i];
      // 上線の真下にあるものが中身。根号記号（幅が狭い "sqrt"）は上線の左にあるので外れる
      const bool under = s.cx() >= bar.x0 - 2 && s.cx() <= bar.x1 + 2 && s.cy() > bar.cy();
      if (!under) { rest.push_back(s); continue; }
      in.push_back(s);
      ux0 = std::min(ux0, s.x0); uy0 = std::min(uy0, s.y0);
      ux1 = std::max(ux1, s.x1); uy1 = std::max(uy1, s.y1);
    }
    // 根号の上線も「細長い横棒」なので、マイナスと取り違えられる（実測: 実写でマイナスが
    // sqrt になった）。**下に何も無い上線はマイナス**として読み直す。
    if (in.empty()) {
      v[(size_t)bi].cls = "-";
      return true;
    }
    // 根号記号そのもの（上線の左にある狭い "sqrt"）を消す。
    // 条件を「右端が上線の左端より左」にしていたら、字形が上線に食い込む場合に消えず、
    // 記号が余って「解釈できない記号: sqrt」で落ちた（実測: sqrt((7)/(48))）。
    // 左端で見るようにする。
    // 上線の**すぐ左にある**ものを 1 つだけ消す。「x0 が上線の左端以下」で探すと、
    // 根号が 2 つ並んでいるとき（sqrt(12) - sqrt(x)）に左側の根号を消してしまい、
    // 記号が余る。いちばん近いものを選ぶ。
    int cand = -1;
    for (size_t i = 0; i < rest.size(); ++i) {
      const Sym& s = rest[i];
      if (s.atom || s.cls != "sqrt") continue;
      if (s.h() * 3 < s.w()) continue;                    // 上線ではなく記号だけを対象にする
      if (s.x0 > bar.x0 + 2) continue;
      if (cand < 0 || s.x0 > rest[(size_t)cand].x0) cand = (int)i;
    }
    if (cand >= 0) {
      ux0 = std::min(ux0, rest[(size_t)cand].x0);
      uy1 = std::max(uy1, rest[(size_t)cand].y1);
      rest.erase(rest.begin() + (long)cand);
    }
    const E e = parse_flat(in, why);
    if (!why->empty()) return false;
    rest.push_back(make_atom(fn_e("sqrt", {e}), ux0, uy0, ux1, uy1, run_baseline(in)));
    std::sort(rest.begin(), rest.end(), by_x);
    v = rest;
    return true;
  }

  // --- 括弧 ---
  const int pi = first_open_paren(v);
  if (pi >= 0) {
    const int pj = match_close(v, pi);
    if (pj < 0) { *why = "括弧が閉じていません"; return false; }
    std::vector<Sym> in(v.begin() + (long)pi + 1, v.begin() + (long)pj);
    if (in.empty()) { *why = "括弧の中が空です"; return false; }
    const E e = parse_flat(in, why);
    if (!why->empty()) return false;
    int ux0 = v[(size_t)pi].x0, uy0 = v[(size_t)pi].y0;
    int ux1 = v[(size_t)pj].x1, uy1 = v[(size_t)pj].y1;
    for (const Sym& s : in) {
      uy0 = std::min(uy0, s.y0);
      uy1 = std::max(uy1, s.y1);
    }
    std::vector<Sym> out(v.begin(), v.begin() + (long)pi);
    Sym pa = make_atom(e, ux0, uy0, ux1, uy1, run_baseline(in));
    pa.from_paren = true;                             // 関数呼び出しの判定に使う
    out.push_back(pa);
    for (size_t k = (size_t)pj + 1; k < v.size(); ++k) out.push_back(v[k]);
    v = out;
    return true;
  }
  return false;
}

// ---------------------------------------------------------------- 2) 平らな列を割る

inline bool is_digit_cls(const Sym& s) {
  return !s.atom && s.cls.size() >= 1 && (isdigit((unsigned char)s.cls[0]) || s.cls[0] == '.');
}

// 小数点。クラス名は "dot"（小学校の計算に出る）
inline bool is_dot_cls(const Sym& s) { return !s.atom && s.cls == "dot"; }

// 隣り合う桁をまとめる（同じ行にあって、隙間が狭いものだけ）。
// **小数点も桁として扱う**（3 . 7 -> "3.7"）。点は行の下にあるので、同じ行かの判定は
// 中心ではなく「下端が近いか」で見る。
// **縦棒だけの `1` を `l` と取り違えるのを直す。**
//
// 教科書の書体の `1` は旗も台も無い縦棒で、検出器から見ると小文字の `l` と同じ
// （実測: 実写の `103 × 12 - 36` が `6*l - 36` になった）。区別は並びでつける:
// **右隣が数字で、桁としてくっつく間隔なら `1`**。左隣だけが数字のときは変えない
// （`3l` は「3 掛ける l」で、変数の l はそこに出る）。この非対称が肝で、これなら合成データの
// `3l + 5` を壊さない。
inline void fix_ones(std::vector<Sym>& v, int h_ref) {
  for (size_t i = 0; i + 1 < v.size(); ++i) {
    if (v[i].atom || v[i].cls != "l") continue;
    const Sym& nx = v[i + 1];
    if (nx.atom || !(nx.cls.size() == 1 && nx.cls[0] >= '0' && nx.cls[0] <= '9')) continue;
    const int h = std::max(v[i].h(), nx.h());
    const int gap = nx.x0 - v[i].x1;
    const bool same_line = std::abs(v[i].cy() - nx.cy()) * 100 <= h * T_SAME_LINE;
    const bool same_size = std::abs(v[i].h() - nx.h()) * 100 <= h * 25;
    // 隙間の上限は桁つなぎ（40%）より緩くする。教科書は字間が広く、実測で 41% だった
    if (same_line && same_size && gap * 100 <= h * 55) v[i].cls = "1";
    (void)h_ref;
  }
  // **計算問題で、文字が l しか無いなら、その l は 1**。
  // 右隣が数字でない縦棒（`21` の 1 など）は上の規則では直せない。ただし × ÷ 小数点が
  // 出ている行は小学校の計算で、そこに変数 l は出てこない（生成器からも外した）。
  // 実測: `12 × 15 × 35` の 1 が l になって `350` と読まれた。
  bool arith_marks = false, other_letter = false, has_l = false;
  for (const Sym& s : v) {
    if (s.atom) continue;
    if (s.cls == "times" || s.cls == "div" || s.cls == "dot") arith_marks = true;
    else if (s.cls == "l") has_l = true;
    else if (s.cls.size() == 1 && s.cls[0] >= 'a' && s.cls[0] <= 'z') other_letter = true;
    else if (s.cls == "t2") other_letter = true;
  }
  if (arith_marks && has_l && !other_letter)
    for (Sym& s : v)
      if (!s.atom && s.cls == "l") s.cls = "1";
}

// 並んだ英字が関数の名前を綴っていて、すぐ右が括弧の塊なら**関数呼び出しにする**。
//
// 検出器は 1 字ずつしか出さないので `sin(x)` は s・i・n・( ・x・) として届く。掛け算として
// 組むと `i*n*s*x` になり、三角関数の問題が 1 つも解けない（実測）。
// `ln` の l は 1 と同じ形なので、検出器はほぼ必ず "1" と読む。**名前を綴るときだけ**
// "1" も l の候補として見る（fix_ones が 1 に寄せるより前にこれを走らせる）。
inline void fix_fnnames(std::vector<Sym>& v) {
  using namespace ex;
  const auto letter_of = [](const Sym& s) -> char {
    if (s.atom) return 0;
    if (s.cls.size() == 1 && isalpha((unsigned char)s.cls[0])) return s.cls[0];
    if (s.cls == "t2") return 't';
    if (s.cls == "1") return 'l';                     // l と 1 は同じ形（名前のときだけ）
    return 0;
  };
  for (size_t j = 0; j < v.size(); ++j) {
    if (!v[j].atom || !v[j].from_paren) continue;     // すぐ左に名前が要る
    size_t i = j;                                     // 英字の並びの先頭を探す
    while (i > 0 && letter_of(v[i - 1])) --i;
    if (j - i < 2) continue;                          // 1 文字の関数名は無い
    for (size_t k = i; k + 1 < j; ++k) {              // **後ろ寄りの綴りから試す**（x sin(x)）
      std::string name;
      for (size_t m = k; m < j; ++m) name += letter_of(v[m]);
      if (!is_fn_name(name) || name == "frac" || name == "mixed") continue;
      const E e = fn_e(name, {v[j].e});
      Sym a = make_atom(e, v[k].x0, std::min(v[k].y0, v[j].y0), v[j].x1,
                        std::max(v[k].y1, v[j].y1), v[j].base_y);
      std::vector<Sym> out(v.begin(), v.begin() + (long)k);
      out.push_back(a);
      for (size_t m = j + 1; m < v.size(); ++m) out.push_back(v[m]);
      v = out;
      j = k;                                          // 詰めたので見直す
      break;
    }
  }
}

inline void merge_digits(std::vector<Sym>& v) {
  for (size_t i = 0; i + 1 < v.size();) {
    // 数 . 数 の並びを 1 つにする（点は小さいので大きさの条件を通らない。先に処理する）
    if (i + 2 < v.size() && is_digit_cls(v[i]) && is_dot_cls(v[i + 1]) &&
        is_digit_cls(v[i + 2])) {
      const int h = std::max(v[i].h(), v[i + 2].h());
      const int g1 = v[i + 1].x0 - v[i].x1, g2 = v[i + 2].x0 - v[i + 1].x1;
      if (g1 * 100 <= h * T_DIGIT_GAP && g2 * 100 <= h * T_DIGIT_GAP &&
          std::abs(v[i].y1 - v[i + 2].y1) * 100 <= h * T_SAME_LINE) {
        v[i].cls += "." + v[i + 2].cls;
        v[i].x1 = v[i + 2].x1;
        v[i].y0 = std::min(v[i].y0, v[i + 2].y0);
        v[i].y1 = std::max(v[i].y1, v[i + 2].y1);
        v.erase(v.begin() + (long)i + 1, v.begin() + (long)i + 3);
        continue;
      }
    }
    if (is_digit_cls(v[i]) && is_digit_cls(v[i + 1])) {
      const int h = std::max(v[i].h(), v[i + 1].h());
      const int gap = v[i + 1].x0 - v[i].x1;
      const bool same_line = std::abs(v[i].cy() - v[i + 1].cy()) * 100 <= h * T_SAME_LINE;
      const bool same_size = std::abs(v[i].h() - v[i + 1].h()) * 100 <= h * 25;
      if (same_line && same_size && gap * 100 <= h * T_DIGIT_GAP) {
        v[i].cls += v[i + 1].cls;
        v[i].x1 = v[i + 1].x1;
        v[i].y0 = std::min(v[i].y0, v[i + 1].y0);
        v[i].y1 = std::max(v[i].y1, v[i + 1].y1);
        v.erase(v.begin() + (long)i + 1);
        continue;
      }
    }
    ++i;
  }
}

inline long long to_int(const std::string& s) {
  long long v = 0;
  for (char c : s) v = v * 10 + (c - '0');
  return v;
}

// 数の文字列（小数もある）を厳密有理数にする。0.25 は 1/4（double は通さない）
inline ex::Rat to_rat(const std::string& s) {
  const size_t dot = s.find('.');
  if (dot == std::string::npos) return ex::Rat(to_int(s));
  const std::string ip = s.substr(0, dot), fp = s.substr(dot + 1);
  long long den = 1;
  for (size_t i = 0; i < fp.size(); ++i) den *= 10;
  return ex::Rat(to_int(ip) * den + to_int(fp), den);
}

inline ex::E leaf(const Sym& s, std::string* why) {
  using namespace ex;
  if (s.atom) return s.e;
  if (is_digit_cls(s)) return num(to_rat(s.cls));
  if (s.cls.size() == 1 && isalpha((unsigned char)s.cls[0])) return sym(s.cls);
  *why = "解釈できない記号: " + s.cls;
  return num(Rat(0));
}

// s が base の上付きか。
//
// **判定はベースラインの差で行う**（大きさの比では駄目）。最初は「上付きは親より小さい」と
// 書いたが、親が x のような背の低い字だと、0.7 倍に縮めた数字のほうが背が高くなる
// （実測: x の高さ 916、上付きの 2 が 968）。それで `3x^2 + x` が `3*x*2 + x = 7x` に
// 化けていた。人が見て分かるのは「下端が親の下端より上に浮いているか」なので、そう書く。
inline bool is_sup(const Sym& base, const Sym& s, int h_ref) {
  const int lift0 = base.base_y - s.base_y;
  // 演算子は上付きにならない。ただし "-" だけは例外で、**十分に持ち上がっていれば**
  // 負の指数の符号として認める（組版側は分数で描くので普段は出ないが、写真から来た式では出る）
  if (!s.atom && (s.cls == "+" || s.cls == "=")) return false;
  if (!s.atom && s.cls == "-" && lift0 * 100 < h_ref * 60) return false;
  const int lift = lift0;                              // y は下向き。s が上にあると正
  if (lift * 100 < h_ref * T_SUP_RISE) return false;
  // 背の高いもの（括弧など）が隣に来ただけのときを弾く。ただし**十分に持ち上がっている**なら
  // 大きさは問わない（指数が分数だと縦に長くなる。実測: 7x^(3/2) がこれで弾かれていた）。
  if (lift * 100 >= h_ref * 60) return true;
  // 大きさは**土台と比べる**（本文の字と比べると、分数の指数が「大きすぎる」で落ちる）。
  if (s.h() * 100 <= base.h() * 85) return true;
  if (s.h() * 100 > h_ref * 130) return false;
  // 持ち上がりが微妙なとき（基準の 30..60%）は、**基準より明らかに小さい**か、
  // **ベースラインが基準の縦中央より上**にあることを要求する。
  //   * 実写は紙が傾くので、隣の括弧の塊が 30% ほど持ち上がって見える（実測:
  //     `(x + 1)(x - 2) = 0` が `(x + 1)^(x - 2) = 0` になった）。塊は基準と同じ大きさなので、
  //     大きさの条件で落ちる。
  //   * 逆に分数の指数（(1/3)^(1/4) の 1/4）は持ち上がりが小さいが、基準より小さい。
  //     ここを落とすと `1/3 * 1/4 = 1/12` と読んでしまう（selftest が捕まえた）。
  return s.base_y < base.cy();
}

// ---------------------------------------------------------------- 括弧と数字を直す
//
// 検出器から見ると `(` `)` と `6` `0` `1` は似ている（実測: 実写で `(x + 1)(x - 2) = 0` の
// `)` が `2` に、`3.7 × (2 - 0.4)` の `(` が `6` になった。ユーザからも指摘された）。
// 字の形では迷うが、**大きさの比**では迷わない: 括弧は**背が高くて細い**
// （実測値: 括弧 h≈48..51 で w/h≈0.31..0.36、数字 h≈38..40 で w/h≈0.45..0.63）。
//
// 向き（開くのか閉じるのか）は箱では分からないので**並びで決める**:
//   * 先頭 / 直前が演算子 / 直前が開き括弧 -> 開き
//   * 末尾 / 直後が演算子 -> 閉じ
//   * それ以外は開いた数と閉じた数の差で決める
inline void fix_parens(std::vector<Sym>& v) {
  // 数字の高さの中央値を尺度にする（上付きや括弧を混ぜると尺度がぶれる）
  std::vector<int> hs;
  for (const Sym& s : v)
    if (!s.atom && s.cls.size() == 1 && s.cls[0] >= '0' && s.cls[0] <= '9') hs.push_back(s.h());
  if (hs.size() < 2) return;
  std::sort(hs.begin(), hs.end());
  const int med = std::max(1, hs[hs.size() / 2]);
  const auto is_op = [](const std::string& c) {
    return c == "+" || c == "-" || c == "=" || c == "times" || c == "div" || c == "dot";
  };
  int open = 0;
  for (size_t i = 0; i < v.size(); ++i) {
    Sym& s = v[i];
    if (s.atom) continue;
    if (s.cls == "(") { ++open; continue; }
    if (s.cls == ")") { --open; continue; }
    const bool digit = s.cls.size() == 1 && s.cls[0] >= '0' && s.cls[0] <= '9';
    if (!digit) continue;
    // 実測値で決めた（括弧 h/med≈1.2..1.3 & w/h≈0.31..0.36、数字 1.0 & 0.45..0.63。
    // 1.25 倍にすると h=49 / med=40 の閉じ括弧を 1px 差で逃した）
    if (s.h() * 100 < med * 115) continue;           // 背が高くなければ数字のまま
    if (s.w() * 100 > s.h() * 40) continue;          // 細くなければ数字のまま（`1` は 0.45）
    const bool first = i == 0;
    const bool last = i + 1 >= v.size();
    const std::string prev = first ? std::string() : v[i - 1].cls;
    const std::string next = last ? std::string() : v[i + 1].cls;
    bool opening;
    if (first || is_op(prev) || prev == "(") opening = true;
    else if (last || is_op(next)) opening = false;
    else opening = open <= 0;
    s.cls = opening ? "(" : ")";
    open += opening ? 1 : -1;
  }
}

// **相手のいない演算子は落とす。** プリントの答え欄（四角）が `÷` や `+` として検出される
// ことがあり、`3.7 × (2 - 0.4) + 0.96 ÷ 1.2 = □` の右辺に 1 個だけ残って解析が落ちた
// （実測: 「解釈できない記号: div」）。合成データには末尾の演算子が出ないので、ここは実写専用。
// 先頭の `-` は単項マイナスなので残す。
// **相手のいない括弧を端から落とす。** 実写では紙の端や印がもう 1 つの括弧として拾われる
// （実測: `(x - 2)^2 + 3(x - 1)` の後ろに中括弧の右が 1 つ入って解析が落ちた）。
// 落とすのは**端にあって数が合わないものだけ**（中に入っているものは構造なので触らない）。
inline void drop_unmatched_brackets(std::vector<Sym>& v) {
  for (int pass = 0; pass < 2; ++pass) {
    const char* lname = pass == 0 ? "(" : "brace_l";
    const char* rname = pass == 0 ? ")" : "brace_r";
    int open = 0, close = 0;
    for (const Sym& s : v) {
      if (s.atom) continue;
      if (s.cls == lname) ++open;
      else if (s.cls == rname) ++close;
    }
    while (close > open && !v.empty()) {           // 末尾の余った閉じを落とす
      size_t last = v.size();
      for (size_t i = v.size(); i-- > 0;)
        if (!v[i].atom && v[i].cls == rname) { last = i; break; }
      if (last == v.size()) break;
      v.erase(v.begin() + (long)last);
      --close;
    }
    while (open > close && !v.empty()) {           // 先頭の余った開きを落とす
      size_t first = v.size();
      for (size_t i = 0; i < v.size(); ++i)
        if (!v[i].atom && v[i].cls == lname) { first = i; break; }
      if (first == v.size()) break;
      v.erase(v.begin() + (long)first);
      --open;
    }
  }
}

inline void strip_dangling(std::vector<Sym>& v) {
  const auto binary_only = [](const std::string& c) {
    return c == "+" || c == "times" || c == "div" || c == "dot";
  };
  while (!v.empty() && !v.back().atom &&
         (binary_only(v.back().cls) || v.back().cls == "-"))
    v.pop_back();
  while (!v.empty() && !v.front().atom && binary_only(v.front().cls))
    v.erase(v.begin());
}

inline ex::E parse_flat(std::vector<Sym> v, std::string* why) {
  using namespace ex;
  if (v.empty()) { *why = "記号がありません"; return num(Rat(0)); }
  std::sort(v.begin(), v.end(), by_x);

  // 0) 横棒を直す（= が 2 本の棒に、マイナスが分数線や根号の上線に化けるのを構造で戻す）
  fix_bars(v, median_h(v));
  std::sort(v.begin(), v.end(), by_x);
  // 0.5) 背が高くて細い数字は括弧（形では迷うが、大きさの比では迷わない）
  fix_parens(v);
  // 0.6) 相手のいない演算子と括弧を落とす（答え欄の四角や紙の端が記号として出ることがある）
  strip_dangling(v);
  drop_unmatched_brackets(v);
  if (v.empty()) { *why = "記号がありません"; return num(Rat(0)); }

  // 1) 構造を全部畳む（外側から内側へ）
  while (collapse_one(v, why)) {
    if (!why->empty()) return num(Rat(0));
  }
  if (!why->empty()) return num(Rat(0));

  // 1.5) 関数名を戻す（sin(x) / cos(x) / ln(x)）。**fix_ones より前**にやる:
  //      ln の l は検出器から "1" として届くので、1 に寄せられる前に名前として拾う
  fix_fnnames(v);

  // 2) 桁をまとめる（その前に、縦棒だけの `1` が `l` になっているのを戻す）
  fix_ones(v, median_h(v));
  merge_digits(v);

  // 3) = で割る。**右が空なら左だけの式として扱う**（プリントの「… = □」の形。
  //    答えを書く四角は読まないので、右辺には何も残らない）
  for (size_t i = 0; i < v.size(); ++i)
    if (!v[i].atom && v[i].cls == "=") {
      std::vector<Sym> l(v.begin(), v.begin() + (long)i), r(v.begin() + (long)i + 1, v.end());
      strip_dangling(l);
      strip_dangling(r);
      if (r.empty() && !l.empty()) return parse_flat(l, why);
      if (l.empty() && !r.empty()) return parse_flat(r, why);
      const E a = parse_flat(l, why);
      if (!why->empty()) return num(Rat(0));
      const E b = parse_flat(r, why);
      if (!why->empty()) return num(Rat(0));
      return eq(a, b);
    }

  // 4) ± で割る（右から。左結合にするため）。先頭の ± は単項として扱う
  for (size_t i = v.size(); i-- > 1;) {
    if (v[i].atom) continue;
    const std::string& c = v[i].cls;
    if (c != "+" && c != "-") continue;
    std::vector<Sym> l(v.begin(), v.begin() + (long)i), r(v.begin() + (long)i + 1, v.end());
    if (l.empty() || r.empty()) { *why = "演算子の両側が空です"; return num(Rat(0)); }
    const E a = parse_flat(l, why);
    if (!why->empty()) return num(Rat(0));
    const E b = parse_flat(r, why);
    if (!why->empty()) return num(Rat(0));
    return c == "+" ? mk_add(a, b) : mk_sub(a, b);
  }
  if (!v[0].atom && (v[0].cls == "+" || v[0].cls == "-") && v.size() > 1) {
    std::vector<Sym> r(v.begin() + 1, v.end());
    const E a = parse_flat(r, why);
    if (!why->empty()) return num(Rat(0));
    return v[0].cls == "-" ? mk_neg(a) : a;
  }

  // 5) × と ÷ で割る（右から。左結合にするため）。± より内側で、並置より外側
  for (size_t i = v.size(); i-- > 1;) {
    if (v[i].atom) continue;
    const std::string& c = v[i].cls;
    if (c != "times" && c != "div") continue;
    std::vector<Sym> l(v.begin(), v.begin() + (long)i), r(v.begin() + (long)i + 1, v.end());
    if (l.empty() || r.empty()) { *why = "演算子の両側が空です"; return num(Rat(0)); }
    const E a = parse_flat(l, why);
    if (!why->empty()) return num(Rat(0));
    const E b = parse_flat(r, why);
    if (!why->empty()) return num(Rat(0));
    // ÷ は「割り算をする所」なので raw では演算に残す（縦の分数と扱いが違う）
    if (c == "div" && raw_mode()) return ex::raw(ex::Kind::Fn, {a, b}, "op_div");
    return c == "times" ? mk_mul(a, b) : ex::div(a, b);
  }

  // 6) 並置（掛け算）と上付き。**数のすぐ右の分数は帯分数**（2 5/8 = 2 + 5/8）
  const int h_ref = median_h(v);
  std::vector<E> factors;
  std::vector<bool> add_it;                          // その因子は掛けるのではなく足す
  for (size_t i = 0; i < v.size();) {
    const Sym base = v[i];
    E b = leaf(base, why);
    if (!why->empty()) return num(Rat(0));
    const bool mixed = i > 0 && base.atom && base.from_frac && is_digit_cls(v[i - 1]);
    size_t k = i + 1;
    std::vector<Sym> sup;
    while (k < v.size() && is_sup(base, v[k], h_ref)) sup.push_back(v[k++]);
    if (!sup.empty()) {
      const E p = parse_flat(sup, why);
      if (!why->empty()) return num(Rat(0));
      b = pow_e(b, p);
    }
    factors.push_back(b);
    add_it.push_back(mixed);
    i = k;
  }
  if (factors.empty()) { *why = "式になりません"; return num(Rat(0)); }
  E r = factors[0];
  for (size_t i = 1; i < factors.size(); ++i)
    r = add_it[i] ? mk_add(r, factors[i]) : mk_mul(r, factors[i]);
  return r;
}

inline Result parse(const std::vector<Sym>& in) {
  Result r;
  std::string why;
  raw_mode() = false;
  r.e = parse_flat(in, &why);
  if (!why.empty()) { r.why = why; return r; }
  r.ok = true;
  r.text = ex::to_infix(r.e);
  return r;
}

// 畳まないで読む（小学校の計算の手順を出すため）。**同じ枠の列**から作るので、
// 通常の parse と食い違うことはない
inline Result parse_raw(const std::vector<Sym>& in) {
  Result r;
  std::string why;
  raw_mode() = true;
  r.e = parse_flat(in, &why);
  raw_mode() = false;
  if (!why.empty()) { r.why = why; return r; }
  r.ok = true;
  r.text = ex::to_infix(r.e);
  return r;
}

// ---------------------------------------------------------------- 行に分ける
//
// 教科書のページは 1 問ずつ切るのが面倒なので、**囲った範囲に何行あっても読める**ようにする。
//
// 分け方は「y の区間を重なりで束ねる」だけ。上付きは親と縦に重なるので同じ行に残り、
// 分数の分子・分母も横線と重なるので同じ行になる。別の問題の行との間には隙間があるので切れる。
// ベースラインの近さで分けると、上付き（0.45em 持ち上がる）が別行になってしまう。
inline std::vector<std::vector<Sym>> split_lines(const std::vector<Sym>& in) {
  std::vector<std::vector<Sym>> out;
  if (in.empty()) return out;
  std::vector<size_t> idx(in.size());
  for (size_t i = 0; i < idx.size(); ++i) idx[i] = i;
  std::sort(idx.begin(), idx.end(),
            [&](size_t a, size_t b) { return in[a].y0 < in[b].y0; });
  std::vector<int> lo, hi;                            // 束ねた y の区間
  std::vector<std::vector<Sym>> bands;
  for (size_t k = 0; k < idx.size(); ++k) {
    const Sym& s = in[idx[k]];
    if (!bands.empty() && s.y0 <= hi.back()) {        // 前の帯と重なる -> 同じ行
      hi.back() = std::max(hi.back(), s.y1);
      bands.back().push_back(s);
      continue;
    }
    lo.push_back(s.y0);
    hi.push_back(s.y1);
    bands.push_back({s});
  }
  for (std::vector<Sym>& b : bands) {
    std::sort(b.begin(), b.end(), by_x);
    out.push_back(b);
  }
  return out;
}

// 1 行を**横の隙間**で区切る（段組みと問題番号を分けるため）。
//
// 教科書の 1 行には「(1)  3x^2 - 5 = 4      (2)  x^2 - 6x + 5 = 0」のように**2 問と番号**が
// 並ぶ。まとめて 1 式として読ませると当然壊れる（実測: 「演算子の両側が空です」）。
// 式の中の隙間（字の間）と、問題の間の隙間は**大きさが桁違い**なので、字の高さを尺度にして
// 切る。番号の「(1)」もこれで独立した塊になり、式の側は綺麗に残る。
//
// 尺度は**字の高さの中央値**にする（幅は数字と分数で大きく違うが、高さは揃っている）。
inline std::vector<std::vector<Sym>> split_cells(const std::vector<Sym>& in,
                                                double gap_factor = 1.2) {
  std::vector<std::vector<Sym>> out;
  if (in.empty()) return out;
  std::vector<Sym> s = in;
  std::sort(s.begin(), s.end(), by_x);
  std::vector<int> hs;
  for (const Sym& t : s) hs.push_back(t.h());
  std::sort(hs.begin(), hs.end());
  const int med_h = std::max(1, hs[hs.size() / 2]);
  const int gap = (int)(med_h * gap_factor);
  std::vector<Sym> cur{s[0]};
  int right = s[0].x1;
  for (size_t i = 1; i < s.size(); ++i) {
    if (s[i].x0 - right > gap) {
      out.push_back(cur);
      cur.clear();
    }
    cur.push_back(s[i]);
    right = std::max(right, s[i].x1);
  }
  if (!cur.empty()) out.push_back(cur);
  return out;
}

// 1 つの塊とその読み（parse_or_split が返す）
struct Piece {
  Result r;
  std::vector<Sym> syms;
  int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
};

// **読めない塊は横の隙間で割って読み直す。**
//
// プリントは `式 = □` の形で、答え欄の四角が問題どうしの隙間を埋めてしまう。射影で切ると
// 1 塊に 2 問（と番号）が入り、まとめて解析して落ちる（実測: 小学校のページはページ渡しで
// 0/6）。**記号の位置はもう分かっている**ので、割り直しに検出はいらない。
// 読めた断片だけ返す。1 つも読めなければ、元の失敗をそのまま返す（嘘を作らない）。
inline std::vector<Piece> parse_or_split(const std::vector<Sym>& syms) {
  const auto box = [](const std::vector<Sym>& v, Piece& p) {
    if (v.empty()) return;
    p.x0 = v[0].x0; p.y0 = v[0].y0; p.x1 = v[0].x1; p.y1 = v[0].y1;
    for (const Sym& s : v) {
      p.x0 = std::min(p.x0, s.x0); p.y0 = std::min(p.y0, s.y0);
      p.x1 = std::max(p.x1, s.x1); p.y1 = std::max(p.y1, s.y1);
    }
  };
  std::vector<Piece> out;
  Piece whole;
  whole.r = parse(syms);
  whole.syms = syms;
  box(syms, whole);
  if (whole.r.ok) { out.push_back(whole); return out; }
  const std::vector<std::vector<Sym>> parts = split_cells(syms);
  if (parts.size() < 2) { out.push_back(whole); return out; }
  for (const std::vector<Sym>& pv : parts) {
    Piece p;
    p.r = parse(pv);
    if (!p.r.ok) continue;
    p.syms = pv;
    box(pv, p);
    out.push_back(p);
  }
  if (out.empty()) out.push_back(whole);
  return out;
}

// 行ごとに解析する。**1 行も読めなくても空を返すだけ**（呼ぶ側が「読めなかった」を出す）
inline std::vector<Result> parse_lines(const std::vector<Sym>& in) {
  std::vector<Result> out;
  for (const std::vector<Sym>& line : split_lines(in)) out.push_back(parse(line));
  return out;
}

}  // namespace pl
