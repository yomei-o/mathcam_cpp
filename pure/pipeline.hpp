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
#include <cstring>
#include <vector>

// 名前は pipeln。**pipe にすると Linux で壊れる**（POSIX の pipe() が
// グローバルにあるので "pipe does not name a type" になる。MSVC では通るので気付かない）
namespace pipeln {

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
    sm.score = d.score;
    if (sm.x1 <= sm.x0 || sm.y1 <= sm.y0) continue;
    out.syms.push_back(sm);
  }
  out.ok = true;
  return out;
}


// ---------------------------------------------------------------- 行に切ってから検出する
//
// 実写のページを広く囲むと、640 に縮む段で字が小さくなって検出できない
// （実測: 4 問ぶん 1140x350 を囲むと 0.56 倍になり、7 記号しか出なかった）。
// **先にインクの横方向の射影で行に切り、行ごとに検出する**（各行が 640 に拡大されるので、
// 字の大きさが学習時に近くなる）。行の切り出しはモデルを使わないので、検出器の出来に依らない。

// インクのある行の帯を返す（y0,y1 の組）。padding は帯の上下に足す余白（px）。
//
// **閾値は行ごとに取る**（その行の中央値より暗い画素を数える）。1 枚に 1 つの閾値
// （Otsu）にすると、光沢や影で明るさが場所ごとに違う写真では、暗い側の背景が全部
// 「インク」になって行が分けられない（実測: 教科書のページで帯が 1 つになった）。
inline std::vector<std::pair<int, int>> ink_bands(const unsigned char* rgb, int w, int h,
                                                 int pad_px = 0) {
  std::vector<unsigned char> gray((size_t)w * h);
  for (size_t i = 0; i < gray.size(); ++i)
    gray[i] = (unsigned char)((rgb[i * 3] * 30 + rgb[i * 3 + 1] * 59 + rgb[i * 3 + 2] * 11) / 100);
  const int min_ink = std::max(3, w / 200);        // 幅に対する下限（ノイズを弾く）
  std::vector<int> ink((size_t)h, 0);
  std::vector<int> row(  (size_t)w, 0);
  for (int y = 0; y < h; ++y) {
    for (int x = 0; x < w; ++x) row[(size_t)x] = gray[(size_t)y * w + x];
    std::vector<int> tmp = row;
    std::nth_element(tmp.begin(), tmp.begin() + w / 2, tmp.end());
    const int paper = tmp[(size_t)(w / 2)];        // その行の「紙の明るさ」
    int c = 0;
    for (int x = 0; x < w; ++x)
      if (row[(size_t)x] < paper - 30) ++c;
    ink[(size_t)y] = c;
  }
  std::vector<std::pair<int, int>> bands;
  int y = 0;
  while (y < h) {
    while (y < h && ink[(size_t)y] <= min_ink) ++y;
    if (y >= h) break;
    const int s = y;
    while (y < h && ink[(size_t)y] > min_ink) ++y;
    bands.push_back({s, y});
  }
  if (bands.empty()) return bands;
  // 近い帯はつなぐ。**つなぐ条件は「帯の高さの 1/4 より近い」**。半分にすると、
  // 教科書の行間（字の高さ 45px に対して行の隙間 40px）でも全部つながって 1 行になった。
  std::vector<int> hs;
  for (const std::pair<int, int>& b : bands) hs.push_back(b.second - b.first);
  std::sort(hs.begin(), hs.end());
  const int med = std::max(1, hs[hs.size() / 2]);
  std::vector<std::pair<int, int>> merged{bands[0]};
  for (size_t i = 1; i < bands.size(); ++i) {
    if (bands[i].first - merged.back().second <= std::max(2, med / 4))
      merged.back().second = bands[i].second;
    else merged.push_back(bands[i]);
  }
  // 高さが極端に小さい帯（罫線やノイズ）は捨てる
  std::vector<std::pair<int, int>> out;
  for (const std::pair<int, int>& b : merged) {
    if (b.second - b.first < std::max(6, med / 3)) continue;
    out.push_back({std::max(0, b.first - pad_px), std::min(h, b.second + pad_px)});
  }
  return out;
}

// 行ごとに検出して、元の座標に戻した記号を行ごとに返す。
// out_bands を渡すと、返した行に対応する帯（y0,y1）も同じ順で入れる。**記号が 1 つも出なかった
// 帯は返さない**ので、帯の一覧を別に取ると行と番号が合わなくなる（ブラウザの重ね描きで踏んだ）。
inline std::vector<std::vector<pl::Sym>> detect_by_lines(const onx::Graph& g,
                                                        const unsigned char* rgb, int w, int h,
                                                        int imgsz, float conf, float nms,
                                                        BoxFmt fmt,
                                                        std::vector<std::pair<int, int>>* out_bands
                                                            = nullptr) {
  std::vector<std::vector<pl::Sym>> out;
  const std::vector<std::pair<int, int>> bands = ink_bands(rgb, w, h, 4);
  for (const std::pair<int, int>& b : bands) {
    const int bh = b.second - b.first;
    if (bh <= 0) continue;
    std::vector<unsigned char> sub((size_t)w * bh * 3);
    for (int y = 0; y < bh; ++y)
      std::memcpy(&sub[(size_t)y * w * 3], rgb + ((size_t)(y + b.first) * w) * 3,
                  (size_t)w * 3);
    Detected d = detect_syms(g, sub.data(), w, bh, imgsz, conf, nms, fmt);
    for (pl::Sym& s : d.syms) {
      s.y0 += b.first;
      s.y1 += b.first;
      s.base_y += b.first;
    }
    if (!d.syms.empty()) {
      out.push_back(d.syms);
      if (out_bands) out_bands->push_back(b);
    }
  }
  return out;
}

}  // namespace pipeln
