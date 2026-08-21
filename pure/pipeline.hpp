// 写真 1 枚を式にするまでの道。**CLI（photo / e2e）と WASM がこの 1 本を共有する。**
// 別の道でテストすると、その差分だけ検証が消える（姉妹リポにも同じ注意がある）。
//
// ここでやること: letterbox -> 自作ランタイムで forward -> v8 のデコード -> クラスを無視した
// 重複除去 -> 元画像の座標に戻す。式木にするのは parse_layout、解くのは solve。
#pragma once
#include "classes.hpp"
#include "infer_v8.hpp"
#include "onnx_run.hpp"
#include "parse_layout.hpp"
#include <algorithm>
#include <cmath>
#include <vector>

namespace pipe {

// 画像 1 枚 -> 記号（検出 -> 元座標に戻す -> クラスを無視した重複除去まで）。
// photo と e2e で同じ道を通すために関数にしてある（別の道でテストすると、その差分だけ
// 検証が消える）。
struct Detected {
  std::vector<pl::Sym> syms;
  bool ok = false;
};

inline Detected detect_syms(const onx::Graph& g, const unsigned char* rgb, int w, int h, int imgsz,
                            float conf, float nms, BoxFmt fmt) {
  Detected out;
  const float sc = std::min((float)imgsz / (float)w, (float)imgsz / (float)h);
  const int nw = (int)(w * sc), nh = (int)(h * sc);
  const int padx = (imgsz - nw) / 2, pady = (imgsz - nh) / 2;
  // **双線形で拡縮する。** 最近傍にしていたら、小さい画像（1 記号だけの式など）が 10 倍に
  // 拡大されたときに字がブロック状になり、学習時（Ultralytics は cv2 の bilinear）と別物に
  // なって読み間違えた（実測: 端から端までの正解率が 72.5% で、失敗が小さい画像に集中）。
  Tensor x = make_tensor({1, 3, imgsz, imgsz}, false);
  for (int y = 0; y < imgsz; ++y)
    for (int xx = 0; xx < imgsz; ++xx) {
      const bool inside = xx >= padx && xx < padx + nw && y >= pady && y < pady + nh;
      if (!inside) {
        for (int c = 0; c < 3; ++c)
          x->data[((size_t)c * imgsz + y) * imgsz + xx] = 114.f / 255.f;
        continue;
      }
      // 画素の中心を合わせる（cv2.resize と同じ規約）
      const float fx = ((float)(xx - padx) + 0.5f) / sc - 0.5f;
      const float fy = ((float)(y - pady) + 0.5f) / sc - 0.5f;
      const int x0 = (int)std::floor(fx), y0 = (int)std::floor(fy);
      const float tx = fx - (float)x0, ty = fy - (float)y0;
      const int x1i = std::min(x0 + 1, w - 1), y1i = std::min(y0 + 1, h - 1);
      const int x0c = std::max(0, std::min(x0, w - 1)), y0c = std::max(0, std::min(y0, h - 1));
      for (int c = 0; c < 3; ++c) {
        const float p00 = rgb[((size_t)y0c * w + x0c) * 3 + c];
        const float p10 = rgb[((size_t)y0c * w + x1i) * 3 + c];
        const float p01 = rgb[((size_t)y1i * w + x0c) * 3 + c];
        const float p11 = rgb[((size_t)y1i * w + x1i) * 3 + c];
        const float top = p00 + (p10 - p00) * tx;
        const float bot = p01 + (p11 - p01) * tx;
        x->data[((size_t)c * imgsz + y) * imgsz + xx] = (top + (bot - top) * ty) / 255.f;
      }
    }
  std::map<std::string, Tensor> vals = onx::run_onnx(g, x, {}, nullptr, false);
  const Tensor& raw = vals.at(g.outputs[0].name);
  const int64_t nc = raw->shape[1] - 4;
  std::vector<Det> dets = v8_detect(raw, nc, conf, nms, fmt);
  std::sort(dets.begin(), dets.end(), [](const Det& a, const Det& b) { return a.score > b.score; });
  std::vector<Det> keep;
  for (const Det& d : dets) {
    bool dup = false;
    for (const Det& k : keep) {
      const float ix0 = std::max(d.x1, k.x1), iy0 = std::max(d.y1, k.y1);
      const float ix1 = std::min(d.x2, k.x2), iy1 = std::min(d.y2, k.y2);
      const float iw = ix1 - ix0, ih = iy1 - iy0;
      if (iw <= 0 || ih <= 0) continue;
      const float inter = iw * ih;
      const float ua = (d.x2 - d.x1) * (d.y2 - d.y1) + (k.x2 - k.x1) * (k.y2 - k.y1) - inter;
      if (ua > 0 && inter / ua > 0.5f) { dup = true; break; }
    }
    if (!dup) keep.push_back(d);
  }
  for (const Det& d : keep) {
    pl::Sym sm;
    sm.cls = cls::name_of(d.cls);
    sm.x0 = (int)((d.x1 - padx) / sc);
    sm.y0 = (int)((d.y1 - pady) / sc);
    sm.x1 = (int)((d.x2 - padx) / sc);
    sm.y1 = (int)((d.y2 - pady) / sc);
    sm.base_y = sm.y1;
    if (sm.x1 <= sm.x0 || sm.y1 <= sm.y0) continue;
    out.syms.push_back(sm);
  }
  out.ok = true;
  return out;
}


}  // namespace pipe
