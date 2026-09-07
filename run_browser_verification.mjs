import fs from 'node:fs';
import path from 'node:path';

async function main() {
  console.log('='.repeat(80));
  console.log('🌐【实机浏览器交互审计】验证 prev_drawdown_180_pct 与 500日新高徽章');
  console.log('='.repeat(80));

  const listResp = await fetch('http://127.0.0.1:9222/json/list');
  const pages = await listResp.json();
  const page = pages.find(p => p.type === 'page');

  if (!page) {
    console.error('[FATAL] 未找到 Chrome CDP page 目标');
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
    if (res.result.exceptionDetails) {
      throw new Error(JSON.stringify(res.result.exceptionDetails));
    }
    return res.result.result.value;
  }

  await new Promise(resolve => ws.onopen = resolve);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(msg.error);
      else resolve(msg);
    } else if (msg.method === 'Runtime.consoleAPICalled') {
      const args = (msg.params.args || []).map(a => a.value || a.description).join(' ');
      if (msg.params.type === 'error') {
        console.error(`  [Browser Console Error]`, args);
      }
    }
  };

  await send('Page.enable');
  await send('Runtime.enable');

  console.log('[1/5] 导航至 http://localhost:8089/index.html ...');
  await send('Page.navigate', { url: 'http://localhost:8089/index.html' });

  // 等待页面与 compact 数据加载就绪
  let ready = false;
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 500));
    const title = await evaluate(`document.title`).catch(() => '');
    const stockCount = await evaluate(`typeof masterStockList !== 'undefined' ? masterStockList.length : 0`).catch(() => 0);
    const trCount = await evaluate(`document.querySelectorAll('#stock-tbody tr').length`).catch(() => 0);
    if (stockCount > 1000 || trCount > 10) {
      ready = true;
      console.log(`  ✅ 页面与数据就绪! 标的总数: ${stockCount}, 表格行数: ${trCount}, 标题: ${title}`);
      break;
    }
  }

  if (!ready) {
    throw new Error('页面加载超时或 masterStockList 未就绪');
  }

  // 1. 验证最新日各因子卡片计数
  console.log('\n[2/5] 核验顶部 9 大因子卡片统计...');
  const stats = await evaluate(`
    (() => {
      return {
        total: document.getElementById('stat-total')?.innerText,
        label1: document.getElementById('stat-label1')?.innerText,
        hl5r: document.getElementById('stat-hl5r')?.innerText,
        f5r: document.getElementById('stat-5r')?.innerText,
        high_all: document.getElementById('stat-high-all')?.innerText,
        high_500: document.getElementById('stat-high-500')?.innerText,
        high_250: document.getElementById('stat-high-250')?.innerText,
        hl_amo: document.getElementById('stat-hlamo')?.innerText,
        amo: document.getElementById('stat-amo')?.innerText,
        ma377: document.getElementById('stat-ma377')?.innerText,
        ma250: document.getElementById('stat-ma250')?.innerText
      };
    })()
  `);
  console.log('  📊 卡片统计:', JSON.stringify(stats, null, 2));

  // 2. 验证新高筛选与徽章展示
  console.log('\n[3/5] 验证 500日新高徽章展示 (包含口径，杜绝遮蔽)...');
  await evaluate(`setQuickFilter('high_500')`);
  await new Promise(r => setTimeout(r, 600));

  const high500Verification = await evaluate(`
    (() => {
      const rows = document.querySelectorAll('#table-body tr');
      const results = [];
      for (let i = 0; i < Math.min(rows.length, 10); i++) {
        const tr = rows[i];
        const code = tr.querySelector('td:nth-child(1)')?.innerText.trim();
        const name = tr.querySelector('td:nth-child(2)')?.innerText.trim();
        const badgesCell = tr.querySelector('td:nth-child(6)');
        const badgesText = badgesCell ? badgesCell.innerText.replace(/\s+/g, ' ') : '';
        const has500Badge = badgesText.includes('500日新高');
        const hasAthBadge = badgesText.includes('覆盖期新高');
        results.push({ code, name, badgesText, has500Badge, hasAthBadge });
      }
      return {
        filteredCount: filteredData.length,
        domRowCount: rows.length,
        samples: results
      };
    })()
  `);
  console.log(`  ✅ 500日新高筛选结果: filteredData.length = ${high500Verification.filteredCount}, DOM 行数 = ${high500Verification.domRowCount}`);
  console.log('  抽样前 5 只标的徽章情况:');
  high500Verification.samples.slice(0, 5).forEach(s => {
    console.log(`    - [${s.code} ${s.name}]: "${s.badgesText}" (包含500日新高: ${s.has500Badge}, 包含覆盖期新高: ${s.hasAthBadge})`);
  });

  const allHave500Badge = high500Verification.samples.length > 0 && high500Verification.samples.every(s => s.has500Badge);
  if (!allHave500Badge) {
    console.error('  ❌ 存在 500日新高未正确渲染的情况!');
  } else {
    console.log('  🎉 成功验证: 在 500日新高筛选下，所有抽样标的均显式渲染【🔥 500日新高】，未被覆盖期新高掩盖!');
  }

  // 3. 验证 HL+AMO 弹窗回撤百分比 (prev_drawdown_180_pct)
  console.log('\n[4/5] 验证 HL+AMO 弹窗中前180日回撤幅度展示...');
  await evaluate(`setQuickFilter('hl_amo')`);
  await new Promise(r => setTimeout(r, 600));

  const hlAmoPopupCheck = await evaluate(`
    (() => {
      if (!filteredData || filteredData.length === 0) return { error: 'HL+AMO 无过滤数据' };
      const firstStock = filteredData[0];
      const code = firstStock.code;
      const name = firstStock.name;
      const activeDate = activeDates[0];

      // 触发弹窗
      showFactorDetail(code, name, activeDate);

      // 读取弹窗内字段
      const modalVisible = !document.getElementById('factor-detail-modal').classList.contains('hidden');
      const prevDrawdownText = document.getElementById('pop-prev-drawdown-180')?.innerText.trim();
      const popAmoStatus = document.getElementById('pop-amo-status')?.innerText.trim();
      const popHighStatus = document.getElementById('pop-high-status')?.innerHTML.trim();

      return {
        code,
        name,
        modalVisible,
        prevDrawdownText,
        popAmoStatus,
        popHighStatus
      };
    })()
  `);

  console.log('  🎯 弹窗核验结果:', hlAmoPopupCheck);
  if (hlAmoPopupCheck.error || hlAmoPopupCheck.prevDrawdownText === '--' || !hlAmoPopupCheck.prevDrawdownText.includes('%')) {
    console.error(`  ❌ 弹窗 prev_drawdown_180 显示异常: ${hlAmoPopupCheck.prevDrawdownText}`);
  } else {
    console.log(`  🎉 成功验证: HL+AMO 弹窗正常展示前180日回撤幅度: ${hlAmoPopupCheck.prevDrawdownText}`);
  }

  // 4. 测试同时命中 覆盖期新高 与 500日新高 标的的弹窗 #pop-high-status
  console.log('\n[5/5] 验证双重或多重新高标的在弹窗中的复合展示...');
  const dualHighCheck = await evaluate(`
    (() => {
      // 寻找一只既命中 factor_high_all 又命中 factor_high_500 的股票
      const dualStock = masterStockList.find(s => s.factors.factor_high_all === 1 && s.factors.factor_high_500 === 1);
      if (!dualStock) return { found: false };

      showFactorDetail(dualStock.code, dualStock.name, activeDates[0]);
      const highStatusEl = document.getElementById('pop-high-status');
      return {
        found: true,
        code: dualStock.code,
        name: dualStock.name,
        highStatusHtml: highStatusEl ? highStatusEl.innerHTML : '',
        highStatusText: highStatusEl ? highStatusEl.innerText : ''
      };
    })()
  `);

  if (dualHighCheck.found) {
    console.log(`  🎯 标的 [${dualHighCheck.code} ${dualHighCheck.name}] 弹窗新高状态:`);
    console.log(`    文本: ${dualHighCheck.highStatusText}`);
    console.log(`    HTML: ${dualHighCheck.highStatusHtml}`);
    const hasBoth = dualHighCheck.highStatusText.includes('覆盖期新高') && dualHighCheck.highStatusText.includes('500日新高');
    if (hasBoth) {
      console.log('  🎉 成功验证: 覆盖期新高与 500日新高在弹窗卡片中并列共存展示，杜绝完全遮蔽!');
    } else {
      console.error('  ❌ 弹窗未同时展示覆盖期新高与 500日新高!');
    }
  }

  // 专门打开 HL+AMO 标的 000417 并滚动到 AMO / HL+AMO 卡片
  console.log('\n📸 打开 000417 合百集团并滚动到 HL+AMO 卡片截取证据...');
  await evaluate(`showFactorDetail('000417', '合百集团', activeDates[0])`);
  await new Promise(r => setTimeout(r, 400));
  await evaluate(`document.getElementById('pop-prev-drawdown-180').scrollIntoView({ behavior: 'instant', block: 'center' })`);
  await new Promise(r => setTimeout(r, 400));

  const ss1 = await send('Page.captureScreenshot', { format: 'png' });
  const ss1Buffer = Buffer.from(ss1.result.data, 'base64');
  const ss1Path = path.join(process.cwd(), 'hl_amo_modal_verified.png');
  fs.writeFileSync(ss1Path, ss1Buffer);
  console.log(`  ✅ 截图已保存: ${ss1Path} (${(ss1Buffer.length / 1024).toFixed(1)} KB)`);

  // 关闭弹窗并截取 500日新高表格视图
  await evaluate(`document.getElementById('factor-detail-modal').classList.add('hidden')`);
  await evaluate(`setQuickFilter('high_500')`);
  await new Promise(r => setTimeout(r, 600));

  console.log('📸 保存 500日新高筛选列表实机验证截图...');
  const ss2 = await send('Page.captureScreenshot', { format: 'png' });
  const ss2Buffer = Buffer.from(ss2.result.data, 'base64');
  const ss2Path = path.join(process.cwd(), 'high_500_table_verified.png');
  fs.writeFileSync(ss2Path, ss2Buffer);
  console.log(`  ✅ 截图已保存: ${ss2Path} (${(ss2Buffer.length / 1024).toFixed(1)} KB)`);

  console.log('\n' + '='.repeat(80));
  console.log('✅ 全部实机浏览器交互审计与截图留存顺利完成!');
  console.log('='.repeat(80));
  process.exit(0);
}

main().catch(err => {
  console.error('[FATAL]', err);
  process.exit(1);
});
