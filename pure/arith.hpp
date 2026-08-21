// 小学校の計算の**手順**を出す。
//
// なぜ別のファイルが要るか: CAS は `1.8 × 3.5 - (10.2 - 6.8)` を読んだ時点で `2.9` に畳む。
// 畳まれた木からは「どこを先に計算したか」が復元できないので、**畳まない木**（raw）を作って、
// 内側から 1 手ずつ畳んでいく。畳む順序は木の形がそのまま持っている（括弧が深い、
// × ÷ が + - より深い）ので、**いちばん深くて左にある「両側が数の演算」から畳む**だけでよい。
//
// 手順の文言は「かっこの中を計算」「かけ算・わり算を先に」「たし算・ひき算」の 3 つ。
// 小学校で習う順序そのもので、これ以上細かくすると読めなくなる。
#pragma once
#include "expr.hpp"
#include <string>
#include <vector>

namespace ar {

// 畳まない演算子。Kind::Fn の名前で持つ（CAS は知らない名前の Fn をそのまま残すので、
// 正規化に巻き込まれない）。op_neg だけ子が 1 つ。
inline bool is_op(const ex::E& e) {
  return e->k == ex::Kind::Fn && e->name.size() > 3 && e->name.compare(0, 3, "op_") == 0;
}
inline ex::E op2(const std::string& name, const ex::E& a, const ex::E& b) {
  return ex::raw(ex::Kind::Fn, {a, b}, name);
}
inline ex::E op1(const std::string& name, const ex::E& a) {
  return ex::raw(ex::Kind::Fn, {a}, name);
}

inline int op_prec(const std::string& n) {
  if (n == "op_add" || n == "op_sub") return 1;
  if (n == "op_mul" || n == "op_div") return 2;
  if (n == "op_neg") return 3;
  if (n == "op_pow") return 4;
  return 5;                                          // op_mixed は 1 つの数として扱う
}

// 畳まない木を、書かれた順のままの文字列にする（手順表示に使う）。
//
// **小数で書くのは、元の式が小数で書かれていたときだけ**（dec を渡す）。分数の問題で
// `5/8` を `0.625` と書いたら、小学校の答えとしては嘘になる（実測でそうなっていた）。
inline std::string to_text(const ex::E& e, bool dec_ok = false, int parent = 0) {
  using namespace ex;
  if (e->k == Kind::Num) {
    if (!dec_ok) return e->num.str();
    const std::string dec = to_decimal(e->num);
    return dec.empty() ? e->num.str() : dec;
  }
  if (e->k == Kind::Fn && e->name == "op_mixed" && e->kids.size() == 3)
    return to_text(e->kids[0], dec_ok, 5) + " " + to_text(e->kids[1], dec_ok, 5) + "/" +
           to_text(e->kids[2], dec_ok, 5);           // 帯分数は 1 つの数として書く
  if (!is_op(e)) return to_infix(e);                  // 変数や根号が混ざったらそのまま
  const std::string& n = e->name;
  const int p = op_prec(n);
  std::string s;
  if (n == "op_neg") {
    s = "-" + to_text(e->kids[0], dec_ok, p);
  } else {
    const char* sym = n == "op_add"   ? " + "
                      : n == "op_sub" ? " - "
                      : n == "op_mul" ? " \xc3\x97 "     // ×
                      : n == "op_div" ? " \xc3\xb7 "     // ÷
                                      : "^";
    // 左結合なので、右側は同じ優先順位でも括弧が要る（8 - (3 - 1) は 8 - 3 - 1 ではない）
    s = to_text(e->kids[0], dec_ok, p) + sym + to_text(e->kids[1], dec_ok, p + 1);
  }
  return p < parent ? "(" + s + ")" : s;
}

// 手順 1 手
struct Step {
  std::string rule;     // 「かっこの中を計算」など
  std::string note;     // 実際に計算した部分（"10.2 - 6.8 = 3.4"）
  std::string after;    // その手のあとの式全体
};

// いちばん深くて左にある「両側が数の演算」を探す。深さも返す（括弧の中が先に来る）
inline bool find_innermost(const ex::E& e, int depth, int& best_depth, ex::E& best) {
  using namespace ex;
  bool found = false;
  if (is_op(e) || (e->k == Kind::Fn && e->name == "op_mixed")) {
    for (const E& c : e->kids)
      if (find_innermost(c, depth + 1, best_depth, best)) found = true;
    if (!found) {
      bool all_num = true;
      for (const E& c : e->kids) all_num = all_num && is_num(c);
      if (all_num) {
        if (depth > best_depth) { best_depth = depth; best = e; }
        return true;
      }
    }
  }
  return found;
}

// 1 手だけ畳む（見つけた場所を値に置き換えた木を返す）。畳めなければ空
inline ex::E fold_once(const ex::E& e, const ex::E& target, const ex::E& value) {
  using namespace ex;
  if (e.get() == target.get()) return value;
  if (e->kids.empty()) return e;
  std::vector<E> ks;
  bool changed = false;
  for (const E& c : e->kids) {
    E r = fold_once(c, target, value);
    changed = changed || r.get() != c.get();
    ks.push_back(r);
  }
  if (!changed) return e;
  return raw(e->k, ks, e->name);
}

// 演算 1 つを計算する。0 で割るときなど計算できないときは false
inline bool apply(const std::string& n, const ex::Rat& a, const ex::Rat& b, ex::Rat& out) {
  using namespace ex;
  if (n == "op_add") { out = a + b; return true; }
  if (n == "op_sub") { out = a - b; return true; }
  if (n == "op_mul") { out = a * b; return true; }
  if (n == "op_div") {
    if (b.is_zero()) return false;
    out = a / b;
    return true;
  }
  if (n == "op_pow") {
    if (!b.is_int() || b.neg() || b.n > 8) return false;
    out = rpow(a, b.n);
    return true;
  }
  return false;
}

inline std::string rule_of(const std::string& n, int depth) {
  if (n == "op_mixed") return "帯分数を仮分数に直す";
  if (depth > 1) return "かっこの中を計算";
  if (n == "op_mul" || n == "op_div") return "かけ算・わり算を先に";
  if (n == "op_pow") return "累乗を先に";
  return "たし算・ひき算";
}

// 内側から 1 手ずつ畳む。返り値は最後の値（ok=false なら手順は途中まで）
struct Result {
  bool ok = false;
  std::vector<Step> steps;
  ex::E value;
};

inline Result eval_steps(const ex::E& root, bool dec_ok = false, int max_steps = 40) {
  using namespace ex;
  Result r;
  E cur = root;
  for (int i = 0; i < max_steps; ++i) {
    if (is_num(cur)) { r.ok = true; r.value = cur; return r; }
    if (cur->k == Kind::Fn && cur->name == "op_neg" && is_num(cur->kids[0])) {
      cur = num(-cur->kids[0]->num);
      continue;
    }
    int best_depth = -1;
    E target;
    if (!find_innermost(cur, 0, best_depth, target) || !target) break;
    Rat val;
    if (target->name == "op_neg") {
      val = -target->kids[0]->num;
    } else if (target->name == "op_mixed") {
      // 帯分数を仮分数に直す（2 5/8 -> 21/8）。人が紙に書く最初の手
      const Rat w = target->kids[0]->num, a = target->kids[1]->num, b = target->kids[2]->num;
      if (b.is_zero()) break;
      val = w.neg() ? w - a / b : w + a / b;
    } else if (!apply(target->name, target->kids[0]->num, target->kids[1]->num, val)) {
      break;
    }
    const std::string shown =
        dec_ok && !to_decimal(val).empty() ? to_decimal(val) : val.str();
    const std::string piece = to_text(target, dec_ok) + " = " + shown;
    const E next = fold_once(cur, target, num(val));
    Step s;
    s.rule = rule_of(target->name, best_depth);
    s.note = piece;
    s.after = to_text(next, dec_ok);
    r.steps.push_back(s);
    cur = next;
  }
  r.value = cur;
  r.ok = is_num(cur);
  return r;
}

}  // namespace ar
