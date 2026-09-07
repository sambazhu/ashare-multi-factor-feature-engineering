import fs from 'node:fs';
import path from 'node:path';

const ARTIFACT_DIR = './screenshots';
const REMOTE_URL = 'http://localhost:8089/index.html';

async function main() {
  const listResp = await fetch('http://127.0.0.1:9222/json/list');
  const pages = await listResp.json();
  let page = pages.find(p => p.type === 'page');

  if (!page) {
    console.error('No Chrome page found');
    process.exit(1);
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let idCounter = 1;
  const pending = new Map();

  function send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = idCounter++;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async function evaluate(expression) {
    const res = await send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true
    });
    return res.result.result ? res.result.result.value : null;
  }

  async function capture(filename) {
    const res = await send('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(res.result.data, 'base64');
    const outPath = path.join(ARTIFACT_DIR, filename);
    fs.writeFileSync(outPath, buffer);
    console.log(`📸 远程服务截图保存成功: ${outPath} (${(buffer.length / 1024).toFixed(1)} KB)`);
    return outPath;
  }

  await new Promise(resolve => ws.onopen = resolve);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(msg.error);
      else resolve(msg);
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 900,
    deviceScaleFactor: 2,
    mobile: false
  });

  console.log(`🌐 正在导航至远程服务: ${REMOTE_URL} ...`);
  await send('Page.navigate', { url: REMOTE_URL });
  await new Promise(r => setTimeout(r, 2500));

  // 1. 全景主看板首页截图 (2026-08-27)
  await evaluate(`setQuickFilter('all'); closeModal('dict-modal'); closeModal('factor-detail-modal');`);
  await new Promise(r => setTimeout(r, 800));
  await capture('remote_dashboard_overview.png');

  // 2. 覆盖期新高 (2026-08-27 命中 27 只)
  await evaluate(`setQuickFilter('high_all');`);
  await new Promise(r => setTimeout(r, 800));
  await capture('remote_dashboard_high_all.png');

  // 3. 底部五阳 HL+5R (2026-08-27 命中 58 只)
  await evaluate(`setQuickFilter('hl_5r');`);
  await new Promise(r => setTimeout(r, 800));
  await capture('remote_dashboard_hl_5r.png');

  // 4. 多因子量化详情弹窗 (以 000509 华塑控股 2026-08-27 为例)
  await evaluate(`showFactorDetail('000509', '华塑控股', activeDates[0]);`);
  await new Promise(r => setTimeout(r, 800));
  await capture('remote_modal_factor_detail.png');
  await evaluate(`closeModal('factor-detail-modal');`);

  console.log('✅ 远程服务器所有真实视图 2K 高清截图已捕获完毕！');
  ws.close();
  process.exit(0);
}

main().catch(err => {
  console.error('Remote capture error:', err);
  process.exit(1);
});
