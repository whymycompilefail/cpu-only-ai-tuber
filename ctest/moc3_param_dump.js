// 读 Cubism moc3 的参数默认值 / Drawable 信息 —— 诊断「配件默认显示」「遮罩糊块」类问题
// 用法: node ctest/moc3_param_dump.js <moc3路径> [过滤关键字|*]
//
// 坑记录（Cubism Core 5.0，frontend/libs/live2dcubismcore.js）：
//  ① module.exports 是 emscripten module，**不是** Live2DCubismCore 命名空间；
//  ② 文件顶层 `var Live2DCubismCore` 是模块作用域 → 用 new Function 包一层 return 才拿得到；
//  ③ 末尾裸引用 window / document → 必须注入（document.currentScript 可为 null）；
//  ④ runtime 异步初始化 → 等 ~2.5 s 后 Moc 才可用；
//  ⑤ Core 5 API 与 4 完全不同：无 createModel/getParameterCount，
//     改为 `new Model(moc)` + 属性 `model.parameters.{count,ids,defaultValues}` /
//     `model.drawables.{count,ids,dynamicFlags,textureIndices,maskCounts}`。
const fs = require('fs');
const path = require('path');

const corePath = path.resolve(__dirname,
  '../Open-LLM-VTuber/frontend/libs/live2dcubismcore.js');
const NS = new Function('window', 'document', 'self',
  fs.readFileSync(corePath, 'utf8') + '\n;return Live2DCubismCore;'
)({}, { currentScript: null }, undefined);

const file = process.argv[2];
const filter = process.argv[3] || '';

setTimeout(() => {
  try {
    const buf = fs.readFileSync(file);
    const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
    const moc = NS.Moc.fromArrayBuffer(ab);
    if (!moc) { console.error('Moc.fromArrayBuffer failed'); process.exit(1); }
    const m = new NS.Model(moc);

    const P = m.parameters, D = m.drawables;
    const rows = [];
    let nonZero = 0;
    for (let i = 0; i < P.count; i++) {
      const r = { i, id: P.ids[i], dv: P.defaultValues[i], mn: P.minimumValues[i], mx: P.maximumValues[i] };
      rows.push(r);
      if (r.dv !== 0) nonZero++;
    }
    console.log(`file: ${path.basename(file)}`);
    console.log(`参数: ${P.count}   默认值非 0: ${nonZero}`);
    console.log();
    // 默认只列非 0；传 '*' 列全部；传子串按 id 匹配列全部匹配项
    const show = filter === '*' ? rows
      : filter ? rows.filter(r => r.id.includes(filter))
        : rows.filter(r => r.dv !== 0);
    console.log('idx  id                     default     min      max');
    for (const r of show) {
      console.log(`${String(r.i).padStart(3)}  ${r.id.padEnd(22)} ${String(r.dv.toFixed(3)).padStart(7)} ${String(r.mn).padStart(8)} ${String(r.mx).padStart(8)}`);
    }

    m.update();
    let vis = 0, masked = 0, invisible = 0;
    const texUse = {};
    for (let i = 0; i < D.count; i++) {
      const visFlag = (D.dynamicFlags[i] & 1) !== 0;
      if (visFlag) vis++; else invisible++;
      if (D.maskCounts[i] > 0) masked++;
      const t = D.textureIndices[i];
      texUse[t] = (texUse[t] || 0) + 1;
    }
    console.log();
    console.log(`Drawable: ${D.count}  update后可见 ${vis}  不可见 ${invisible}  带遮罩 ${masked}`);
    console.log('纹理索引使用分布:', JSON.stringify(texUse));
    console.log(`Canvas: ${m.canvasinfo.CanvasWidth}x${m.canvasinfo.CanvasHeight} pxPerUnit=${m.canvasinfo.PixelsPerUnit}`);

    m.release();
    moc._release();
  } catch (e) {
    console.error('ERROR:', e && e.message);
    process.exit(1);
  }
}, 2500);
