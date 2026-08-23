// Build a yolov8 detector graph from nothing — the last thing the C++ lane could not do.
//
// Until now `jlpr train --model det` could only *fine-tune* an ONNX somebody else produced, which in
// practice meant Ultralytics (`YOLO('yolov8n.pt').export(...)`). This writes the whole graph here:
// backbone (Conv/C2f/SPPF), neck (upsample + concat + C2f), the Detect head, and the decode tail
// (DFL softmax, anchor points, strides) — so a detector can be created, trained and exported without
// PyTorch anywhere in the loop. The corner net already had this (`crn::build_graph`); this is the
// same idea at 200 nodes instead of 14.
//
// WHAT IS COPIED FROM ULTRALYTICS, EXACTLY:
//   * the yolov8n scaling rule — width 0.25 / depth 0.33 / max 1024 channels, each layer's channel
//     count `make_divisible(min(c, 1024) * width, 8)`, each C2f's repeat `max(1, round(n * depth))`;
//   * the module wiring of yolov8.yaml (layers 0-22, including which layers concat with which);
//   * torch's default init for Conv2d (uniform +-1/sqrt(fan_in)), BN gamma 1 / beta 0, and
//     `initialize_weights`' BN eps 1e-3 / momentum 0.03;
//   * `Detect.bias_init`: the box branch's last bias is 1.0 and the class branch's is
//     log(5 / nc / (640/stride)^2) — the "expect almost nothing" prior that keeps the first steps
//     from drowning in false positives;
//   * the exported decode tail node for node (Reshape/Concat/DFL/Slice/Sub/Add/Div/Mul/Concat),
//     read off models/plate_det_v8n_320.onnx so the output is the same [1, 4+nc, A] cxcywh tensor
//     pure/infer_v8.hpp already decodes.
//
// WHAT IS DELIBERATELY DIFFERENT: the graph keeps **BatchNormalization as its own node**. Ultralytics
// fuses BN into the convolution before exporting, which is right for inference and useless for
// training from scratch — a fresh network without BN does not converge. `jlpr fuse-bn` folds them
// afterwards, which is how the shipped file gets its inference shape back.
//
// 出どころ: 姉妹リポ yolo_lpr_cpp/pure/build_v8.hpp。既定値だけ mathcam に合わせた
// （nc=39・imgsz=640）。構造は同じなので、片方を直したらもう片方も見ること。
#pragma once
#include "onnx.hpp"
#include "rng.hpp"
#include <cmath>
#include <string>
#include <vector>

namespace v8b {

struct Cfg {
  int nc = 39;                // クラス数（mathcam の記号は 39 種）
  int imgsz = 640;            // アンカーとストライドを焼き込むので、大きさは固定
  int reg_max = 16;
  double width = 0.25;        // yolov8n
  double depth = 0.33;
  int max_ch = 1024;
};

inline int make_divisible(double v, int d = 8) {
  return (int)std::ceil(v / d) * d;
}

struct Builder {
  onx::Graph g;
  Rng rng;
  Cfg cfg;
  Builder(const Cfg& c, uint64_t seed) : rng(seed), cfg(c) {}

  int ch(int base) const { return make_divisible(std::min((double)base, (double)cfg.max_ch) * cfg.width); }
  int rep(int n) const { return std::max(1, (int)std::lround(n * cfg.depth)); }

  std::string fi(const std::string& name, const std::vector<int64_t>& dims, std::vector<float> d) {
    g.init_f.push_back({name, dims, std::move(d)});
    return name;
  }
  std::string ii(const std::string& name, const std::vector<int64_t>& dims, std::vector<int64_t> d) {
    g.init_i.push_back({name, dims, std::move(d)});
    return name;
  }
  void node(const std::string& op, const std::vector<std::string>& in,
            const std::vector<std::string>& out, const std::vector<onx::Attr>& attr = {}) {
    onx::Node n;
    n.op_type = op;
    n.name = out.empty() ? op : out[0];
    n.input = in;
    n.output = out;
    n.attr = attr;
    g.nodes.push_back(std::move(n));
  }
  std::vector<float> uniform(int64_t n, float bound) {
    std::vector<float> v((size_t)n);
    for (int64_t i = 0; i < n; ++i) v[(size_t)i] = (float)rng.range(-bound, bound);
    return v;
  }

  // Conv2d(bias=False) -> BatchNormalization(eps 1e-3) -> SiLU (Sigmoid + Mul), i.e. one
  // ultralytics `Conv` module. `pre` is the module path, e.g. "model.2.cv1".
  std::string conv_bn_silu(const std::string& x, int cin, int cout, int k, int s,
                           const std::string& pre) {
    const int pad = k / 2;
    const float bound = 1.f / std::sqrt((float)(cin * k * k));
    const std::string cw = fi(pre + ".conv.weight", {cout, cin, k, k}, uniform((int64_t)cout * cin * k * k, bound));
    const std::string yc = "/" + pre + "/conv/Conv_output_0";
    node("Conv", {x, cw}, {yc},
         {{"kernel_shape", onx::A_INTS, 0, 0, "", {k, k}, {}},
          {"strides", onx::A_INTS, 0, 0, "", {s, s}, {}},
          {"pads", onx::A_INTS, 0, 0, "", {pad, pad, pad, pad}, {}},
          {"group", onx::A_INT, 1, 0, "", {}, {}}});
    const std::string yb = "/" + pre + "/bn/BatchNormalization_output_0";
    node("BatchNormalization",
         {yc,
          fi(pre + ".bn.weight", {cout}, std::vector<float>((size_t)cout, 1.f)),
          fi(pre + ".bn.bias", {cout}, std::vector<float>((size_t)cout, 0.f)),
          fi(pre + ".bn.running_mean", {cout}, std::vector<float>((size_t)cout, 0.f)),
          fi(pre + ".bn.running_var", {cout}, std::vector<float>((size_t)cout, 1.f))},
         {yb}, {{"epsilon", onx::A_FLOAT, 0, 1e-3f, "", {}, {}}});
    const std::string ys = "/" + pre + "/act/Sigmoid_output_0";
    node("Sigmoid", {yb}, {ys});
    const std::string ym = "/" + pre + "/act/Mul_output_0";
    node("Mul", {yb, ys}, {ym});
    return ym;
  }

  // A bare Conv2d with bias — the last layer of each Detect branch (no BN, no activation).
  std::string conv_plain(const std::string& x, int cin, int cout, int k, const std::string& pre,
                         const std::vector<float>& bias) {
    const int pad = k / 2;
    const float bound = 1.f / std::sqrt((float)(cin * k * k));
    const std::string y = "/" + pre + "/Conv_output_0";
    node("Conv",
         {x, fi(pre + ".weight", {cout, cin, k, k}, uniform((int64_t)cout * cin * k * k, bound)),
          fi(pre + ".bias", {cout}, bias)},
         {y},
         {{"kernel_shape", onx::A_INTS, 0, 0, "", {k, k}, {}},
          {"strides", onx::A_INTS, 0, 0, "", {1, 1}, {}},
          {"pads", onx::A_INTS, 0, 0, "", {pad, pad, pad, pad}, {}},
          {"group", onx::A_INT, 1, 0, "", {}, {}}});
    return y;
  }

  std::string bottleneck(const std::string& x, int c, bool shortcut, const std::string& pre) {
    std::string h = conv_bn_silu(x, c, c, 3, 1, pre + ".cv1");
    h = conv_bn_silu(h, c, c, 3, 1, pre + ".cv2");
    if (!shortcut) return h;
    const std::string y = "/" + pre + "/Add_output_0";
    node("Add", {x, h}, {y});
    return y;
  }

  // C2f: cv1 splits into two halves, every bottleneck's output is kept, cv2 mixes them all.
  std::string c2f(const std::string& x, int cin, int cout, int n, bool shortcut,
                  const std::string& pre) {
    const int c = cout / 2;
    const std::string y1 = conv_bn_silu(x, cin, 2 * c, 1, 1, pre + ".cv1");
    const std::string a = "/" + pre + "/Split_output_0", b = "/" + pre + "/Split_output_1";
    node("Split", {y1, ii("/" + pre + "/Split_sizes", {2}, {c, c})}, {a, b},
         {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
    std::vector<std::string> outs{a, b};
    std::string last = b;
    for (int i = 0; i < n; ++i) {
      last = bottleneck(last, c, shortcut, pre + ".m." + std::to_string(i));
      outs.push_back(last);
    }
    const std::string cat = "/" + pre + "/Concat_output_0";
    node("Concat", outs, {cat}, {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
    return conv_bn_silu(cat, (2 + n) * c, cout, 1, 1, pre + ".cv2");
  }

  std::string sppf(const std::string& x, int cin, int cout, int k, const std::string& pre) {
    const int c = cin / 2;
    const std::string y = conv_bn_silu(x, cin, c, 1, 1, pre + ".cv1");
    std::vector<std::string> outs{y};
    std::string last = y;
    for (int i = 0; i < 3; ++i) {
      const std::string p = "/" + pre + "/m" + (i ? "_" + std::to_string(i) : "") + "/MaxPool_output_0";
      node("MaxPool", {last}, {p},
           {{"kernel_shape", onx::A_INTS, 0, 0, "", {k, k}, {}},
            {"strides", onx::A_INTS, 0, 0, "", {1, 1}, {}},
            {"pads", onx::A_INTS, 0, 0, "", {k / 2, k / 2, k / 2, k / 2}, {}}});
      outs.push_back(p);
      last = p;
    }
    const std::string cat = "/" + pre + "/Concat_output_0";
    node("Concat", outs, {cat}, {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
    return conv_bn_silu(cat, c * 4, cout, 1, 1, pre + ".cv2");
  }

  std::string upsample(const std::string& x, const std::string& pre) {
    const std::string sc = "/" + pre + "/scales";
    if (g.init_f.empty() || true) fi(sc, {4}, {1.f, 1.f, 2.f, 2.f});
    const std::string y = "/" + pre + "/Resize_output_0";
    // nearest + asymmetric: with scales exactly 2 this is the plain pixel-doubling the C++ runner
    // does; the default half_pixel would shift the sampling and quietly misalign the neck.
    node("Resize", {x, "", sc}, {y},
         {{"mode", onx::A_STRING, 0, 0, "nearest", {}, {}},
          {"nearest_mode", onx::A_STRING, 0, 0, "floor", {}, {}},
          {"coordinate_transformation_mode", onx::A_STRING, 0, 0, "asymmetric", {}, {}}});
    return y;
  }

  std::string concat(const std::vector<std::string>& xs, const std::string& pre) {
    const std::string y = "/" + pre + "/Concat_output_0";
    node("Concat", xs, {y}, {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
    return y;
  }
};

// The whole graph: yolov8n by default, any (nc, imgsz) — the anchor grid and stride vector are baked
// in for that size, exactly as an Ultralytics export bakes them in.
inline onx::Graph build(const Cfg& cfg, uint64_t seed = 1234) {
  Builder B(cfg, seed);
  B.g.opset = 13;
  B.g.inputs.push_back({"images", {1, 3, cfg.imgsz, cfg.imgsz}});

  const int c1 = B.ch(64), c2 = B.ch(128), c3 = B.ch(256), c4 = B.ch(512), c5 = B.ch(1024);
  const int n1 = B.rep(3), n2 = B.rep(6);

  std::string x = B.conv_bn_silu("images", 3, c1, 3, 2, "model.0");
  x = B.conv_bn_silu(x, c1, c2, 3, 2, "model.1");
  x = B.c2f(x, c2, c2, n1, true, "model.2");
  x = B.conv_bn_silu(x, c2, c3, 3, 2, "model.3");
  const std::string p3 = B.c2f(x, c3, c3, n2, true, "model.4");        // 1/8
  x = B.conv_bn_silu(p3, c3, c4, 3, 2, "model.5");
  const std::string p4 = B.c2f(x, c4, c4, n2, true, "model.6");        // 1/16
  x = B.conv_bn_silu(p4, c4, c5, 3, 2, "model.7");
  x = B.c2f(x, c5, c5, n1, true, "model.8");
  const std::string p5 = B.sppf(x, c5, c5, 5, "model.9");              // 1/32

  std::string u = B.upsample(p5, "model.10");
  u = B.concat({u, p4}, "model.11");
  const std::string h4 = B.c2f(u, c5 + c4, c4, n1, false, "model.12");
  u = B.upsample(h4, "model.13");
  u = B.concat({u, p3}, "model.14");
  const std::string o3 = B.c2f(u, c4 + c3, c3, n1, false, "model.15");   // P3 out
  std::string d = B.conv_bn_silu(o3, c3, c3, 3, 2, "model.16");
  d = B.concat({d, h4}, "model.17");
  const std::string o4 = B.c2f(d, c3 + c4, c4, n1, false, "model.18");   // P4 out
  d = B.conv_bn_silu(o4, c4, c4, 3, 2, "model.19");
  d = B.concat({d, p5}, "model.20");
  const std::string o5 = B.c2f(d, c4 + c5, c5, n1, false, "model.21");   // P5 out

  // ---- Detect ----
  const int nc = cfg.nc, reg = cfg.reg_max;
  const int hc2 = std::max(16, std::max(c3 / 4, reg * 4));      // box branch width
  const int hc3 = std::max(c3, std::min(nc, 100));              // class branch width
  const std::string in[3] = {o3, o4, o5};
  const int inch[3] = {c3, c4, c5};
  const int strides[3] = {8, 16, 32};
  std::vector<std::string> box_out, cls_out;
  for (int l = 0; l < 3; ++l) {
    const std::string bp = "model.22.cv2." + std::to_string(l);
    std::string b = B.conv_bn_silu(in[l], inch[l], hc2, 3, 1, bp + ".0");
    b = B.conv_bn_silu(b, hc2, hc2, 3, 1, bp + ".1");
    // Detect.bias_init: box branch starts at 1.0 ...
    box_out.push_back(B.conv_plain(b, hc2, 4 * reg, 1, bp + ".2", std::vector<float>((size_t)(4 * reg), 1.f)));

    const std::string cp = "model.22.cv3." + std::to_string(l);
    std::string c = B.conv_bn_silu(in[l], inch[l], hc3, 3, 1, cp + ".0");
    c = B.conv_bn_silu(c, hc3, hc3, 3, 1, cp + ".1");
    // ... and the class branch starts at log(5 / nc / (640/stride)^2): "expect almost nothing".
    const float cb = (float)std::log(5.0 / nc / std::pow(640.0 / strides[l], 2.0));
    cls_out.push_back(B.conv_plain(c, hc3, nc, 1, cp + ".2", std::vector<float>((size_t)nc, cb)));
  }

  // ---- decode tail (node for node as an Ultralytics export writes it) ----
  int64_t A = 0;
  std::vector<int64_t> hw(3);
  for (int l = 0; l < 3; ++l) { hw[(size_t)l] = cfg.imgsz / strides[l]; A += hw[(size_t)l] * hw[(size_t)l]; }
  std::vector<std::string> rb, rc;
  for (int l = 0; l < 3; ++l) {
    const std::string yb = "/model.22/Reshape_" + std::to_string(l) + "_output_0";
    B.node("Reshape", {box_out[(size_t)l], B.ii("/model.22/rb" + std::to_string(l), {3}, {1, 4 * reg, -1})}, {yb});
    rb.push_back(yb);
    const std::string yc = "/model.22/Reshape_" + std::to_string(3 + l) + "_output_0";
    B.node("Reshape", {cls_out[(size_t)l], B.ii("/model.22/rc" + std::to_string(l), {3}, {1, nc, -1})}, {yc});
    rc.push_back(yc);
  }
  B.node("Concat", rb, {"/model.22/Concat_output_0"}, {{"axis", onx::A_INT, 2, 0, "", {}, {}}});
  B.node("Concat", rc, {"/model.22/Concat_1_output_0"}, {{"axis", onx::A_INT, 2, 0, "", {}, {}}});
  B.node("Sigmoid", {"/model.22/Concat_1_output_0"}, {"/model.22/Sigmoid_output_0"});

  B.node("Reshape", {"/model.22/Concat_output_0", B.ii("/model.22/dfl/shape", {4}, {1, 4, reg, A})},
         {"/model.22/dfl/Reshape_output_0"});
  B.node("Transpose", {"/model.22/dfl/Reshape_output_0"}, {"/model.22/dfl/Transpose_output_0"},
         {{"perm", onx::A_INTS, 0, 0, "", {0, 2, 1, 3}, {}}});
  B.node("Softmax", {"/model.22/dfl/Transpose_output_0"}, {"/model.22/dfl/Softmax_output_0"},
         {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
  {
    std::vector<float> proj((size_t)reg);
    for (int i = 0; i < reg; ++i) proj[(size_t)i] = (float)i;      // the DFL projection: 0..reg-1
    B.node("Conv", {"/model.22/dfl/Softmax_output_0", B.fi("model.22.dfl.conv.weight", {1, reg, 1, 1}, proj)},
           {"/model.22/dfl/conv/Conv_output_0"},
           {{"kernel_shape", onx::A_INTS, 0, 0, "", {1, 1}, {}},
            {"strides", onx::A_INTS, 0, 0, "", {1, 1}, {}},
            {"pads", onx::A_INTS, 0, 0, "", {0, 0, 0, 0}, {}},
            {"group", onx::A_INT, 1, 0, "", {}, {}}});
  }
  B.node("Reshape", {"/model.22/dfl/conv/Conv_output_0", B.ii("/model.22/dfl/shape1", {3}, {1, 4, A})},
         {"/model.22/dfl/Reshape_1_output_0"});
  B.node("Slice",
         {"/model.22/dfl/Reshape_1_output_0", B.ii("/model.22/s0", {1}, {0}), B.ii("/model.22/s2", {1}, {2}),
          B.ii("/model.22/ax1", {1}, {1})},
         {"/model.22/Slice_output_0"});
  B.node("Slice",
         {"/model.22/dfl/Reshape_1_output_0", "/model.22/s2", B.ii("/model.22/s4", {1}, {4}), "/model.22/ax1"},
         {"/model.22/Slice_1_output_0"});

  std::vector<float> anchors((size_t)(2 * A));
  std::vector<float> strv((size_t)A);
  {
    int64_t k = 0;
    for (int l = 0; l < 3; ++l)
      for (int64_t y = 0; y < hw[(size_t)l]; ++y)
        for (int64_t xg = 0; xg < hw[(size_t)l]; ++xg) {
          anchors[(size_t)k] = (float)xg + 0.5f;                  // row 0: x of every anchor
          anchors[(size_t)(A + k)] = (float)y + 0.5f;             // row 1: y
          strv[(size_t)k] = (float)strides[l];
          ++k;
        }
  }
  const std::string anc = B.fi("/model.22/anchors", {1, 2, A}, anchors);
  B.node("Sub", {anc, "/model.22/Slice_output_0"}, {"/model.22/Sub_output_0"});          // x1y1
  B.node("Add", {anc, "/model.22/Slice_1_output_0"}, {"/model.22/Add_1_output_0"});      // x2y2
  B.node("Add", {"/model.22/Sub_output_0", "/model.22/Add_1_output_0"}, {"/model.22/Add_2_output_0"});
  B.node("Sub", {"/model.22/Add_1_output_0", "/model.22/Sub_output_0"}, {"/model.22/Sub_1_output_0"});
  B.node("Div", {"/model.22/Add_2_output_0", B.fi("/model.22/two", {1}, {2.f})}, {"/model.22/Div_1_output_0"});
  B.node("Concat", {"/model.22/Div_1_output_0", "/model.22/Sub_1_output_0"}, {"/model.22/Concat_2_output_0"},
         {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
  B.node("Mul", {"/model.22/Concat_2_output_0", B.fi("/model.22/strides", {1, A}, strv)},
         {"/model.22/Mul_2_output_0"});
  B.node("Concat", {"/model.22/Mul_2_output_0", "/model.22/Sigmoid_output_0"}, {"output0"},
         {{"axis", onx::A_INT, 1, 0, "", {}, {}}});
  B.g.outputs.push_back({"output0", {1, 4 + nc, A}});
  return B.g;
}

// Fold every BatchNormalization into the convolution before it, the way Ultralytics fuses before
// exporting: w' = w * gamma/sqrt(var+eps), b' = beta - mean*gamma/sqrt(var+eps). Training needs BN as
// its own node; inference does not, and the fused graph is what the CLI and the WASM demo run.
inline onx::Graph fuse_bn(const onx::Graph& in, int* fused = nullptr) {
  onx::Graph out = in;
  std::map<std::string, size_t> fidx;                       // initializer name -> index
  for (size_t i = 0; i < out.init_f.size(); ++i) fidx[out.init_f[i].name] = i;
  std::map<std::string, size_t> producer;                   // tensor name -> node index
  for (size_t i = 0; i < out.nodes.size(); ++i)
    for (const std::string& o : out.nodes[i].output) producer[o] = i;

  int n_fused = 0;
  std::vector<char> drop(out.nodes.size(), 0);
  std::map<std::string, std::string> rename;                // BN output -> conv output
  for (size_t i = 0; i < out.nodes.size(); ++i) {
    onx::Node& bn = out.nodes[i];
    if (bn.op_type != "BatchNormalization" || bn.input.size() < 5) continue;
    auto pit = producer.find(bn.input[0]);
    if (pit == producer.end()) continue;
    onx::Node& cv = out.nodes[pit->second];
    if (cv.op_type != "Conv" || cv.input.size() < 2) continue;
    if (!fidx.count(cv.input[1]) || !fidx.count(bn.input[1]) || !fidx.count(bn.input[2]) ||
        !fidx.count(bn.input[3]) || !fidx.count(bn.input[4])) continue;
    onx::Tensor64& W = out.init_f[fidx[cv.input[1]]];
    const std::vector<float>& gamma = out.init_f[fidx[bn.input[1]]].data;
    const std::vector<float>& beta = out.init_f[fidx[bn.input[2]]].data;
    const std::vector<float>& mean = out.init_f[fidx[bn.input[3]]].data;
    const std::vector<float>& var = out.init_f[fidx[bn.input[4]]].data;
    float eps = 1e-5f;
    for (const onx::Attr& a : bn.attr) if (a.name == "epsilon") eps = a.f;
    const int64_t Co = W.dims[0], per = (int64_t)W.data.size() / std::max<int64_t>(1, Co);
    std::vector<float> bias((size_t)Co, 0.f);
    if (cv.input.size() >= 3 && fidx.count(cv.input[2])) bias = out.init_f[fidx[cv.input[2]]].data;
    for (int64_t c = 0; c < Co; ++c) {
      const float s = gamma[(size_t)c] / std::sqrt(var[(size_t)c] + eps);
      for (int64_t k = 0; k < per; ++k) W.data[(size_t)(c * per + k)] *= s;
      bias[(size_t)c] = (bias[(size_t)c] - mean[(size_t)c]) * s + beta[(size_t)c];
    }
    const std::string bname = cv.input.size() >= 3 && !cv.input[2].empty() ? cv.input[2]
                                                                          : cv.input[1] + "_fusedbias";
    if (!fidx.count(bname)) {
      out.init_f.push_back({bname, {Co}, bias});
      fidx[bname] = out.init_f.size() - 1;
    } else {
      out.init_f[fidx[bname]].data = bias;
    }
    if (cv.input.size() >= 3) cv.input[2] = bname; else cv.input.push_back(bname);
    rename[bn.output[0]] = cv.output[0];
    drop[i] = 1;
    ++n_fused;
  }
  // drop the BN nodes and point their consumers at the convolution's output
  std::vector<onx::Node> kept;
  for (size_t i = 0; i < out.nodes.size(); ++i) {
    if (drop[i]) continue;
    onx::Node n = out.nodes[i];
    for (std::string& in_name : n.input) {
      auto it = rename.find(in_name);
      while (it != rename.end()) { in_name = it->second; it = rename.find(in_name); }
    }
    kept.push_back(std::move(n));
  }
  out.nodes.swap(kept);
  // and drop the BN parameters, which nothing reads any more
  std::set<std::string> used;
  for (const onx::Node& n : out.nodes) for (const std::string& s : n.input) used.insert(s);
  std::vector<onx::Tensor64> keep_f;
  for (const onx::Tensor64& t : out.init_f) if (used.count(t.name)) keep_f.push_back(t);
  out.init_f.swap(keep_f);
  if (fused) *fused = n_fused;
  return out;
}

}  // namespace v8b
