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
      // **入れ子の箱も落とす。** 同じ字に大小 2 つの箱が出ることがあり、IoU では残る
      // （実測: `)` に (166,8)-(186,72) と (172,32)-(186,71) の 2 つが出て IoU 0.43。
      // 小さいほうが完全に中にあるのに残り、「解釈できない記号: )」で解析が落ちた）。
      const float amin = std::min((d.x2 - d.x1) * (d.y2 - d.y1),
                                 (k.x2 - k.x1) * (k.y2 - k.y1));
      if (ua > 0 && inter / ua > 0.5f) { dup = true; break; }
      if (amin > 0 && inter / amin > 0.8f) { dup = true; break; }
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
//
// **数える下限は「最も濃い行の何割か」で決める**（固定の px 数では駄目だった）。実測:
// 教科書 1 ページ（2016x1512）は隣のページの写り込みと 2 段組みのせいで、どの行にも
// 少しインクがある。下限 w/200 = 10 では**全体が 1 帯（y 0..1287）**になった。
// 最大値の 12% にすると 9 帯に分かれ、1 問ずつの欄（1200x460）では 0.5%〜20% の
// どれでも 4 行に切れた（つまりこの割合は効き方が鈍く、安全側）。
inline std::vector<std::pair<int, int>> ink_bands(const unsigned char* rgb, int w, int h,
                                                 int pad_px = 0, int pct_of_max = 12,
                                                 int merge_pct = 25) {
  std::vector<unsigned char> gray((size_t)w * h);
  for (size_t i = 0; i < gray.size(); ++i)
    gray[i] = (unsigned char)((rgb[i * 3] * 30 + rgb[i * 3 + 1] * 59 + rgb[i * 3 + 2] * 11) / 100);
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
  int mx = 0;
  for (int y = 0; y < h; ++y) mx = std::max(mx, ink[(size_t)y]);
  const int min_ink = std::max(std::max(3, w / 200), mx * pct_of_max / 100);
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
    if (bands[i].first - merged.back().second <= std::max(2, med * merge_pct / 100))
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

// 帯の中を**縦の射影**で塊に切る（x0,x1 の組）。行と同じ考え方を横方向にやるだけ。
//
// **ここでモデルを使わない**のが要点。粗く検出してから切ろうとすると、教科書 1 ページ
// （幅 2016）では帯がそのまま 640 に縮んで字が小さくなり、粗い段で何も出ない（実測: ページ
// まるごとで 98 記号しか出ず、しかも化けていた）。射影なら検出器の出来に依らない。
// 隙間の下限は**帯の高さ**を尺度にする（字の間の隙間と、問題どうしの隙間は桁が違う）。
// 実測（教科書 1 ページを丸ごと渡して正解表と突き合わせ、tools/page_eval.py）:
// 帯の高さの 90% -> 2/12、60% -> 2/12、40% -> 3/12。問題番号「(1)」と式の間隔が
// 字の高さの半分ほどしかないので、大きく取ると番号と式がくっつく。
inline std::vector<std::pair<int, int>> ink_cols(const unsigned char* rgb, int w, int h, int y0,
                                                int y1, double gap_factor = 0.35) {
  std::vector<std::pair<int, int>> out;
  const int bh = y1 - y0;
  if (bh <= 0 || w <= 0) return out;
  // 帯の紙の明るさ（帯全体の中央値）。行ごとに取る ink_bands と違い、帯の中は明るさが揃う
  std::vector<int> all;
  all.reserve((size_t)w * bh / 4 + 1);
  for (int y = y0; y < y1; y += 2)
    for (int x = 0; x < w; x += 2) {
      const size_t i = ((size_t)y * w + x) * 3;
      all.push_back((rgb[i] * 30 + rgb[i + 1] * 59 + rgb[i + 2] * 11) / 100);
    }
  if (all.empty()) return out;
  std::nth_element(all.begin(), all.begin() + all.size() / 2, all.end());
  const int paper = all[all.size() / 2];
  std::vector<int> ink((size_t)w, 0);
  for (int x = 0; x < w; ++x) {
    int c = 0;
    for (int y = y0; y < y1; ++y) {
      const size_t i = ((size_t)y * w + x) * 3;
      const int g = (rgb[i] * 30 + rgb[i + 1] * 59 + rgb[i + 2] * 11) / 100;
      if (g < paper - 30) ++c;
    }
    ink[(size_t)x] = c;
  }
  const int min_ink = std::max(1, bh / 20);
  std::vector<std::pair<int, int>> runs;
  int x = 0;
  while (x < w) {
    while (x < w && ink[(size_t)x] <= min_ink) ++x;
    if (x >= w) break;
    const int s = x;
    while (x < w && ink[(size_t)x] > min_ink) ++x;
    runs.push_back({s, x});
  }
  if (runs.empty()) return out;
  // **切る隙間は分布で決める。** 固定値だと両立しない: 大きく取ると問題番号「(1)」が式に
  // くっつき（実測: 帯の高さの 90% で 2/12）、小さく取ると 1 つの式が割れる（40% にしたら
  // `x^2 - 5x + 6 = 0` が `x^2 - 5x` と `+ 6 = 0` に割れて、ブラウザの検査が落ちた）。
  // 字の間の隙間（中央値）を基準に、その 2.5 倍より広い隙間だけを切れ目とする。
  std::vector<int> gaps;
  for (size_t i = 1; i < runs.size(); ++i) gaps.push_back(runs[i].first - runs[i - 1].second);
  int med_gap = 0;
  if (!gaps.empty()) {
    std::vector<int> g2 = gaps;
    std::sort(g2.begin(), g2.end());
    med_gap = g2[g2.size() / 2];
  }
  const int gap = std::max(std::max(4, (int)(bh * gap_factor)), med_gap * 5 / 2);
  out.push_back(runs[0]);
  for (size_t i = 1; i < runs.size(); ++i) {
    if (runs[i].first - out.back().second <= gap) out.back().second = runs[i].second;
    else out.push_back(runs[i]);
  }
  return out;
}

// 塊（1 式ぶん）とその中の記号。detect_by_cells が返す。
struct Cell {
  int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
  std::vector<pl::Sym> syms;
};

// **射影で塊に切ってから、塊ごとに 1 回だけ検出する。**
//
// 行に切るだけでは足りない（実測: 教科書の 1200x460 の欄を 4 行に切っても、1 行が
// 1200x60 なので 640 に縮む段で 0.53 倍になり、31 記号のうち半分が化けた）。**当たるのは
// 1 式ぶんを囲んだとき**（280x90 なら 640 に 2 倍以上に拡大される。実測 12/12）。
// そこで行（横の射影）と塊（縦の射影）の両方を**モデルを使わずに**切り出し、塊ごとに
// 元画像から読む。検出は塊の数だけ走る（ページ 1 枚で 20 回ほど）。
// 塊 1 つを読み終えるたびに呼ばれる（ブラウザで進捗を出すため。ページ 1 枚で 30 秒級なので、
// 何も出ないと壊れて見える）。CLI は渡さない。
using CellProgress = void (*)(int done, int total, void* user);

inline std::vector<Cell> detect_by_cells(const onx::Graph& g, const unsigned char* rgb, int w,
                                        int h, int imgsz, float conf, float nms, BoxFmt fmt,
                                        int gap_pct = 35,    // 隙間の下限（残りは分布で決める）
                                        int merge_pct = 25,
                                        CellProgress on_cell = nullptr, void* user = nullptr) {
  std::vector<Cell> out;
  const std::vector<std::pair<int, int>> bands = ink_bands(rgb, w, h, 4, 12, merge_pct);
  // 先に塊の総数を数える（進捗の分母。射影だけなので安い）
  int total = 0, done = 0;
  for (const std::pair<int, int>& b0 : bands)
    total += (int)ink_cols(rgb, w, h, b0.first, b0.second, gap_pct / 100.0).size();
  for (const std::pair<int, int>& b : bands) {
    const int bh = b.second - b.first;
    if (bh <= 0) continue;
    for (const std::pair<int, int>& c :
         ink_cols(rgb, w, h, b.first, b.second, gap_pct / 100.0)) {
      // 余白を帯の高さの 1/4 取る（上付きや括弧が帯の外に出ていることがある）
      const int pad = std::max(4, bh / 4);
      const int cx0 = std::max(0, c.first - pad), cy0 = std::max(0, b.first - pad);
      const int cx1 = std::min(w, c.second + pad), cy1 = std::min(h, b.second + pad);
      const int cw = cx1 - cx0, chh = cy1 - cy0;
      if (cw < 8 || chh < 8) continue;
      std::vector<unsigned char> cell((size_t)cw * chh * 3);
      for (int y = 0; y < chh; ++y)
        std::memcpy(&cell[(size_t)y * cw * 3], rgb + ((size_t)(y + cy0) * w + cx0) * 3,
                    (size_t)cw * 3);
      Detected d = detect_syms(g, cell.data(), cw, chh, imgsz, conf, nms, fmt);
      if (on_cell) on_cell(++done, total, user);
      if (d.syms.empty()) continue;
      Cell res;
      res.x0 = cx0; res.y0 = cy0; res.x1 = cx1; res.y1 = cy1;
      for (pl::Sym& s : d.syms) {
        s.x0 += cx0; s.x1 += cx0;
        s.y0 += cy0; s.y1 += cy0; s.base_y += cy0;
        res.syms.push_back(s);
      }
      out.push_back(res);
    }
    // **演算子で切れた塊はつなぐ。** 教科書は演算子の左右を広く空けるので、`3x^2 + x - 10 = 0`
    // が `3x^2 + x` と `- 10 = 0` の 2 つに割れた（実測: ページ渡しでこの型の取りこぼしが多い）。
    // 隙間が帯の高さの 1.5 倍以内で、片方の端が二項演算子なら 1 つにする（再検出は要らない）。
    const auto binop = [](const std::string& c) {
      return c == "+" || c == "-" || c == "=" || c == "times" || c == "div";
    };
    while (out.size() >= 2) {
      bool merged = false;
      for (size_t i = out.size() - 1; i >= 1; --i) {
        Cell& L = out[i - 1];
        Cell& R = out[i];
        if (R.y0 != L.y0 || R.y1 != L.y1) continue;          // 同じ帯だけ
        if (R.x0 - L.x1 > (int)(bh * 3 / 2)) continue;
        std::vector<pl::Sym> ls = L.syms, rs = R.syms;
        std::sort(ls.begin(), ls.end(), pl::by_x);
        std::sort(rs.begin(), rs.end(), pl::by_x);
        if (ls.empty() || rs.empty()) continue;
        if (!binop(rs.front().cls) && !binop(ls.back().cls)) continue;
        for (const pl::Sym& sm : R.syms) L.syms.push_back(sm);
        L.x1 = std::max(L.x1, R.x1);
        L.y0 = std::min(L.y0, R.y0);
        L.y1 = std::max(L.y1, R.y1);
        out.erase(out.begin() + (long)i);
        merged = true;
        break;
      }
      if (!merged) break;
    }
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
