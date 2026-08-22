// ブラウザを開かずに WASM を検査する。**ブラウザと同じ画素**を渡すのが要点なので、
// サンプル PNG をここで自力で展開して RGBA にする（zlib は node 内蔵、外部依存なし）。
// 依存を足さないのは、姉妹リポと同じで「この 1 本で再現できる」状態を保つため。
//
//   node wasm/test_node.js                     # samples/s1.png を読んで答え合わせ
//   node wasm/test_node.js wasm/samples/s4.png # 別のサンプル（表示のみ）
//
// emsdk の node でも普通の node でもよい:
//   /c/prog/emsdk/emsdk/node/*/bin/node wasm/test_node.js
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

// --- 最小の PNG 展開器（8bit、非インタレース、grey/greyA/RGB/RGBA だけ）------------
// stb_image_write が吐くのはこの範囲。範囲外なら黙って壊れないよう投げる。
function decodePng(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error('PNG ではない');
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  const depth = buf[24], ctype = buf[25], interlace = buf[28];
  if (depth !== 8 || interlace !== 0) throw new Error('8bit 非インタレースのみ対応');
  const ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype];
  if (!ch) throw new Error('colortype ' + ctype + ' は未対応（パレットは使っていない）');

  const idat = [];
  for (let i = 8; i + 8 <= buf.length;) {
    const len = buf.readUInt32BE(i), typ = buf.toString('ascii', i + 4, i + 8);
    if (typ === 'IDAT') idat.push(buf.subarray(i + 8, i + 8 + len));
    i += 12 + len;
  }
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = w * ch;
  const out = Buffer.alloc(stride * h);
  let p = 0;
  for (let y = 0; y < h; ++y) {
    const filter = raw[p++];
    const line = raw.subarray(p, p + stride); p += stride;
    const cur = out.subarray(y * stride, (y + 1) * stride);
    const prev = y ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let x = 0; x < stride; ++x) {
      const a = x >= ch ? cur[x - ch] : 0;
      const b = prev ? prev[x] : 0;
      const c = (prev && x >= ch) ? prev[x - ch] : 0;
      let v = line[x];
      if (filter === 1) v += a;
      else if (filter === 2) v += b;
      else if (filter === 3) v += (a + b) >> 1;
      else if (filter === 4) {
        const q = a + b - c;
        const pa = Math.abs(q - a), pb = Math.abs(q - b), pc = Math.abs(q - c);
        v += (pa <= pb && pa <= pc) ? a : (pb <= pc ? b : c);
      } else if (filter !== 0) throw new Error('filter ' + filter);
      cur[x] = v & 255;
    }
  }
  // ブラウザの getImageData と同じ RGBA に揃える
  const rgba = new Uint8Array(w * h * 4);
  for (let i = 0; i < w * h; ++i) {
    const s = i * ch;
    const r = out[s], g = ch >= 3 ? out[s + 1] : r, b = ch >= 3 ? out[s + 2] : r;
    const al = (ch === 2) ? out[s + 1] : (ch === 4 ? out[s + 3] : 255);
    rgba[i * 4] = r; rgba[i * 4 + 1] = g; rgba[i * 4 + 2] = b; rgba[i * 4 + 3] = al;
  }
  return {w, h, rgba};
}

(async () => {
  const root = path.join(__dirname, '..');
  const img = process.argv[2] || path.join(root, 'wasm', 'samples', 's1.png');
  const strict = !process.argv[2];   // 既定のサンプルのときだけ答えを検査する

  const {w, h, rgba} = decodePng(fs.readFileSync(img));
  const M = await require(path.join(__dirname, 'mathcam.js'))();

  // 第 2 引数でモデルを差し替えられる（出荷前に候補の重みでブラウザの道を通すため）
  const modelPath = process.argv[3] || path.join(root, 'models', 'sym_det_v5.onnx');
  const model = fs.readFileSync(modelPath);
  let p = M._malloc(model.length);
  M.HEAPU8.set(model, p);
  const nodes = M.ccall('mc_load', 'number', ['number', 'number'], [p, model.length]);
  M._free(p);
  if (nodes <= 0) { console.error('mc_load 失敗'); process.exit(1); }
  console.log('nodes', nodes, path.basename(modelPath));

  p = M._malloc(rgba.length);
  M.HEAPU8.set(rgba, p);
  const t0 = Date.now();
  const n = M.ccall('mc_run', 'number', ['number', 'number', 'number', 'number', 'number'],
                    [p, w, h, 640, 0.25]);
  const ms = Date.now() - t0;
  M._free(p);
  const res = JSON.parse(M.UTF8ToString(M.ccall('mc_result', 'number', [], [])));

  console.log(path.basename(img), w + 'x' + h, 'syms', n, ms + ' ms');
  console.log('expr  :', res.expr || ('(読めない: ' + res.error + ')'));
  console.log('kind  :', res.kind, res.var || '');
  for (const s of (res.steps || [])) console.log('  [' + s.rule + ']', s.note, '->', s.after);
  console.log('answer:', (res.answer || []).join(', '));

  // **行に切る道も検査する**（ブラウザの「行を自動で切って全部読む」が通る道）。
  // 入口が増えたのに検査が片方だけだと、片方だけ壊れていても気付けない。
  p = M._malloc(rgba.length);
  M.HEAPU8.set(rgba, p);
  const nl = M.ccall('mc_run_lines', 'number', ['number', 'number', 'number', 'number', 'number'],
                     [p, w, h, 640, 0.25]);
  M._free(p);
  const resl = JSON.parse(M.UTF8ToString(M.ccall('mc_result', 'number', [], [])));
  console.log('cells :', (resl.lines || []).length, '塊、記号', nl);
  for (const l of (resl.lines || []))
    console.log('  (' + l.x0 + ',' + l.y0 + ')-(' + l.x1 + ',' + l.y1 + ')',
                l.expr || ('(読めない: ' + l.error + ')'), '->', (l.answer || []).join(', '));

  if (!strict) return;
  const want_expr = 'x^2 - 5*x + 6 = 0';
  // 答えは人が読む文（slv::answer_lines が作る。CLI と同じ文言）
  const want_ans = ['x = 3', 'x = 2'];
  const got_ans = (res.answer || []).slice().sort();
  const bad = [];
  if (res.expr !== want_expr) bad.push('expr: ' + res.expr + ' != ' + want_expr);
  if (got_ans.join(',') !== want_ans.slice().sort().join(',')) bad.push('answer: ' + got_ans);
  if (!(res.steps || []).length) bad.push('手順が空');
  const l0 = (resl.lines || [])[0] || {};
  if ((resl.lines || []).length !== 1) bad.push('塊の数: ' + (resl.lines || []).length + ' != 1');
  if (l0.expr !== want_expr) bad.push('塊の式: ' + l0.expr + ' != ' + want_expr);
  if (bad.length) { console.error('FAIL'); for (const b of bad) console.error(' ', b); process.exit(1); }
  console.log('OK');
})().catch((e) => { console.error(e); process.exit(1); });
