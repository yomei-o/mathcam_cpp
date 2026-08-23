// 学習で使うファイル入出力と画像の縮小 — 姉妹リポ（yolo_lpr_cpp/pure/train_ocr.hpp と crop.hpp）
// から必要なぶんだけ持ってきたもの。**名前空間もそのまま**にしてあるので、向こうの
// train_det.hpp をほぼ無改造で使える（両方を直すときに差分が読める）。
//
// Windows で wide API を使う理由は向こうと同じ: データセットのパスに日本語が入ると
// ANSI 版の fopen / FindFirstFileA は開けない。
#pragma once
#include "autograd.hpp"
#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <dirent.h>
#endif

namespace trn {

#ifdef _WIN32
inline std::wstring to_w(const std::string& s) {
  if (s.empty()) return L"";
  int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
  std::wstring w((size_t)n, L' ');
  MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), w.data(), n);
  return w;
}
inline std::string from_w(const std::wstring& w) {
  if (w.empty()) return "";
  int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), nullptr, 0, nullptr, nullptr);
  std::string s((size_t)n, ' ');
  WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(), s.data(), n, nullptr, nullptr);
  return s;
}
#endif

// Read a whole file, UTF-8 path safe. stb_image's stbi_load() goes through fopen(), which cannot
// open a Japanese path given as UTF-8 on Windows — so images are read here and decoded from memory.
inline std::vector<unsigned char> read_file(const std::string& path) {
  std::vector<unsigned char> out;
#ifdef _WIN32
  FILE* f = _wfopen(to_w(path).c_str(), L"rb");
#else
  FILE* f = fopen(path.c_str(), "rb");
#endif
  if (!f) return out;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  if (n > 0) {
    out.resize((size_t)n);
    out.resize(fread(out.data(), 1, (size_t)n, f));
  }
  fclose(f);
  return out;
}

// Write a whole file, UTF-8 path safe — the mirror of read_file(). std::ofstream takes the path
// through the ANSI code page on Windows, so any directory with Japanese in it (the parity tests use
// tempfile.TemporaryDirectory(), which lands under C:/Users/<name>/AppData/Local/Temp) silently
// fails to open and the caller writes nothing.
inline bool write_file(const std::string& path, const void* data, size_t n) {
#ifdef _WIN32
  FILE* f = _wfopen(to_w(path).c_str(), L"wb");
#else
  FILE* f = fopen(path.c_str(), "wb");
#endif
  if (!f) return false;
  const bool ok = n == 0 || fwrite(data, 1, n, f) == n;
  fclose(f);
  return ok;
}

inline std::vector<std::string> list_dir(const std::string& dir, bool want_dirs) {
  std::vector<std::string> out;
#ifdef _WIN32
  WIN32_FIND_DATAW fd;
  HANDLE h = FindFirstFileW(to_w(dir + "/*").c_str(), &fd);
  if (h == INVALID_HANDLE_VALUE) return out;
  do {
    std::string n = from_w(fd.cFileName);
    if (n == "." || n == "..") continue;
    bool isdir = (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
    if (isdir == want_dirs) out.push_back(n);
  } while (FindNextFileW(h, &fd));
  FindClose(h);
#else
  DIR* d = opendir(dir.c_str());
  if (!d) return out;
  while (dirent* e = readdir(d)) {
    std::string n = e->d_name;
    if (n == "." || n == "..") continue;
    bool isdir = e->d_type == DT_DIR;
    if (isdir == want_dirs) out.push_back(n);
  }
  closedir(d);
#endif
  std::sort(out.begin(), out.end());
  return out;
}

// Recursive image listing that survives Japanese paths. std::filesystem on mingw converts char
// paths through the ANSI code page and throws "Illegal byte sequence" on 自家用/ — so the whole
// project lists directories through list_dir() (wide API on Windows) instead.
inline void list_images_recursive(const std::string& dir, std::vector<std::string>& out, int depth = 0) {
  if (depth > 6) return;
  for (const std::string& f : list_dir(dir, false)) {
    std::string low = f;
    for (char& c : low) c = (char)tolower(c);
    if ((low.size() > 4 && (low.rfind(".jpg") == low.size() - 4 || low.rfind(".png") == low.size() - 4)) ||
        (low.size() > 5 && low.rfind(".jpeg") == low.size() - 5))
      out.push_back(dir + "/" + f);
  }
  for (const std::string& d : list_dir(dir, true)) list_images_recursive(dir + "/" + d, out, depth + 1);
}

}  // namespace trn

namespace jl {

inline Tensor resize_rgb01(const unsigned char* rgb, int W, int H, int iw, int ih) {
  Tensor t = make_tensor({1, 3, ih, iw}, false);
  auto px = [&](int yy, int xx, int c) {
    yy = std::clamp(yy, 0, H - 1); xx = std::clamp(xx, 0, W - 1);
    return (float)rgb[((size_t)yy * W + xx) * 3 + c];
  };
  for (int y = 0; y < ih; ++y)
    for (int x = 0; x < iw; ++x) {
      const float sx = (x + 0.5f) * ((float)W / iw) - 0.5f;
      const float sy = (y + 0.5f) * ((float)H / ih) - 0.5f;
      const int xi = (int)std::floor(sx), yi = (int)std::floor(sy);
      const float fx = sx - xi, fy = sy - yi;
      for (int c = 0; c < 3; ++c) {
        const float v = px(yi, xi, c) * (1 - fx) * (1 - fy) + px(yi, xi + 1, c) * fx * (1 - fy)
                      + px(yi + 1, xi, c) * (1 - fx) * fy + px(yi + 1, xi + 1, c) * fx * fy;
        t->data[(size_t)((c * ih + y) * iw + x)] = v / 255.f;
      }
    }
  return t;
}

}  // namespace jl
