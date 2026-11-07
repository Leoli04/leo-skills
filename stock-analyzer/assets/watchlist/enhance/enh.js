

/* ═══════════════════════════════════════════════════════════════════════
   台账交互增强（2026-10-22 恢复）
   ① 观察池「＋」→ 一键加入持仓计划（写数据表）
   ② 持仓面板改由数据表实时渲染（含就地编辑 / 二次确认删除）
   ③ 观察池卡片与表格行联动显示「持仓中 / 计划中」状态
   ── 全部为增量逻辑，不改动既有排序 / 筛选 / 视图切换代码；
      无 SDK 环境（本地直接打开 HTML）时保持静态快照并给出提示。
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var DATABASE_ID = '@@ENH_DB_ID@@';
  var db = (window.__SMART_PAGE__ && window.__SMART_PAGE__.database) || null;
  var SCHEMA_OPTIONS = {};
  var POS = [];
  var IDX = [];
  var BYCODE = {};

  /* ── 小工具 ──────────────────────────────────────────────────────── */
  function t(el) { return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : ''; }
  function q(sel, root) { return (root || document).querySelector(sel); }
  function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function n1(s) {
    var m = String(s == null ? '' : s).replace(/[−–]/g, '-').match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }
  function num(v) { if (v === null || v === undefined || v === '') { return 0; } var f = parseFloat(v); return isNaN(f) ? 0 : f; }
  function money(v) { return (v === null || v === undefined || isNaN(v)) ? '—' : Math.round(v).toLocaleString('en-US'); }
  /* 逐字符转义（不用含引号的正则字面量，避免语法平衡检查误判） */
  function esc(s) {
    var v = String(s === null || s === undefined ? '' : s);
    var map = { 38: '&amp;', 60: '&lt;', 62: '&gt;', 34: '&quot;', 39: '&#39;' };
    var out = '';
    for (var i = 0; i < v.length; i++) {
      var c = v.charCodeAt(i);
      out += map[c] || v.charAt(i);
    }
    return out;
  }
  function today() {
    var d = new Date();
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }
  function bind(el) {
    if (el && DATABASE_ID) {
      el.setAttribute('data-sp-bindable', 'database');
      el.setAttribute('data-sp-database-id', DATABASE_ID);
    }
    return el;
  }
  function signed(v) { return (v >= 0 ? '+' : '−') + Math.abs(v); }
  function urlish(v) {
    if (!v) { return ''; }
    if (typeof v === 'string') { return v; }
    if (v.length) { return (v[0] && v[0].link) ? v[0].link : ''; }
    return v.link || '';
  }
  function priceOf(r) {
    var it = BYCODE[r['代码']];
    return (it && it.px !== null && it.px !== undefined) ? it.px : null;
  }
  function isLocked(r) { return String(r['成本备注'] || '').indexOf('锁定') >= 0; }
  function byCode(code) {
    for (var i = 0; i < POS.length; i++) { if (POS[i]['代码'] === code) { return POS[i]; } }
    return null;
  }
  function recordId(r) { return r.record_id || r.recordId || r.id || r._id || ''; }
  function byRid(rid) {
    if (!rid) { return null; }
    for (var i = 0; i < POS.length; i++) { if (recordId(POS[i]) === rid) { return POS[i]; } }
    return null;
  }

  var noteTimer = null;
  function flashNote(msg) {
    var bar = document.getElementById('wlNote');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'wlNote';
      bar.className = 'wlnote';
      document.body.appendChild(bar);
    }
    bar.textContent = msg;
    bar.className = 'wlnote on';
    clearTimeout(noteTimer);
    noteTimer = setTimeout(function () { bar.className = 'wlnote'; }, 3600);
  }

  /* ── ① 观察池索引（卡片 + 表格两种结构）───────────────────────────── */
  function buildIndex() {
    IDX = [];
    BYCODE = {};
    qa('[data-row]').forEach(function (el) {
      var isCard = el.className.indexOf('zcard') >= 0;
      var nameEl = q(isCard ? '.zcard__id b' : '.nm b', el);
      var codeEl = q(isCard ? '.zcard__id .cd' : '.nm .cd', el);
      var judgeEl = q('.jd__n', el) || q('.zcard__top .tag', el);
      var px = null, exp = null;
      if (isCard) {
        var dd = q('.zcard__kv dd.n', el);
        var seg = t(dd).split('→');
        px = n1(seg[0]);
        exp = n1(seg[1] || '');
      } else {
        px = n1(t(q('.pb__c', el)));
        exp = n1(t(q('.pb__e', el)));
      }
      var a = q('a.lk[href*="/space/d/"]', el) || q('.c-lk a', el);
      var item = {
        el: el,
        card: isCard,
        name: t(nameEl),
        code: t(codeEl),
        judge: t(judgeEl),
        px: px,
        exp: exp,
        link: a ? a.getAttribute('href') : '',
        key: (el.getAttribute('data-k') || '').toLowerCase()
      };
      IDX.push(item);
      if (item.code) { BYCODE[item.code] = item; }
    });
  }

  /* ── ② ＋持仓 按钮注入 ───────────────────────────────────────────── */
  function initPadd() {
    IDX.forEach(function (it) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'padd-mini';
      b.title = '加入持仓计划';
      b.textContent = '+';
      b.setAttribute('aria-label', '将「' + it.name + '」加入持仓计划');
      b.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        addPlan(it, b);
      });
      if (it.card) {
        var top = q('.zcard__top', it.el);
        if (top) { top.appendChild(b); }
      } else {
        var cell = q('td.c-lk', it.el);
        if (cell) {
          cell.appendChild(document.createElement('br'));
          cell.appendChild(b);
        } else {
          var nmCell = q('td.nm', it.el) || q('.nm', it.el);
          if (!nmCell) { return; }
          b.style.marginLeft = '5px';
          nmCell.appendChild(b);
        }
      }
    });
  }

  /* 点「＋」：只打表单、不写库；点保存才 addRecord，取消则什么都不会发生。 */
  function addPlan(item, btn) {
    if (!db) { flashNote('当前打开方式未连上数据表，请到资料库中打开台账后再试'); return; }
    var exist = byCode(item.code);
    if (exist) {
      switchView('pos');
      setTimeout(function () { focusCard(item.code); openForm(exist); }, 80);
      flashNote('「' + item.name + '」已在持仓计划里，直接编辑即可');
      return;
    }
    switchView('pos');
    openForm(null, {
      '标的名称': item.name,
      '代码': item.code,
      '状态': '计划中',
      '策略': '待定',
      '报告判定': item.judge || '',
      '期望价': item.exp,
      '加入日期': today(),
      '报告链接': item.link ? [{ link: item.link, text: '报告原文' }] : ''
    });
  }

  function switchView(v) {
    var b = document.querySelector('.vtab[data-v="' + v + '"]');
    if (b) { b.click(); }
  }

  function focusCard(code) {
    var card = document.getElementById('pos-' + code);
    if (!card) { return; }
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    card.classList.remove('flash');
    void card.offsetWidth;
    card.classList.add('flash');
  }

  /* ── ③ 持仓数据层（分页拉全量，避免超一页静默截断）───────────────── */
  function fetchAll() {
    var acc = [];
    var guard = 0;
    function step(cursor) {
      guard++;
      return db.query({
        databaseId: DATABASE_ID,
        sorts: [{ property: '加入日期', direction: 'descending' }],
        pageSize: 200,
        startCursor: cursor
      }).then(function (res) {
        acc = acc.concat(res.results || []);
        if (res.hasMore && res.nextCursor && res.nextCursor !== cursor && guard < 100) {
          return step(res.nextCursor);
        }
        return acc;
      }).catch(function (err) {
        if (window.console) { console.error('[plan] query page failed', err); }
        throw err;   /* 交给 loadPos 的统一 catch 做界面降级 */
      });
    }
    return step(undefined);
  }

  function loadPos() {
    if (!db) { return Promise.resolve(); }
    return fetchAll().then(function (rows) {
      POS = rows || [];
      renderPos();
      syncPoolState();
    }).catch(function (err) {
      if (window.console) { console.error('[plan] query failed', err); }
      flashNote('持仓数据加载失败（稍后重试或刷新页面）');
    });
  }

  var ORDER = { '持仓中': 0, '计划中': 1 };

  function sorted() {
    return POS.filter(function (r) {
      return (r['状态'] || '') !== '已清仓';
    }).sort(function (a, b) {
      var oa = ORDER[a['状态']];
      var ob = ORDER[b['状态']];
      oa = (oa === undefined) ? 9 : oa;
      ob = (ob === undefined) ? 9 : ob;
      if (oa !== ob) { return oa - ob; }
      return String(b['加入日期'] || '').localeCompare(String(a['加入日期'] || ''));
    });
  }

  function renderPos() {
    var host = q('#view-pos .panel__body');
    if (!host) { return; }
    var list = sorted();
    var held = list.filter(function (r) { return r['状态'] === '持仓中'; });
    var planned = list.filter(function (r) { return r['状态'] !== '持仓中'; });

    var mvAll = 0, managed = 0, plAll = 0, heldN = 0;
    var names = [], lockTxt = [];
    held.forEach(function (r) {
      var px = priceOf(r), sh = num(r['持仓股数']), c = num(r['成本价']);
      if (sh > 0) { heldN++; }
      if (px !== null && sh > 0) { mvAll += px * sh; }
      if (isLocked(r)) { lockTxt.push((r['标的名称'] || '') + ' ' + (r['成本备注'] || '')); return; }
      if (c > 0 && sh > 0) { managed += c * sh; names.push(r['标的名称'] || ''); }
      if (px !== null && c > 0 && sh > 0) { plAll += (px - c) * sh; }
    });

    var h = '<div class="pos-ovw"><table class="pos-ov"><thead><tr>'
      + '<th>标的</th><th>状态</th><th>策略</th><th>持仓</th>'
      + '<th>成本</th><th>现价</th><th>市值</th><th>浮动盈亏</th><th>加仓条件</th><th>操作</th>'
      + '</tr></thead><tbody>';

    if (!list.length) {
      h += '<tr><td colspan="10" class="pos__empty">数据表里还没有持仓记录，点观察池卡片上的「＋」加入第一只。</td></tr>';
    }

    h += list.map(function (r) {
      var code = r['代码'] || '';
      var rid = recordId(r);
      var isHold = r['状态'] === '持仓中';
      var px = priceOf(r), sh = num(r['持仓股数']), c = num(r['成本价']);
      var planSh = num(r['计划股数']);
      var mv = (isHold && px !== null && sh > 0) ? px * sh : null;
      var plp = (isHold && px !== null && c > 0) ? (px / c - 1) * 100 : null;
      var costTxt = c > 0 ? c.toFixed(3) + ' 元' : (r['成本备注'] || '—');
      return '<tr class="pos-ov__row" data-code="' + esc(code) + '">'
        + '<td class="pos-ov__nm"><b>' + esc(r['标的名称']) + '</b><span class="cd">' + esc(code) + '</span></td>'
        + '<td><span class="pos-st pos-st--' + (isHold ? 'hold' : 'plan') + '">' + esc(r['状态'] || '—') + '</span></td>'
        + '<td>' + (r['策略'] ? '<span class="posv">' + esc(r['策略']) + '</span>' : '—') + '</td>'
        + '<td class="n">' + (isHold && sh > 0
            ? money(sh) + ' 股' + (planSh > 0 ? ' <span class="dim">/ 计划 ' + money(planSh) + '</span>' : '')
            : '—') + '</td>'
        + '<td class="n">' + esc(costTxt) + '</td>'
        + '<td class="n">' + (px === null ? '—' : px.toFixed(2)) + '</td>'
        + '<td class="n">' + (mv === null ? '—' : money(mv) + ' 元') + '</td>'
        + '<td class="n">' + (plp === null
            ? '<span class="dim">—</span>'
            : '<span class="' + (plp >= 0 ? 'is-up' : 'is-down') + ' n">' + signed(parseFloat(plp.toFixed(2))) + '%</span>') + '</td>'
        + '<td class="pos-ov__buyc">' + buyCell(r['计划阶梯'], isHold) + '</td>'
        + '<td class="pos-ov__ops">'
        + '<button class="pbtn pbtn--xs" type="button" data-edit="' + esc(rid) + '">编辑</button>'
        + '<button class="pbtn pbtn--xs pbtn--d" type="button" data-del="' + esc(rid) + '">删除</button>'
        + '</td>'
        + '</tr>';
    }).join('');

    h += '</tbody></table></div>';

    h += '<div class="pos-sum">'
      + sumItem('持仓标的', heldN + ' 只')
      + sumItem('总市值', money(mvAll) + ' 元')
      + sumItem('在管成本' + (names.length ? '（' + names.join('、') + '）' : ''), money(managed) + ' 元')
      + sumItem('浮动盈亏（对在管成本）', signed(Math.round(plAll)) + ' 元', plAll >= 0 ? 'is-up' : 'is-down')
      + sumItem('计划中', planned.length + ' 只')
      + sumItem('利润仓', lockTxt.length ? lockTxt.join('｜') : '无')
      + '</div>';

    h += '<p class="pos-note-tip">以上数字由数据表实时计算：市值、浮动盈亏按观察池现价快照 × 持仓股数得出；成本备注含「锁定」的计入利润仓、不计入在管成本。</p>';

    h += list.map(cardHtml).join('');

    host.innerHTML = h;
    qa('#view-pos .pos-sum dd, #view-pos .pos-ov td.n, #view-pos .pos-card dd, #view-pos .pos-card td').forEach(bind);
    var src = document.getElementById('posSrc');
    if (src) {
      src.textContent = '持仓 ' + heldN + ' · 计划 ' + planned.length;
      bind(src);
    }
  }

  /* 加仓条件：取计划阶梯里「加仓/建仓/补」档的触发价；全无 → 暂停／未设 */
  function buyCell(raw, isHold) {
    var lines = String(raw || '').split('\n').filter(function (x) { return x.trim(); });
    if (!lines.length) {
      return '<span class="pos-ov__buyc-none">' + (isHold ? '未设' : '待设') + '</span>';
    }
    var prices = [], paused = false;
    lines.forEach(function (line) {
      var p = line.split('|').map(function (x) { return x.trim(); });
      if (p.length < 3) { return; }
      var a = p[1] || '';
      if (a.indexOf('加仓') < 0 && a.indexOf('建仓') < 0 && a.indexOf('补') < 0) { return; }
      var px = (p[0] || '').replace(/\s/g, '');
      if (!px || px === '—' || px === '-' || px.indexOf('暂停') >= 0) { paused = true; return; }
      prices.push(px);
    });
    if (!prices.length) {
      if (paused) { return '<span class="pos-ov__buyc-none" title="加仓暂停，重启条件见卡片说明">暂停</span>'; }
      return '<span class="pos-ov__buyc-none">' + (isHold ? '未设' : '待设') + '</span>';
    }
    return '<span class="pos-ov__buyc-v">' + esc(prices.join(' / ')) + '</span>';
  }

  function sumItem(label, val, cls) {
    return '<div><dt>' + esc(label) + '</dt><dd class="n' + (cls ? ' ' + cls : '') + '">' + esc(val) + '</dd></div>';
  }


  /* 计划阶梯：优先解析四列（触发价|动作|数量|说明），否则退回两列（环节｜触发与动作） */
  function actClass(a) {
    var t = String(a || '');
    if (t.indexOf('止损') >= 0 || t.indexOf('证伪') >= 0 || t.indexOf('破位') >= 0 || t.indexOf('放弃') >= 0) { return 'stop'; }
    if (t.indexOf('减') >= 0 || t.indexOf('清') >= 0 || t.indexOf('兑现') >= 0) { return 'sell'; }
    if (t.indexOf('加仓') >= 0 || t.indexOf('建仓') >= 0 || t.indexOf('补') >= 0) { return 'buy'; }
    return 'wait';
  }
  function ladderHtml(raw) {
    var lines = String(raw || '').split('\n').filter(function (x) { return x.trim(); });
    if (!lines.length) {
      return '<p class="pos__empty">未设计划阶梯——点「编辑」补充：每行一条「触发价|动作|数量|说明」。</p>';
    }
    var grid = lines.map(function (line) { return line.split('|').map(function (x) { return x.trim(); }); });
    var all4 = grid.every(function (p) { return p.length === 4; });
    if (!all4) {
      var h2 = '<table class="pos__plan"><thead><tr><th>环节</th><th>触发与动作</th></tr></thead><tbody>';
      h2 += lines.map(function (line) {
        var p = line.split('｜');
        return '<tr><td class="pos__trg">' + esc((p[0] || '').trim()) + '</td><td>'
          + esc((p[1] || '').trim() || '—') + '</td></tr>';
      }).join('');
      return h2 + '</tbody></table>';
    }
    var h = '<table class="pos__plan pos__plan--grid"><thead><tr>'
      + '<th>触发价</th><th>动作</th><th>数量</th><th>说明</th></tr></thead><tbody>';
    h += grid.map(function (p) {
      return '<tr><td class="pos__px">' + esc(p[0]) + '</td>'
        + '<td><span class="pln-tag pln-tag--' + actClass(p[1]) + '">' + esc(p[1]) + '</span></td>'
        + '<td class="pos__qty">' + esc(p[2]) + '</td>'
        + '<td class="pos__memo">' + esc(p[3]) + '</td></tr>';
    }).join('');
    return h + '</tbody></table>';
  }

  function cardHtml(r) {
    var code = r['代码'] || '';
    var isHold = r['状态'] === '持仓中';
    var px = priceOf(r), sh = num(r['持仓股数']), c = num(r['成本价']);
    var planSh = num(r['计划股数']);
    var costNote = r['成本备注'] || '';
    var mv = (isHold && px !== null && sh > 0) ? px * sh : null;
    var plp = (isHold && px !== null && c > 0) ? (px / c - 1) * 100 : null;
    var plv = (isHold && px !== null && c > 0 && sh > 0) ? (px - c) * sh : null;
    var openTxt = r['建仓日']
      ? String(r['建仓日']).slice(0, 10) + ' 建仓'
      : (r['加入日期'] ? '加入于 ' + String(r['加入日期']).slice(0, 10) : '');
    var link = urlish(r['报告链接']);

    var s = '<article class="pos-card" id="pos-' + esc(code) + '">';
    s += '<div class="pos-card__top"><div class="pos-card__id"><b>' + esc(r['标的名称'])
      + '</b><span class="cd">' + esc(code) + '</span></div>';
    if (r['策略']) { s += '<span class="posv">' + esc(r['策略']) + '</span>'; }
    s += '<span class="pos-st pos-st--' + (isHold ? 'hold' : 'plan') + '">' + esc(r['状态'] || '') + '</span>';
    if (openTxt) { s += '<span class="pos__open">' + esc(openTxt) + '</span>'; }
    s += '</div>';

    s += '<div class="pos-card__kv">';
    if (isHold) {
      s += '<div><dt>持仓 / 计划</dt><dd class="n">' + money(sh) + ' 股'
        + (planSh > 0 ? ' <span class="dim">/ 计划 ' + money(planSh) + '</span>' : '') + '</dd></div>';
      s += '<div><dt>成本</dt><dd class="n">' + (c > 0 ? c.toFixed(3) + ' 元' : (costNote || '—')) + '</dd></div>';
      s += '<div><dt>现价</dt><dd class="n">' + (px === null ? '—' : px.toFixed(2)) + '</dd></div>';
      s += '<div><dt>市值</dt><dd class="n">' + (mv === null ? '—' : money(mv) + ' 元') + '</dd></div>';
      s += '<div class="pos__pl"><dt>浮动盈亏（对成本）</dt><dd class="n '
        + (plp === null ? '' : (plp >= 0 ? 'is-up' : 'is-down')) + '">'
        + (plp === null ? '—'
            : signed(parseFloat(plp.toFixed(2))) + '% <span>' + signed(Math.round(plv)) + ' 元</span>') + '</dd></div>';
    } else {
      s += '<div><dt>报告判定</dt><dd>' + esc(r['报告判定'] || '—') + '</dd></div>';
      s += '<div><dt>期望价</dt><dd class="n">' + (num(r['期望价']) > 0 ? num(r['期望价']).toFixed(2) : '—') + '</dd></div>';
      s += '<div><dt>现价</dt><dd class="n">' + (px === null ? '—' : px.toFixed(2)) + '</dd></div>';
      s += '<div><dt>目标股数</dt><dd class="n">' + (planSh > 0 ? money(planSh) + ' 股' : '—') + '</dd></div>';
    }
    s += '</div>';

    if (r['持仓备注']) { s += '<p class="pos__note">' + esc(r['持仓备注']) + '</p>'; }

    s += ladderHtml(r['计划阶梯']);

    s += '<div class="pos-acts">';
    if (link) { s += '<a class="lk" href="' + esc(link) + '" target="_blank" rel="noopener">报告原文 →</a>'; }
    s += '<button class="pbtn" type="button" data-edit="' + esc(recordId(r)) + '">编辑</button>';
    s += '<button class="pbtn pbtn--d" type="button" data-del="' + esc(recordId(r)) + '">删除</button>';
    s += '</div></article>';
    return s;
  }

  function syncPoolState() {
    var holdMap = {}, planMap = {};
    POS.forEach(function (r) {
      if (r['状态'] === '持仓中') { holdMap[r['代码']] = 1; }
      if (r['状态'] === '计划中') { planMap[r['代码']] = 1; }
    });
    IDX.forEach(function (it) {
      var isHold = !!holdMap[it.code];
      it.el.setAttribute('data-pos', isHold ? '1' : '0');
      var old = q('.opb', it.el);
      if (old && old.parentNode) { old.parentNode.removeChild(old); }
      if (!isHold && !planMap[it.code]) { return; }
      var rec = byCode(it.code);
      var tag = document.createElement('span');
      tag.className = 'opb';
      if (isHold && rec) {
        var bits = [];
        if (rec['策略']) { bits.push(rec['策略']); }
        if (num(rec['持仓股数']) > 0) { bits.push(money(num(rec['持仓股数'])) + '股'); }
        if (num(rec['成本价']) > 0) { bits.push('成本' + num(rec['成本价'])); }
        tag.title = bits.join(' · ');
        tag.textContent = '持仓中';
      } else {
        tag.title = '已加入交易计划，待定仓位';
        tag.textContent = '计划中';
      }
      var host = it.card ? q('.zcard__top', it.el) : q('.jd', it.el);
      if (host) { host.appendChild(tag); }
      bind(tag);
    });
  }

  /* ── ④ 持仓编辑表单 ──────────────────────────────────────────────── */
  var FIELDS = [
    ['标的名称', 'fName', 'text', ''],
    ['代码', 'fCode', 'text', '如 603323'],
    ['状态', 'fStatus', 'select', ''],
    ['策略', 'fStrategy', 'select', ''],
    ['持仓股数', 'fShares', 'number', '股'],
    ['计划股数', 'fPlanShares', 'number', '股'],
    ['成本价', 'fCost', 'number', '元'],
    ['成本备注', 'fCostNote', 'text', '如「−12.6%（已锁定）」'],
    ['报告判定', 'fJudge', 'text', '不买 / 持有 / 可小仓试探'],
    ['期望价', 'fExp', 'number', '元'],
    ['观察买点', 'fObs', 'number', '元'],
    ['建仓日', 'fOpen', 'date', ''],
    ['加入日期', 'fAdd', 'date', ''],
    ['报告链接', 'fLink', 'url', 'https://…'],
    ['持仓备注', 'fNote', 'area', '一句话说清这仓的定位与纪律'],
    ['计划阶梯', 'fLadder', 'area', '每行一条：触发价|动作|数量|说明（半角竖线分隔）。例：4.10|加仓|补 1,000 股|回踩第一档']
  ];

  var DRAFT_KEY = 'wl-pos-draft';
  var draftTimer = null;

  function draftCollect() {
    var m = document.getElementById('posMask');
    if (!m) { return null; }
    var o = {};
    qa('input,select,textarea', m).forEach(function (el) {
      var n = el.getAttribute('name');
      if (!n || el.type === 'password' || el.type === 'file' || el.hasAttribute('data-no-cache')) { return; }
      o[n] = el.value;
    });
    return o;
  }

  function draftSaveSoon() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(function () {
      try {
        var o = draftCollect() || {};
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ code: o.fCode || '', fields: o }));
      } catch (e) { /* 静默降级 */ }
    }, 300);
  }

  function draftGet(code) {
    try {
      var raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) { return null; }
      var o = JSON.parse(raw);
      if (!o) { return null; }
      if (o.fields) { return (String(o.code || '') === String(code || '')) ? o.fields : null; }
      return o;
    } catch (e) { return null; }
  }

  function draftClear() {
    try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* 静默降级 */ }
  }

  function closeForm() {
    var m = document.getElementById('posMask');
    if (m && m.parentNode) { m.parentNode.removeChild(m); }
  }

  function fieldHtml(fd, r) {
    var label = fd[0], id = fd[1], type = fd[2], ph = fd[3];
    var v = r ? r[label] : '';
    var wide = (type === 'area');
    var s = '<label class="' + (wide ? 'w2' : '') + '">' + esc(label);
    if (type === 'select') {
      var opts = SCHEMA_OPTIONS[label] || [];
      s += '<select name="' + id + '"><option value="">—</option>';
      opts.forEach(function (o) {
        s += '<option value="' + esc(o.id) + '"' + (String(v || '') === String(o.text) ? ' selected' : '') + '>'
          + esc(o.text) + '</option>';
      });
      s += '</select>';
    } else if (type === 'area') {
      s += '<textarea name="' + id + '" placeholder="' + esc(ph) + '">' + esc(v || '') + '</textarea>';
    } else {
      var val = '';
      if (type === 'date') { val = v ? String(v).slice(0, 10) : ''; }
      else if (type === 'url') { val = urlish(v); }
      else if (type === 'number') { val = (v === null || v === undefined || v === '' || Number(v) === 0) ? '' : v; }
      else { val = (v === null || v === undefined) ? '' : v; }
      s += '<input type="' + (type === 'number' ? 'number" step="any' : type) + '" name="' + id
        + '" value="' + esc(val) + '" placeholder="' + esc(ph) + '">';
    }
    return s + '</label>';
  }

  function openForm(r, seed) {
    if (!db) { flashNote('未连接数据表，无法编辑'); return; }
    closeForm();
    var isNew = !r;
    var src = r || seed || null;
    var code = src ? (src['代码'] || '') : '';
    var mask = document.createElement('div');
    mask.className = 'pos-mask';
    mask.id = 'posMask';
    var f = '<div class="pos-fm" role="dialog" aria-modal="true">';
    f += '<div class="pos-fm__h"><h3>' + (isNew ? '加入持仓计划' : '编辑持仓计划') + '</h3>';
    if (code) { f += '<span class="cd">' + esc(code) + '</span>'; }
    f += '<button class="pos-fm__x" type="button" data-close="1" aria-label="关闭">×</button></div>';
    f += '<div class="pfg">';
    FIELDS.forEach(function (fd) { f += fieldHtml(fd, src); });
    f += '</div>';
    f += '<div class="pos-fm__f"><span class="pos-fm__err" id="posErr"></span><span class="grow"></span>';
    f += '<button class="pbtn" type="button" data-close="1">取消</button>';
    f += '<button class="pbtn pbtn--p" type="button" id="posSave">' + (isNew ? '加入计划' : '保存') + '</button></div>';
    f += '</div>';
    mask.innerHTML = f;
    document.body.appendChild(mask);

    if (isNew) {
      var cached = draftGet(code);
      if (cached) {
        Object.keys(cached).forEach(function (k) {
          var el = mask.querySelector('[name="' + k + '"]');
          if (el && cached[k] !== '') { el.value = cached[k]; }
        });
      }
    }
    mask.addEventListener('input', draftSaveSoon);
    mask.addEventListener('change', draftSaveSoon);

    mask.addEventListener('click', function (e) {
      var el = e.target;
      if (el.getAttribute && el.getAttribute('data-close')) { closeForm(); return; }
      if (el === mask) { closeForm(); }
    });
    document.getElementById('posSave').addEventListener('click', function () { saveForm(r); });
    mask.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { closeForm(); }
    });
    var first = mask.querySelector('input,select,textarea');
    if (first) { first.focus(); }
  }

  function fv(name) {
    var el = document.querySelector('#posMask [name="' + name + '"]');
    return el ? String(el.value || '').trim() : '';
  }

  /* 选项目标文本 → 选项 id（写入 select 时必须用 id，不能用文本） */
  function optId(field, text) {
    var opts = SCHEMA_OPTIONS[field] || [];
    for (var i = 0; i < opts.length; i++) {
      if (String(opts[i].text) === String(text)) { return opts[i].id; }
    }
    return '';
  }

  function buildProps() {
    var p = {};
    p['标的名称'] = { text: fv('fName') };
    p['代码'] = { text: fv('fCode') };
    var st = fv('fStatus') || optId('状态', '计划中');
    if (st) { p['状态'] = { select: st }; }
    var sp = fv('fStrategy') || optId('策略', '待定');
    if (sp) { p['策略'] = { select: sp }; }
    var nums = {
      '持仓股数': 'fShares', '计划股数': 'fPlanShares',
      '成本价': 'fCost', '期望价': 'fExp', '观察买点': 'fObs'
    };
    Object.keys(nums).forEach(function (k) {
      var v = parseFloat(fv(nums[k]));
      p[k] = { number: isNaN(v) ? 0 : v };
    });
    var texts = {
      '成本备注': 'fCostNote', '报告判定': 'fJudge',
      '持仓备注': 'fNote', '计划阶梯': 'fLadder'
    };
    Object.keys(texts).forEach(function (k) { p[k] = { text: fv(texts[k]) }; });
    var lk = fv('fLink');
    if (lk) { p['报告链接'] = { url: { text: '报告原文', link: lk } }; }
    var od = fv('fOpen');
    if (od) { p['建仓日'] = { date: od }; }
    var ad = fv('fAdd');
    if (ad) { p['加入日期'] = { date: ad }; }
    return p;
  }

  function ensureRecordId(r) {
    var rid = recordId(r);
    if (rid) { return Promise.resolve(rid); }
    return fetchAll().then(function (rows) {
      var hit = null;
      rows.forEach(function (x) {
        if (!hit && x['代码'] === r['代码']) { hit = x; }
      });
      return hit ? recordId(hit) : '';
    });
  }

  function saveForm(r) {
    var errEl = document.getElementById('posErr');
    var props = buildProps();
    if (!props['标的名称'].text) {
      if (errEl) { errEl.textContent = '标的名称不能为空'; }
      return;
    }
    var btn = document.getElementById('posSave');
    var keep = btn ? btn.textContent : '保存';
    if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
    var job = r
      ? ensureRecordId(r).then(function (rid) {
          if (!rid) { throw new Error('missing recordId'); }
          return db.updateRecord({ databaseId: DATABASE_ID, recordId: rid, properties: props });
        })
      : db.addRecord({ databaseId: DATABASE_ID, properties: props });
    job.then(function () {
      draftClear();
      closeForm();
      return loadPos();
    }).then(function () {
      flashNote(r ? '已保存修改' : '已加入持仓计划');
    }).catch(function (err) {
      if (window.console) { console.error('[plan] save failed', err); }
      if (errEl) { errEl.textContent = '保存失败，请重试（若反复失败，刷新页面后重试）'; }
      if (btn) { btn.disabled = false; btn.textContent = keep; }
    });
  }

  /* 删除走二次点击确认，不用 window.confirm —— 沙箱 iframe 里 confirm 常被静默拦截 */
  var pendingDel = '', pendingTimer = null;

  function resetDelButtons() {
    qa('[data-del]').forEach(function (b) {
      if (b.getAttribute('data-armed') === '1') {
        b.removeAttribute('data-armed');
        b.textContent = '删除';
        b.classList.remove('pbtn--armed');
      }
    });
    pendingDel = '';
  }

  function delRecord(r, btn) {
    var rid = recordId(r);
    if (pendingDel !== rid) {
      resetDelButtons();
      pendingDel = rid;
      if (btn) {
        btn.setAttribute('data-armed', '1');
        btn.textContent = '确认删除';
        btn.classList.add('pbtn--armed');
      }
      flashNote('再点一次「确认删除」才会删掉「' + (r['标的名称'] || '') + '」');
      clearTimeout(pendingTimer);
      pendingTimer = setTimeout(resetDelButtons, 4000);
      return;
    }
    clearTimeout(pendingTimer);
    pendingDel = '';
    if (btn) { btn.disabled = true; btn.textContent = '删除中…'; }
    ensureRecordId(r).then(function (id) {
      if (!id) { throw new Error('missing recordId'); }
      return db.deleteRecord({ databaseId: DATABASE_ID, recordId: id });
    }).then(function () {
      return loadPos();
    }).then(function () {
      flashNote('已删除');
    }).catch(function (err) {
      if (window.console) { console.error('[plan] delete failed', err); }
      flashNote('删除失败，请刷新页面后重试');
      resetDelButtons();
    });
  }

  /* ── ⑤ 启动 ──────────────────────────────────────────────────────── */
  function markOffline() {
    var host = q('#view-pos .panel__body');
    if (!host) { return; }
    var d = document.createElement('div');
    d.className = 'pos-note-tip';
    d.textContent = '当前打开方式未连上数据表（请在资料库页面中打开台账）：下方为上次发布的快照，'
      + '「加入 / 编辑 / 删除」不可用。';
    host.insertBefore(d, host.firstChild);
    var src = document.getElementById('posSrc');
    if (src) { src.textContent = '快照（未连表）'; }
  }

  function initPos() {
    if (!db) { markOffline(); return; }
    db.getSchema({ databaseId: DATABASE_ID }).then(function (schema) {
      ((schema && schema.properties) || []).forEach(function (fd) {
        if ((fd.type === 'select' || fd.type === 'multi_select') && fd.config && fd.config.options) {
          SCHEMA_OPTIONS[fd.name] = fd.config.options;
        }
      });
    }).catch(function (err) {
      if (window.console) { console.error('[plan] schema failed', err); }
    }).then(function () {
      return loadPos();
    });
  }

  function initPosActions() {
    /* 捕获阶段拦截：避免点到操作按钮时，行点击又触发"滚动到卡片"的既有逻辑 */
    document.addEventListener('click', function (e) {
      var tg = e.target;
      if (!tg || !tg.closest) { return; }
      var ed = tg.closest('[data-edit]');
      if (ed) {
        e.stopPropagation();
        var r1 = byRid(ed.getAttribute('data-edit'));
        if (r1) { openForm(r1); }
        else { flashNote('记录已变化，刷新页面后重试'); }
        return;
      }
      var dl = tg.closest('[data-del]');
      if (dl) {
        e.stopPropagation();
        var r2 = byRid(dl.getAttribute('data-del'));
        if (r2) { delRecord(r2, dl); }
        else { flashNote('记录已变化，刷新页面后重试'); }
      }
    }, true);
  }

  function boot() {
    try {
      buildIndex();
      initPadd();
      initPosActions();
      initPos();
    } catch (err) {
      if (window.console) { console.error('[plan] boot failed', err); }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

