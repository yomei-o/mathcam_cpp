// WASM の入口 — ブラウザが CLI と同じ道を通る。
//
// ページが models/sym_det_v5.onnx を取ってきてバイト列を渡し、RGBA のフレームを push すると、
// **記号の枠・読めた式・解き方の手順**が JSON で返る。推論ライブラリは使わない
// （pure/onnx_run.hpp を emcc でビルドしたもの）。
//
// 気をつける点（どれも実測で踏んだ）:
//   * letterbox は**双線形**で拡縮する。最近傍にすると、小さい画像が 10 倍に拡大されたときに
//     字がブロック状になり、学習時（cv2 の bilinear）と別物になって読み間違える
//     （端から端までの正解率が 72.5% -> 98.3% に変わった）。pipeline.hpp がそれをやる。
//   * v8 の NMS はクラスごとなので、同じ字が別クラスで二重に残る。クラスを無視した
//     重複除去も pipeline.hpp に入っている（"5" と "3" が重なって "53" と読まれた）。
//   * 箱の形は export 依存。Ultralytics の素の export は cxcywh。
//   * **答えの文言は slv::answer_lines だけが作る**（CLI と同じ関数）。ここで書き分けると
//     ブラウザと CLI で言い方が違うアプリになる。
#include "pipeline.hpp"
#include "solve.hpp"
#include "arith.hpp"
#include <emscripten/emscripten.h>
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

static onx::Graph g_graph;
static bool g_ok = false;
static std::string g_result = "{}";

static std::string esc(const std::string& s) {
  std::string o;
  for (char c : s) {
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if ((unsigned char)c < 0x20) { o += ' '; }
    else o += c;
  }
  return o;
}

static std::string arr(const std::vector<std::string>& v) {
  std::string s = "[";
  for (size_t i = 0; i < v.size(); ++i) s += (i ? ",\"" : "\"") + esc(v[i]) + "\"";
  return s + "]";
}

// 1 行ぶんの結果（式・手順・答え）を JSON の中身にする（{ } は付けない）。
// syms を渡すと、計算問題のときに**小学校の順序の手順**も返す（畳まない木で読み直す）。
static std::string one_json(const pl::Result& r, const std::vector<pl::Sym>* syms = nullptr) {
  if (!r.ok) return "\"error\":\"" + esc(r.why) + "\"";
  // **計算問題は「書かれたとおり」を見せる**（畳んだ木の印字だと答えの数が式の欄に出る）
  std::string shown = r.text, shown_tex = ex::to_latex(r.e);
  const bool is_rel = r.e->k == ex::Kind::Rel || r.e->k == ex::Kind::Sys;
  std::vector<std::string> vs0;
  ex::collect_syms(r.e, vs0);
  if (syms && !is_rel && vs0.empty()) {
    bool dec0 = false;
    for (const pl::Sym& s0 : *syms)
      if (s0.cls == "dot") dec0 = true;
    const pl::Result rr0 = pl::parse_raw(*syms);
    if (rr0.ok) {
      shown = ar::to_text(rr0.e, dec0);
      shown_tex = ar::to_latex_raw(rr0.e, dec0);
    }
  }
  std::string js = "\"expr\":\"" + esc(shown) + "\",\"latex\":\"" + esc(shown_tex) + "\"";
  const slv::Solution sol = slv::solve(r.e);
  if (!sol.ok) {
    // 方程式でなければ計算問題として値を出す
    const ex::E v = ex::expand(r.e);
    js += ",\"kind\":\"value\",\"answer\":[\"" + esc(ex::to_infix(v)) + "\"]";
    js += ",\"answer_latex\":[\"" + esc(ex::to_latex(v)) + "\"]";
    // 割り切れる分数は小数でも返す（小学校の計算は小数で答える）
    if (ex::is_num(v) && !v->num.is_int()) {
      const std::string dec = ex::to_decimal(v->num);
      if (!dec.empty()) js += ",\"decimal\":\"" + esc(dec) + "\"";
    }
    // 1 手ずつの計算（かっこの中 -> かけ算・わり算 -> たし算・ひき算）
    if (syms) {
      bool dec_ok = false;
      for (const pl::Sym& s : *syms)
        if (s.cls == "dot") dec_ok = true;
      const pl::Result rr = pl::parse_raw(*syms);
      if (rr.ok) {
        const ar::Result ares = ar::eval_steps(rr.e, dec_ok);
        if (ares.ok) {
          js += ",\"steps\":[";
          for (size_t i = 0; i < ares.steps.size(); ++i) {
            js += (i ? ",{" : "{");
            js += "\"rule\":\"" + esc(ares.steps[i].rule) + "\",\"note\":\"" +
                  esc(ares.steps[i].note) + "\",\"after\":\"" + esc(ares.steps[i].after) +
                  "\",\"after_latex\":\"" + esc(ares.steps[i].after) + "\"}";
          }
          js += "]";
        }
      }
    }
    return js;
  }
  js += ",\"kind\":\"" + esc(sol.kind) + "\",\"var\":\"" + esc(sol.var) + "\",\"steps\":[";
  for (size_t i = 0; i < sol.steps.size(); ++i) {
    const slv::Step& st = sol.steps[i];
    js += (i ? ",{" : "{");
    js += "\"rule\":\"" + esc(st.rule) + "\",\"note\":\"" + esc(st.note) +
          "\",\"after\":\"" + esc(ex::to_infix(st.after)) + "\",\"after_latex\":\"" +
          esc(ex::to_latex(st.after)) + "\"}";
  }
  js += "],\"answer\":" + arr(slv::answer_lines(sol));
  js += ",\"answer_latex\":" + arr(slv::answer_lines(sol, true));
  return js;
}

// 記号の枠を JSON の配列にする（"syms":[...] の中身。x 順に並べる）。
// **確からしさも返す**（ブラウザで枠に出すと、どの記号が危ういのかがすぐ分かる）。
static std::string syms_json(const std::vector<pl::Sym>& syms) {
  std::vector<pl::Sym> sorted = syms;
  std::sort(sorted.begin(), sorted.end(), pl::by_x);
  std::string js = "[";
  for (size_t i = 0; i < sorted.size(); ++i) {
    const pl::Sym& s = sorted[i];
    char sc[16];
    std::snprintf(sc, sizeof(sc), "%.2f", (double)s.score);
    js += (i ? ",{" : "{");
    js += "\"cls\":\"" + esc(s.cls) + "\",\"x0\":" + std::to_string(s.x0) +
          ",\"y0\":" + std::to_string(s.y0) + ",\"x1\":" + std::to_string(s.x1) +
          ",\"y1\":" + std::to_string(s.y1) + ",\"score\":" + sc + "}";
  }
  return js + "]";
}

extern "C" {

EMSCRIPTEN_KEEPALIVE int mc_load(const unsigned char* buf, int len) {
  g_graph = onx::parse_onnx(buf, (size_t)len);
  g_ok = !g_graph.nodes.empty();
  return g_ok ? (int)g_graph.nodes.size() : -1;
}

// 1 フレーム。返り値は検出した記号の数（負なら失敗）。詳細は mc_result() の JSON。
EMSCRIPTEN_KEEPALIVE int mc_run(const unsigned char* rgba, int w, int h, int imgsz, float conf) {
  if (!g_ok) { g_result = "{\"error\":\"model not loaded\"}"; return -1; }
  if (w <= 0 || h <= 0) { g_result = "{\"error\":\"empty frame\"}"; return -1; }
  // RGBA -> RGB（検出器は 3ch）
  std::vector<unsigned char> rgb((size_t)w * h * 3);
  for (size_t i = 0; i < (size_t)w * h; ++i) {
    rgb[i * 3] = rgba[i * 4];
    rgb[i * 3 + 1] = rgba[i * 4 + 1];
    rgb[i * 3 + 2] = rgba[i * 4 + 2];
  }
  const pipeln::Detected det =
      pipeln::detect_syms(g_graph, rgb.data(), w, h, imgsz > 0 ? imgsz : 640,
                          conf > 0.f ? conf : 0.20f, 0.45f, BoxFmt::CXCYWH);

  std::string js = "{\"count\":" + std::to_string(det.syms.size()) +
                   ",\"syms\":" + syms_json(det.syms);

  // 全体を 1 式として読んだ結果（今までと同じ形）。ページの一部を囲んだときは
  // **行ごとの結果**も返す（教科書は 1 問ずつ切るのが面倒なので）
  js += "," + one_json(pl::parse(det.syms), &det.syms);
  const std::vector<std::vector<pl::Sym>> line_syms = pl::split_lines(det.syms);
  js += ",\"lines\":[";
  for (size_t i = 0; i < line_syms.size(); ++i)
    js += (i ? ",{" : "{") + one_json(pl::parse(line_syms[i]), &line_syms[i]) + "}";
  js += "]}";
  g_result = js;
  return (int)det.syms.size();
}

// ページや欄をまるごと**塊ごとに**読む。CLI の photo --auto-cells と同じ道
// （pipeln::detect_by_cells）。行の帯で位置を取り、塊ごとに元画像から読み直す 2 段構え。
//
// 広い範囲をそのまま 640 に縮めると字が潰れて何も出ない（実測: 4 問ぶん 1140x350 を囲むと
// 7 記号しか出なかった）。**先にインクの横方向の射影で行に切り、行ごとに検出する**と、
// 各行が 640 に拡大されるので字の大きさが学習時に近くなる。
EMSCRIPTEN_KEEPALIVE int mc_run_lines(const unsigned char* rgba, int w, int h, int imgsz,
                                      float conf) {
  if (!g_ok) { g_result = "{\"error\":\"model not loaded\"}"; return -1; }
  if (w <= 0 || h <= 0) { g_result = "{\"error\":\"empty frame\"}"; return -1; }
  std::vector<unsigned char> rgb((size_t)w * h * 3);
  for (size_t i = 0; i < (size_t)w * h; ++i) {
    rgb[i * 3] = rgba[i * 4];
    rgb[i * 3 + 1] = rgba[i * 4 + 1];
    rgb[i * 3 + 2] = rgba[i * 4 + 2];
  }
  // 塊を 1 つ読むたびに進捗を返す（ページ 1 枚で 30 秒級。何も出ないと壊れて見える）
  const std::vector<pipeln::Cell> cells = pipeln::detect_by_cells(
      g_graph, rgb.data(), w, h, imgsz > 0 ? imgsz : 640, conf > 0.f ? conf : 0.20f, 0.45f,
      BoxFmt::CXCYWH, 35, 25,
      [](int done, int total, void*) {
        // **postMessage が無い所でも動くようにする**（node での検査は Worker ではない。
        // 素で呼ぶと ReferenceError で mc_run_lines が落ちた）
        EM_ASM({
          if (typeof postMessage === 'function')
            postMessage({type : 'progress', done : $0, total : $1});
        }, done, total);
      },
      nullptr);
  int total = 0;
  bool first = true;
  std::string js = "{\"mode\":\"lines\",\"lines\":[";
  for (const pipeln::Cell& c : cells) {
    // 読めない塊は横の隙間で割って読み直す（答え欄の四角が問題の隙間を埋めるため）
    for (const pl::Piece& pc : pl::parse_or_split(c.syms)) {
      // 問題番号（「(1)」など）と、記号が 2 つ以下で読めない塊は出さない。**記号の数でも
      // 縛る**（小学校の計算は値が数になるので、数だけを条件にすると式そのものが消える）
      if (pc.r.ok && ex::is_num(pc.r.e) && pc.syms.size() <= 4) continue;
      if (!pc.r.ok && pc.syms.size() < 3) continue;
      total += (int)pc.syms.size();
      js += (first ? "{" : ",{");
      first = false;
      js += "\"x0\":" + std::to_string(pc.x0) + ",\"y0\":" + std::to_string(pc.y0) +
            ",\"x1\":" + std::to_string(pc.x1) + ",\"y1\":" + std::to_string(pc.y1) +
            ",\"syms\":" + syms_json(pc.syms) + ",";
      js += one_json(pc.r, &pc.syms) + "}";
    }
  }
  js += "],\"count\":" + std::to_string(total) + "}";
  g_result = js;
  return total;
}

EMSCRIPTEN_KEEPALIVE const char* mc_result() { return g_result.c_str(); }

}  // extern "C"
