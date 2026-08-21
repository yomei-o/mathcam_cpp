// 組版の実装のうち、stb_truetype の実体が必要な部分。**.cpp からだけ** include する
// （stb は実装がインクルードガードの外にあるので、ヘッダから include すると二重定義になる。
// 姉妹リポにも同じ注意書きがある）。
#pragma once
#include "stb_truetype.h"
#include "typeset.hpp"
#include <cstdio>
#include <cstring>

namespace ts {

inline int Font::advance(int cp) const {
  int adv = 0, lsb = 0;
  stbtt_GetCodepointHMetrics(info, cp, &adv, &lsb);
  return adv;
}

inline void Font::bbox(int cp, int* x0, int* y0, int* x1, int* y1) const {
  *x0 = *y0 = *x1 = *y1 = 0;
  stbtt_GetCodepointBox(info, cp, x0, y0, x1, y1);
}

// フォントを読む。--font で渡されなければ、よくある場所を順に探す。
// **フォントはリポジトリに入れない**（再配布の可否が font ごとに違う）。学習データを作る側が
// 手元のフォントを指定する。Kaggle（Linux）には DejaVu がある。
inline bool load_font(Font& f, const std::string& path_in, std::string* why = nullptr,
                      bool italic = false) {
  static const char* kRoman[] = {
      "fonts/math.ttf",
      "C:/Windows/Fonts/times.ttf",
      "C:/Windows/Fonts/georgia.ttf",
      "C:/Windows/Fonts/arial.ttf",
      "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
      "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
  };
  // 数式のイタリック体。**教科書の変数はこれで組まれている**。Kaggle（Linux）には
  // matplotlib が Computer Modern（cmmi10）と STIX を同梱しているので、そこも見る
  // （cmmi10 は TeX の数式イタリックそのもので、教科書の字形に最も近い）。
  static const char* kItalic[] = {
      "fonts/math-italic.ttf",
      "C:/Windows/Fonts/timesi.ttf",
      "C:/Windows/Fonts/cambriai.ttf",
      "C:/Windows/Fonts/georgiai.ttf",
      "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
      "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
  };
  std::vector<std::string> tries;
  if (!path_in.empty()) tries.push_back(path_in);
  if (italic) { for (const char* c : kItalic) tries.push_back(c); }
  else { for (const char* c : kRoman) tries.push_back(c); }

  for (const std::string& p : tries) {
    FILE* fp = fopen(p.c_str(), "rb");
    if (!fp) continue;
    fseek(fp, 0, SEEK_END);
    const long n = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    f.data.assign((size_t)n, 0);
    const size_t got = fread(f.data.data(), 1, (size_t)n, fp);
    fclose(fp);
    if (got != (size_t)n) continue;
    f.info = new stbtt_fontinfo();
    const int off = stbtt_GetFontOffsetForIndex(f.data.data(), 0);
    if (!stbtt_InitFont(f.info, f.data.data(), off < 0 ? 0 : off)) { delete f.info; f.info = nullptr; continue; }
    // upem は head テーブルの値。stb は直接返さないので、'M' の縦幅ではなく
    // unitsPerEm を自分で読む（TTF のバイト列から: head テーブルの offset+18）
    f.upem = 0;
    {
      const unsigned char* d = f.data.data();
      const int num = (d[4] << 8) | d[5];
      for (int i = 0; i < num; ++i) {
        const unsigned char* rec = d + 12 + 16 * i;
        if (memcmp(rec, "head", 4) == 0) {
          const unsigned int o = (rec[8] << 24) | (rec[9] << 16) | (rec[10] << 8) | rec[11];
          f.upem = (d[o + 18] << 8) | d[o + 19];
          break;
        }
      }
    }
    if (f.upem <= 0) f.upem = 1000;
    int lg = 0;
    stbtt_GetFontVMetrics(f.info, &f.ascent, &f.descent, &lg);
    return true;
  }
  if (why) *why = "フォントが見つかりません（--font で TTF を渡してください）";
  return false;
}

// 組版して画素に落とす。返る箱は「画素・y は下向き正」で、認識器の正解枠にそのまま使える。
inline Rendered render(const Font& f, const Font* fi, const ex::E& e, int px,
                       const Style& st = Style()) {
  Rendered R;
  const P p = present(e, false, st);
  Layout L = lay(f, fi, p, 1, 1);

  // 実際に置かれたものの範囲を取る（layout の box より、描いた枠の合併のほうが正確）
  int minx = 0, maxx = L.box.w, miny = -L.box.desc, maxy = L.box.asc;
  for (const Item& it : L.items) {
    // bbox は shift() で既に絶対座標になっている。ここで it.x を足すと二重加算になる
    // （実際にそう書いていて、ラベルの枠だけが 2 倍の位置に出ていた。絵は it.x を使う
    //  ラスタ側だけ正しかったので、見た目では気付けなかった）。
    const int bx0 = it.x0, by0 = it.y0, bx1 = it.x1, by1 = it.y1;
    minx = std::min(minx, bx0); maxx = std::max(maxx, bx1);
    miny = std::min(miny, by0); maxy = std::max(maxy, by1);
  }
  const int mg = emk(f, K_MARGIN);
  const int W = to_px((long long)(maxx - minx) + 2 * mg, px, f.upem);
  const int H = to_px((long long)(maxy - miny) + 2 * mg, px, f.upem);
  R.w = std::max(1, W);
  R.h = std::max(1, H);
  R.gray.assign((size_t)R.w * R.h, 255);

  const int ox = -minx + mg;                        // フォント単位での平行移動
  const int oy = maxy + mg;                         // 上端をこの位置に置く（y は上向き正のまま）

  for (const Item& it : L.items) {
    if (it.cp == 0) {                               // 線（分数・根号の横線）
      const int x0 = to_px((long long)it.x0 + ox, px, f.upem);
      const int x1 = to_px((long long)it.x1 + ox, px, f.upem);
      const int y0 = to_px((long long)oy - it.y1, px, f.upem);   // 上向き -> 下向き
      const int y1 = to_px((long long)oy - it.y0, px, f.upem);
      for (int y = std::max(0, y0); y < std::min(R.h, std::max(y1, y0 + 1)); ++y)
        for (int x = std::max(0, x0); x < std::min(R.w, x1); ++x)
          R.gray[(size_t)y * R.w + x] = 0;
      R.cls.push_back(it.cls);
      R.box.push_back(x0); R.box.push_back(y0); R.box.push_back(x1);
      R.box.push_back(std::max(y1, y0 + 1));
      continue;
    }
    // 記号。stb に「その文字だけ」のビットマップを描かせて貼る
    const Font& g = (it.ital && fi) ? *fi : f;
    const float sc = (float)px / (float)g.upem * (float)it.scale_num / (float)it.scale_den;
    int gx0 = 0, gy0 = 0, gx1 = 0, gy1 = 0;
    stbtt_GetCodepointBitmapBox(g.info, it.cp, sc, sc, &gx0, &gy0, &gx1, &gy1);
    const int gw = gx1 - gx0, gh = gy1 - gy0;
    const int penx = to_px((long long)it.x + ox, px, f.upem);
    const int peny = to_px((long long)oy - it.y, px, f.upem);    // ベースラインの画素位置
    if (gw > 0 && gh > 0) {
      std::vector<unsigned char> bm((size_t)gw * gh, 0);
      stbtt_MakeCodepointBitmap(g.info, bm.data(), gw, gh, gw, sc, sc, it.cp);
      for (int y = 0; y < gh; ++y)
        for (int x = 0; x < gw; ++x) {
          const int dx = penx + gx0 + x, dy = peny + gy0 + y;
          if (dx < 0 || dy < 0 || dx >= R.w || dy >= R.h) continue;
          const int v = 255 - bm[(size_t)y * gw + x];
          unsigned char& dst = R.gray[(size_t)dy * R.w + dx];
          if (v < dst) dst = (unsigned char)v;
        }
    }
    // 正解枠はフォント単位の bbox から作る（ラスタの端の薄い画素に左右されないため）。
    // bbox は絶対座標なので it.x / it.y を足さない（足すと二重加算）
    const int bx0 = to_px((long long)it.x0 + ox, px, f.upem);
    const int bx1 = to_px((long long)it.x1 + ox, px, f.upem);
    const int by0 = to_px((long long)oy - it.y1, px, f.upem);
    const int by1 = to_px((long long)oy - it.y0, px, f.upem);
    R.cls.push_back(it.cls);
    R.box.push_back(bx0); R.box.push_back(by0);
    R.box.push_back(std::max(bx1, bx0 + 1)); R.box.push_back(std::max(by1, by0 + 1));
  }
  return R;
}

}  // namespace ts
