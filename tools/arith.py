"""小学校の計算の**手順**を出す（Python 側）— pure/arith.hpp の鏡。

なぜ別のファイルが要るか: CAS は `1.8 × 3.5 - (10.2 - 6.8)` を読んだ時点で `2.9` に畳む。
畳まれた木からは「どこを先に計算したか」が復元できないので、**畳まない木**（raw）を作って、
内側から 1 手ずつ畳んでいく。畳む順序は木の形がそのまま持っている（括弧が深い、
× ÷ が + - より深い）ので、いちばん深くて左にある「両側が数の演算」から畳むだけでよい。

  python tools/arith.py --expr "{1.8 × 3.5 - (10.2 - 6.8)} × 9"
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import expr as X      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def is_op(e):
    """畳まない演算子（Fn の名前が op_ で始まる）。"""
    return e.k == X.FN and len(e.name) > 3 and e.name.startswith("op_")


def op_prec(n):
    if n in ("op_add", "op_sub"):
        return 1
    if n in ("op_mul", "op_div"):
        return 2
    if n == "op_neg":
        return 3
    if n == "op_pow":
        return 4
    return 5                                          # op_mixed は 1 つの数として扱う


def to_text(e, dec_ok=False, parent=0):
    """畳まない木を、書かれた順のままの文字列にする。

    **小数で書くのは、元の式が小数で書かれていたときだけ**。分数の問題で `5/8` を `0.625`
    と書いたら、小学校の答えとしては嘘になる。
    """
    if e.k == X.NUM:
        if not dec_ok:
            return str(e.num)
        dec = X.to_decimal(e.num)
        return dec if dec else str(e.num)
    if e.k == X.FN and e.name == "op_mixed" and len(e.kids) == 3:
        return "%s %s/%s" % (to_text(e.kids[0], dec_ok, 5), to_text(e.kids[1], dec_ok, 5),
                             to_text(e.kids[2], dec_ok, 5))
    if not is_op(e):
        return X.to_infix(e)                          # 変数や根号が混ざったらそのまま
    n = e.name
    p = op_prec(n)
    if n == "op_neg":
        s = "-" + to_text(e.kids[0], dec_ok, p)
    else:
        sym = {"op_add": " + ", "op_sub": " - ", "op_mul": " × ",
               "op_div": " ÷ "}.get(n, "^")
        # 左結合なので、右側は同じ優先順位でも括弧が要る（8 - (3 - 1) は 8 - 3 - 1 ではない）
        s = to_text(e.kids[0], dec_ok, p) + sym + to_text(e.kids[1], dec_ok, p + 1)
    return "(" + s + ")" if p < parent else s


class Step:
    __slots__ = ("rule", "note", "after")

    def __init__(self, rule, note, after):
        self.rule = rule
        self.note = note
        self.after = after


def find_innermost(e, depth, state):
    """いちばん深くて左にある「両側が数の演算」を探す。state = [best_depth, best]。"""
    found = False
    if is_op(e) or (e.k == X.FN and e.name == "op_mixed"):
        for c in e.kids:
            if find_innermost(c, depth + 1, state):
                found = True
        if not found:
            if all(X.is_num(c) for c in e.kids):
                if depth > state[0]:
                    state[0], state[1] = depth, e
                return True
    return found


def fold_once(e, target, value):
    """1 手だけ畳む（見つけた場所を値に置き換えた木を返す）。"""
    if e is target:
        return value
    if not e.kids:
        return e
    ks, changed = [], False
    for c in e.kids:
        r = fold_once(c, target, value)
        changed = changed or (r is not c)
        ks.append(r)
    return X.raw(e.k, ks, e.name) if changed else e


def apply(n, a, b):
    """演算 1 つを計算する。計算できないときは None。"""
    if n == "op_add":
        return a + b
    if n == "op_sub":
        return a - b
    if n == "op_mul":
        return a * b
    if n == "op_div":
        return None if b.is_zero() else a / b
    if n == "op_pow":
        if not b.is_int() or b.neg() or b.n > 8:
            return None
        return X.rpow(a, b.n)
    return None


def rule_of(n, depth):
    if n == "op_mixed":
        return "帯分数を仮分数に直す"
    if depth > 1:
        return "かっこの中を計算"
    if n in ("op_mul", "op_div"):
        return "かけ算・わり算を先に"
    if n == "op_pow":
        return "累乗を先に"
    return "たし算・ひき算"


class Result:
    def __init__(self):
        self.ok = False
        self.steps = []
        self.value = None


def eval_steps(root, dec_ok=False, max_steps=40):
    """内側から 1 手ずつ畳む（C++ の ar::eval_steps と同じ順序・同じ文言）。"""
    r = Result()
    cur = root
    for _ in range(max_steps):
        if X.is_num(cur):
            r.ok = True
            r.value = cur
            return r
        if cur.k == X.FN and cur.name == "op_neg" and X.is_num(cur.kids[0]):
            cur = X.num(-cur.kids[0].num)
            continue
        state = [-1, None]
        if not find_innermost(cur, 0, state) or state[1] is None:
            break
        target = state[1]
        if target.name == "op_neg":
            val = -target.kids[0].num
        elif target.name == "op_mixed":
            # 帯分数を仮分数に直す（2 5/8 -> 21/8）。人が紙に書く最初の手
            w, a, b = target.kids[0].num, target.kids[1].num, target.kids[2].num
            if b.is_zero():
                break
            val = (w - a / b) if w.neg() else (w + a / b)
        else:
            val = apply(target.name, target.kids[0].num, target.kids[1].num)
            if val is None:
                break
        dec = X.to_decimal(val)
        shown = dec if (dec_ok and dec) else str(val)
        piece = to_text(target, dec_ok) + " = " + shown
        nxt = fold_once(cur, target, X.num(val))
        r.steps.append(Step(rule_of(target.name, state[0]), piece, to_text(nxt, dec_ok)))
        cur = nxt
    r.value = cur
    r.ok = X.is_num(cur)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expr", required=True)
    a = ap.parse_args()
    e, err = X.parse_raw(a.expr)
    if err:
        print("parse error: %s" % err)
        return 1
    dec_ok = "." in a.expr
    r = eval_steps(e, dec_ok)
    for i, st in enumerate(r.steps, 1):
        print("%d. [%s] %s" % (i, st.rule, st.note))
        print("   %s" % st.after)
    print(to_text(r.value, dec_ok) if r.value is not None else "(計算できない)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
