// 検出と解析はここで動かす。1 枚 3 秒級なので、UI スレッドでやると固まって「壊れている」
// ように見える。
//
// 手順: {type:'load', url, stamp} -> {type:'loaded', nodes, bytes}
//       {type:'run', rgba, w, h, imgsz, conf} -> {type:'result', ...} | {type:'error', message}
let M = null;
let loaded = false;

self.onmessage = async (ev) => {
  const msg = ev.data;
  try {
    if (msg.type === 'load') {
      if (!M) {
        // コードだけキャッシュ避けする（stale な .wasm を掴むと原因が分からない失敗になる）
        importScripts('mathcam.js?v=' + msg.stamp);
        M = await createMathcam();
      }
      // モデルにはキャッシュ避けを付けない（12MB をリロードごとに取り直すことになる）
      const r = await fetch(msg.url);
      if (!r.ok) throw new Error('fetch ' + msg.url + ': HTTP ' + r.status);
      const bytes = new Uint8Array(await r.arrayBuffer());
      const p = M._malloc(bytes.length);
      M.HEAPU8.set(bytes, p);
      const nodes = M.ccall('mc_load', 'number', ['number', 'number'], [p, bytes.length]);
      M._free(p);
      if (nodes <= 0) throw new Error('この .onnx は自作ランタイムが読めない形です');
      loaded = true;
      self.postMessage({type: 'loaded', nodes, bytes: bytes.length});
      return;
    }
    if (msg.type === 'run') {
      if (!loaded) throw new Error('モデルがまだ読めていません');
      const {rgba, w, h, imgsz, conf, ox, oy} = msg;
      const p = M._malloc(rgba.length);
      M.HEAPU8.set(rgba, p);
      const t0 = performance.now();
      const n = M.ccall('mc_run', 'number',
                        ['number', 'number', 'number', 'number', 'number'],
                        [p, w, h, imgsz || 640, conf || 0.25]);
      const ms = performance.now() - t0;
      M._free(p);
      const res = JSON.parse(M.UTF8ToString(M.ccall('mc_result', 'number', [], [])));
      if (n < 0) throw new Error(res.error || ('mc_run が ' + n + ' を返しました'));
      // ox/oy は切り出した位置。枠を元の写真の座標に戻すのに要る
      self.postMessage({type: 'result', ...res, ms, ox: ox || 0, oy: oy || 0});
      return;
    }
  } catch (e) {
    self.postMessage({type: 'error', message: (e && e.message) || String(e)});
  }
};
