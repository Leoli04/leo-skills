// Phase 9.5 第二遍 · 动作 1：导出报告「渲染后」的全文，供读者视角通读。
// 用法：node _reader.js "<报告.html 绝对路径>" [输出 txt 路径]
// 依赖 playwright-core + 本机 Chrome。渲染后文本不含源码注释，阅读顺序 = 真实阅读顺序。
const { chromium } = require('C:/Users/86130/.workbuddy/binaries/node/workspace/node_modules/playwright-core');
const { pathToFileURL } = require('url');
const fs = require('fs');
const path = require('path');

const target = process.argv[2];
if (!target) { console.error('用法: node _reader.js "<报告.html 绝对路径>" [输出txt]'); process.exit(1); }
const htmlPath = path.resolve(target);
const outPath = process.argv[3] || path.join(path.dirname(htmlPath), '_reader_out.txt');

(async () => {
  const b = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', args: ['--allow-file-access-from-files'] });
  const p = await b.newPage({ viewport: { width: 1180, height: 900 } });
  await p.goto(pathToFileURL(htmlPath).href, { waitUntil: 'load' });
  await p.waitForTimeout(2000);
  const out = await p.evaluate(() => [...document.querySelectorAll('.section')].map(s => ({
    id: s.id,
    title: s.querySelector('.section-title') ? s.querySelector('.section-title').textContent.trim() : '',
    text: s.innerText.replace(/\s+/g, ' ').trim()
  })));
  let buf = '';
  for (const s of out) { buf += '\n########## ' + s.id + ' | ' + s.title + ' ##########\n' + s.text + '\n'; }
  fs.writeFileSync(outPath, buf, 'utf8');
  console.log('已导出 ' + out.length + ' 节 → ' + outPath);
  await b.close();
})();
