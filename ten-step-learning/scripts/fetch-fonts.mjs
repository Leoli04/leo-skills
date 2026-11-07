#!/usr/bin/env node
/**
 * fetch-fonts.mjs — 把 Google Fonts 的 latin 子集下载并 base64 内联为 assets/fonts-inline.css
 *
 * 为什么需要它：assets/template.html 默认零外链（断网可用）。若想保住 Fraunces / Inter
 * 的拉丁字形与数字观感，用本脚本生成一份纯内联 @font-face，再由 render.py --fonts 注入。
 *
 * 用法：
 *   node scripts/fetch-fonts.mjs           # 生成 assets/fonts-inline.css
 *   node scripts/fetch-fonts.mjs --force   # 已存在也重做
 *
 * 依赖：curl（Windows 自带 / Git for Windows 自带）。国内网络若不通，先设代理：
 *   set HTTPS_PROXY=http://127.0.0.1:7890
 */
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'assets', 'fonts-inline.css');
const TMP = join(ROOT, '.font-cache');
const FORCE = process.argv.includes('--force');

const CSS_URL =
  'https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500' +
  '&family=Inter:wght@400;500;600&display=swap';
// 只要拉丁基本区：中文由本地字体栈承担，latin-ext / cyrillic / greek 白占体积
// （latin-ext 只在出现 à / ł / ő 这类字符时才用得上，回退 Georgia 也几乎看不出来）
const KEEP = process.argv.includes('--latin-ext') ? ['latin', 'latin-ext'] : ['latin'];
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';

function curl(url, out) {
  const args = ['-sS', '--connect-timeout', '10', '--max-time', '60', '-H', `User-Agent: ${UA}`, '-o', out, url];
  // Windows schannel 对部分 CDN 会因「吊销列表离线」直接失败，跳过吊销检查
  if (process.platform === 'win32') args.unshift('--ssl-no-revoke');
  // 只有显式给了代理才走代理，避免把本机代理误用
  if (process.env.HTTPS_PROXY || process.env.https_proxy) {
    args.unshift('--proxy', process.env.HTTPS_PROXY || process.env.https_proxy);
  }
  execFileSync('curl', args, { stdio: ['ignore', 'ignore', 'pipe'] });
}

if (existsSync(OUT) && !FORCE) {
  console.log(`[skip] ${OUT} 已存在（--force 可重做）`);
  process.exit(0);
}

mkdirSync(TMP, { recursive: true });

const cssPath = join(TMP, 'google-fonts.css');
console.log('· 拉取 Google Fonts CSS …');
curl(CSS_URL, cssPath);
const css = readFileSync(cssPath, 'utf8');

// 解析成 [{ family, weight, url, range, subset }]
const faces = [];
// 用「/* subset */ @font-face {...}」整体匹配，靠注释行追踪子集名
for (const raw of css.match(/\/\*[^*]*\*\/[\s\S]*?}/g) || []) {
  const sub = (raw.match(/\/\*\s*([a-z-]+)\s*\*\//) || [])[1] || '';
  const family = (raw.match(/font-family:\s*'([^']+)'/) || [])[1];
  const weight = (raw.match(/font-weight:\s*(\d+)/) || [])[1];
  const url = (raw.match(/url\((https:[^)]+\.woff2)\)/) || [])[1];
  const range = (raw.match(/unicode-range:\s*([^;]+);/) || [])[1];
  if (!family || !url || !weight) continue;
  faces.push({ family, weight, url, range: (range || '').trim(), subset: sub });
}

const picked = faces.filter((f) => KEEP.includes(f.subset));
if (!picked.length) {
  console.error('✗ 未解析到 @font-face，Google Fonts 返回内容可能变了');
  process.exit(1);
}

// 关键去重：Inter / Fraunces 是可变字体，400/500/600 三个字重指向同一个 woff2。
// 若按 face 逐条内联，同一份字节会被 base64 三遍（实测 105 KB 膨胀成 854 KB）。
// 因此按 url 归组，只内联一次，字重写成区间（variable range）。
const groups = new Map();
for (const f of picked) {
  const key = `${f.family}\u0000${f.url}`;
  const g = groups.get(key) || { family: f.family, url: f.url, range: f.range, weights: [] };
  g.weights.push(Number(f.weight));
  if (f.range) g.range = f.range;
  groups.set(key, g);
}

console.log(`· 命中 ${picked.length} 条字面 → 去重后 ${groups.size} 个字体文件`);

const parts = [];
let totalRaw = 0;
for (const g of groups.values()) {
  const name = `${g.family}-${createHash('sha1').update(g.url).digest('hex').slice(0, 8)}.woff2`;
  const file = join(TMP, name);
  if (!existsSync(file)) curl(g.url, file);
  const buf = readFileSync(file);
  totalRaw += buf.length;

  const ws = [...new Set(g.weights)].sort((a, b) => a - b);
  const wDecl = ws.length > 1 ? `${ws[0]} ${ws[ws.length - 1]}` : `${ws[0]}`;
  parts.push(
    `@font-face{font-family:'${g.family}';font-style:normal;font-weight:${wDecl};font-display:swap;` +
      `src:url(data:font/woff2;base64,${buf.toString('base64')}) format('woff2');` +
      (g.range ? `unicode-range:${g.range};` : '') +
      `}`
  );
  console.log(`  · ${g.family} weight ${wDecl} (${(buf.length / 1024).toFixed(1)} KB)`);
}

const header =
  '/* 由 scripts/fetch-fonts.mjs 生成 — Fraunces + Inter latin 子集，纯 base64 内联，零外链。\n' +
  '   用法：python scripts/render.py --data data.json --fonts\n' +
  '   重做：node scripts/fetch-fonts.mjs --force */\n';

writeFileSync(OUT, header + parts.join('\n') + '\n', 'utf8');
const size = readFileSync(OUT).length;
console.log(`✓ 写出 ${OUT}`);
console.log(`  原始字体 ${(totalRaw / 1024).toFixed(1)} KB → CSS ${(size / 1024).toFixed(1)} KB`);
