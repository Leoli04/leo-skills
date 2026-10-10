# -*- coding: utf-8 -*-
"""观察池台账 · 数据构建（配置驱动）

从 watchlist_manifest.json 指定的各报告 HTML 中抽取结论字段，产出 ledger_final.json，
并与上期快照（ledger_prev.json）比对生成「变化高亮」标记。

用法：
  python build_watchlist.py --manifest watchlist_manifest.json \
      --out ledger_final.json --prev ledger_prev.json

抽取规则（两条都是实测得出的必要条件，改动前请先看注释）：
  1. 结论横条有两种布局：新版 vb-k/vb-v 键值对；旧版纯文本（「结论：… 加权期望价 … 基于 2026-10-09 盘中价 92.73 元」）。
  2. 同一报告可能出现多个 class="verdict-bar"（CSS 定义、JS 模板、页头副本），
     只有「后接导航栏 class="nav"」的那个是页面真实横条，且取最后一个。
"""
import io
import json
import os
import re
import argparse

NUM = r'(\d+(?:\.\d+)?)'
NAV = 'class="nav"'


def strip(s):
    """HTML → 纯文本。必须先解码实体再剥标签，否则 &lt;div 会在剥标签后变成假标签残留。"""
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                 ('&#39;', "'"), ('&quot;', '"'), ('&#165;', '¥'), ('&yen;', '¥')):
        s = s.replace(a, b)
    s = re.sub(r'(?is)<script.*?</script>', ' ', s)
    s = re.sub(r'(?is)<style.*?</style>', ' ', s)
    s = re.sub(r'(?is)<!--.*?-->', ' ', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'<[^>]*$', ' ', s)          # 段尾恰好切在半个标签中间
    return re.sub(r'\s+', ' ', s).strip()


def num(t):
    m = re.search(NUM, t or '')
    return m.group(1) if m else ''


def parse_bar(raw):
    """返回 (panel, lead, kv, note)。panel 为真实结论横条的纯文本。"""
    best = None
    for m in re.finditer(r'class="(?:verdict-bar|top-verdict)"', raw):
        i = m.start()
        e = raw.find(NAV, i)
        if i < e < i + 9000:
            best = i
    if best is None:
        return None, '', {}, ''
    end = raw.find(NAV, best)
    seg = raw[max(0, best - 120): end]
    lead = re.search(r'class="vb-lead"[^>]*>([^<]*)</', seg)
    kv = {}
    for m in re.finditer(r'class="vb-k"[^>]*>([^<]*)</span>\s*<span class="vb-v[^"]*"[^>]*>([^<]*)</span>', seg, re.S):
        kv.setdefault(strip(m.group(1)), strip(m.group(2)))
    if not kv:
        for m in re.finditer(r'class="tv-badge-k"[^>]*>([^<]*)</\w+>\s*<[^>]*class="tv-badge-val"[^>]*>([^<]*)</\w+>', seg, re.S):
            kv.setdefault(strip(m.group(1)), strip(m.group(2)))
        for m in re.finditer(r'class="tv-badge-val"[^>]*>([^<]*)</\w+>', seg, re.S):
            kv.setdefault('_v%d' % len(kv), strip(m.group(1)))
    note = re.search(r'class="vb-note"[^>]*>([^<]*)</div>', seg, re.S)
    return strip(seg), (strip(lead.group(1)) if lead else ''), kv, (strip(note.group(1)) if note else '')


def pick(kv, *keys):
    """精确键匹配优先，其次前缀匹配。禁止用 'in'（会让「现价」误配「对现价 −1.0%」这类备注键）。"""
    for k in keys:
        for kk, vv in kv.items():
            if kk.strip() == k:
                return vv
    for k in keys:
        for kk, vv in kv.items():
            if kk.strip().startswith(k):
                return vv
    return ''


def extract(path, cat):
    """抽取单份报告的结论字段。"""
    raw = io.open(path, encoding='utf-8', errors='ignore').read()
    panel, lead, kv, note = parse_bar(raw)
    full = strip(raw)
    r = {'cat': cat, 'cur': '元'}
    if cat == 'A':
        if panel is None:
            r['no_bar'] = True
            j = raw.find('id="conclusion"')
            panel = strip(raw[j:j + 3000]) if j > 0 else full[:1200]
        judge = lead or pick(kv, '综合结论') or pick(kv, '结论')
        if not judge and panel:
            for pat in (r'评级\s*[：:]?\s*([^\s\d（(。；]{2,14})',
                        r'结论\s*[：:]?\s*([^\d（(。；]{2,30})'):
                m = re.search(pat, panel)
                if m:
                    judge = m.group(1)
                    break
        if not judge and panel:
            m = re.search(r'(不买|回避|减持|增持|买入|持有|观望|中性[偏积极空谨慎]*)', panel[:160])
            judge = m.group(1) if m else ''
        judge = re.sub(r'^(?:综合)?结论\s*[：:·]?\s*', '', judge).strip()
        judge = re.sub(r'^为', '', judge).strip()
        judge = re.split(r'[；。]', judge)[0]
        if '——' in judge and '，' in judge.split('——', 1)[1]:
            judge = judge.split('——')[0].strip()
        judge = re.split(r'\s+(?=(?:加权期望|折现|合理价值|期望价|买入门槛|目标价|买入胜率|赔率|仓位|评级|R/R))', judge)[0].strip()
        if len(judge) > 28 and '（' in judge:
            judge = judge.split('（')[0].strip()
        judge = re.sub(r'[\s·/、,，;；\-—]+$', '', judge)
        judge = re.sub(r'\s*(?:现价|价格|收盘价|当前价|元|港元)$', '', judge).strip()
        r['judge'] = judge[:30]

        exp = pick(kv, '期望价', '合理价值')
        if not exp and panel:
            m = re.search(r'(?:加权期望折现价|加权期望价|折现期望价|折现后期望价|合理价值|期望价)'
                          r'[^\d]{0,8}[≈约¥]?\s*' + NUM, panel)
            exp = m.group(1) if m else ''
        r['exp'] = num(exp)

        win = pick(kv, '胜率')
        if not win and panel:
            m = re.search(r'(?:买入)?胜率[^\d]{0,6}' + NUM, panel)
            win = m.group(1) if m else ''
        r['win'] = num(win)
        if r['win'].endswith('.0'):
            r['win'] = r['win'][:-2]

        r['obs'] = pick(kv, '观察买点')
        if not r['obs'] and panel:
            m = re.search(r'观察买点[^\d]{0,10}([¥￥]?\s*\d+(?:\.\d+)?(?:\s*[–~\-—]\s*\d+(?:\.\d+)?)?)', panel)
            r['obs'] = m.group(1).replace(' ', '') if m else ''
        r['op'] = pick(kv, '操作')
        if not r['obs'] and r['op']:
            m = re.search(r'(\d+(?:\.\d+)?\s*[–~\-—]\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?)', r['op'])
            r['obs'] = m.group(1).replace(' ', '') if m else ''

        # 现价：严禁把「对现价 −7.85%」或「折现价」误当价格 → 按可信度排序取第一命中
        px = pick(kv, '当前价', '现价')
        if not px and panel:
            for pat in (r'基于\s*\d{4}-\d{2}-\d{2}[^0-9]{0,12}' + NUM,
                        NUM + r'\s*现价（元）',
                        r'(?<!折)现价\s*[（(]?\s*' + NUM + r'\s*(?:元|港元)',
                        r'收盘价\s*[（(]?\s*(?:\d{4}-\d{2}-\d{2}\s*[）)]\s*)?' + NUM):
                m = re.search(pat, panel)
                if m:
                    px = m.group(1)
                    break
        if not px and note:
            m = re.search(r'收盘\s*[价]?\s*' + NUM, note)
            px = m.group(1) if m else ''
        if not px:
            m = re.search(NUM + r'\s*现价（元）', full[:5000])
            px = m.group(1) if m else ''
        r['px'] = num(px)

        if '港元' in (panel or ''):
            r['cur'] = '港元'
        m = re.search(r'有效期至\s*([^·。；<]{3,30})', (note or '') + ' ' + (panel or ''))
        r['valid'] = m.group(1).strip() if m else ''
        m = re.search(r'(\d{4}-\d{2}-\d{2})', (note or '') + ' ' + (panel or ''))
        r['asof'] = m.group(1) if m else ''
    else:
        head = full[:1500]
        j = (re.search(r'投资评级\s*[：:]\s*([^\s。，,；;（(]{2,14})', head)
             or re.search(r'评级\s*[：:]\s*([^\s。，,；;（(]{2,14})', head)
             or re.search(r'(中性偏积极|中性偏空|中性偏谨慎|中性|减持|增持|买入|回避|观望|持有)', head))
        r['judge'] = j.group(1) if j else ''
        m = re.search(r'目标价\s*[约为]*\s*' + NUM, head)
        r['target'] = m.group(1) if m else ''
        m = re.search(r'(?:现价|最新价|收盘价)\s*[约为]*\s*' + NUM, head)
        r['px'] = m.group(1) if m else ''
        r.update({'exp': '', 'win': '', 'obs': '', 'op': '', 'valid': ''})
    return r


def bucket(j):
    """三桶：N 不买/回避 · S 减持 · H 其余。

    分两步，缺一不可：
      1) 先按「判定首词」归类（首词 = 去掉 / · （ 等分隔符之前的部分），
         这样「持有 / 观望（暂不买入）」括号里的否定词不会把 H 误判成 N。
      2) 首词内部再找第一个命中的结论词。若只做第 1 步，
         「当前价位回避新建仓」这类把结论词放在句中的写法会因首字不是「回/不」
         而被归入 H 桶，出现「标签写回避、桶却是持有」的自相矛盾（2026-10-09 荣昌生物实测）。
    注意：只在首词内部检索，不能扩到全串 —— 否则「HOLD（不新增 / 逢高减持）」
    会被括号里的「减持」误判为 S，「中性偏空 · 观望（回避追高）」也会被误判为 N。
    """
    j = (j or '').strip()
    head = re.split(r'[/·（(，,、]', j)[0].strip()
    if re.match(r'^(不买|回避)', head):
        return 'N'
    if '减持' in head:
        return 'S'
    m = re.search(r'(不买入|不买|回避|减持|持有|观望|中性)', head)
    if m:
        kw = m.group(1)
        if kw in ('不买入', '不买', '回避'):
            return 'N'
        if kw == '减持':
            return 'S'
    return 'H'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--root', default='')
    ap.add_argument('--out', default='ledger_final.json')
    ap.add_argument('--prev', default='')
    a = ap.parse_args()

    man = json.load(io.open(a.manifest, encoding='utf-8'))
    root = a.root or man.get('report_root', '')
    fresh_from = man.get('fresh_from', '')

    rows = []
    warns = []
    for it in man['reports']:
        p = it['file'] if os.path.isabs(it['file']) else os.path.join(root, it['file'])
        if not os.path.isfile(p):
            warns.append('缺文件: %s %s' % (it['code'], it['file']))
            continue
        r = extract(p, it.get('cat', 'A'))
        r.update({'code': it['code'], 'name': it['name'],
                  'date': it.get('report_date', ''), 'url': it.get('lib_url', '')})
        for k, v in (it.get('overrides') or {}).items():
            r[k] = v
        for k in ('exp', 'win', 'px', 'obs', 'target', 'op'):
            r[k] = (r.get(k) or '').strip()
            if k in ('exp', 'win', 'px', 'target'):
                r[k] = re.sub(r'[≈约¥￥\s]', '', r[k])
            if k == 'obs':
                r[k] = re.split(r'[（(]', r[k])[0].strip()
        r['exp_n'] = r['exp'] if re.fullmatch(r'\d+(\.\d+)?', r['exp']) else ''
        r['px_n'] = r['px'] if re.fullmatch(r'\d+(\.\d+)?', r['px']) else ''
        r['updown'] = (round((float(r['exp_n']) / float(r['px_n']) - 1) * 100, 1)
                       if r['exp_n'] and r['px_n'] and float(r['px_n']) else None)
        r['fresh'] = 1 if (fresh_from and r['date'] >= fresh_from) else 0
        r['bucket'] = bucket(r.get('judge', ''))
        rows.append(r)

    prev = {}
    if a.prev and os.path.isfile(a.prev):
        prev = {x['code']: x for x in json.load(io.open(a.prev, encoding='utf-8'))}
    for r in rows:
        p = prev.get(r['code'])
        r['chg'] = ''
        if p:
            t = []
            if p.get('judge') != r['judge']:
                t.append('判定变化')
            if (p.get('exp_n') or '') != (r['exp_n'] or ''):
                t.append('期望价变化')
            if (p.get('win') or '') != (r['win'] or ''):
                t.append('胜率变化')
            r['chg'] = ' / '.join(t)
            r['prev_judge'] = p.get('judge', '')

    rank = {'N': 0, 'H': 1, 'S': 2}
    rows.sort(key=lambda r: r['date'], reverse=True)
    rows.sort(key=lambda r: rank[r['bucket']])

    txt = json.dumps(rows, ensure_ascii=False, indent=1)
    io.open(a.out, 'w', encoding='utf-8').write(txt)
    if a.prev:
        io.open(a.prev, 'w', encoding='utf-8').write(txt)

    cnt = {'N': 0, 'H': 0, 'S': 0}
    for r in rows:
        cnt[r['bucket']] += 1
    print('标的', len(rows), '| 不买/回避', cnt['N'], '| 中性/持有', cnt['H'], '| 减持', cnt['S'])
    print('无判定:', [r['name'] for r in rows if not r['judge']])
    print('A类缺现价:', [r['name'] for r in rows if r['cat'] == 'A' and not r['px_n']])
    print('缺原文链接:', [r['name'] for r in rows if not r['url']])
    print('无结论横条(需人工核对):', [r['name'] for r in rows if r.get('no_bar')])
    for w in warns:
        print('!', w)


if __name__ == '__main__':
    main()
