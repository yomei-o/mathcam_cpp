// WASM の入口 — ブラウザが CLI と同じ道を通る。
//
// ページが models/sym_det.onnx を取ってきてバイト列を渡し、RGBA のフレームを push すると、
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
#include "pipeline.hpp"
#include "solve.hpp"
#include <emscripten/emscripten.h>
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
  const pipe::Detected det =
      pipe::detect_syms(g_graph, rgb.data(), w, h, imgsz > 0 ? imgsz : 640,
                        conf > 0.f ? conf : 0.25f, 0.45f, BoxFmt::CXCYWH);

  std::string js = "{\"count\":" + std::to_string(det.syms.size()) + ",\"syms\":[";
  std::vector<pl::Sym> sorted = det.syms;
  std::sort(sorted.begin(), sorted.end(), pl::by_x);
  for (size_t i = 0; i < sorted.size(); ++i) {
    const pl::Sym& s = sorted[i];
    js += (i ? ",{" : "{");
    js += "\"cls\":\"" + esc(s.cls) + "\",\"x0\":" + std::to_string(s.x0) +
          ",\"y0\":" + std::to_string(s.y0) + ",\"x1\":" + std::to_string(s.x1) +
          ",\"y1\":" + std::to_string(s.y1) + "}";
  }
  js += "]";

  const pl::Result r = pl::parse(det.syms);
  if (!r.ok) {
    js += ",\"error\":\"" + esc(r.why) + "\"}";
    g_result = js;
    return (int)det.syms.size();
  }
  js += ",\"expr\":\"" + esc(r.text) + "\",\"latex\":\"" + esc(ex::to_latex(r.e)) + "\"";

  const slv::Solution sol = slv::solve(r.e);
  if (!sol.ok) {
    // 方程式でなければ計算問題として値を出す
    const ex::E v = ex::expand(r.e);
    js += ",\"answer\":[\"" + esc(ex::to_infix(v)) + "\"]";
    js += ",\"answer_latex\":[\"" + esc(ex::to_latex(v)) + "\"],\"kind\":\"value\"}";
    g_result = js;
    return (int)det.syms.size();
  }
  js += ",\"kind\":\"" + esc(sol.kind) + "\",\"var\":\"" + esc(sol.var) + "\",\"steps\":[";
  for (size_t i = 0; i < sol.steps.size(); ++i) {
    const slv::Step& st = sol.steps[i];
    js += (i ? ",{" : "{");
    js += "\"rule\":\"" + esc(st.rule) + "\",\"note\":\"" + esc(st.note) +
          "\",\"after\":\"" + esc(ex::to_infix(st.after)) + "\",\"after_latex\":\"" +
          esc(ex::to_latex(st.after)) + "\"}";
  }
  js += "],\"answer\":[";
  for (size_t i = 0; i < sol.roots.size(); ++i)
    js += (i ? ",\"" : "\"") + esc(ex::to_infix(sol.roots[i])) + "\"";
  js += "],\"answer_latex\":[";
  for (size_t i = 0; i < sol.roots.size(); ++i)
    js += (i ? ",\"" : "\"") + esc(ex::to_latex(sol.roots[i])) + "\"";
  js += "]}";
  g_result = js;
  return (int)det.syms.size();
}

EMSCRIPTEN_KEEPALIVE const char* mc_result() { return g_result.c_str(); }

}  // extern "C"
