# -*- coding: utf-8 -*-
"""观察池台账 · 现价刷新（实时行情叠加）

用法：
  python refresh_prices.py --ledger ledger_final.json --out ledger_live.json \
      [--asof "2026-10-12 11:05"]

职责边界（与 build_watchlist.py 的分工）：
  · build_watchlist.py 负责「报告 → ledger」：判定 / 期望价 / 胜率 / 观察买点 / 报告日 / 原文链接，
    全部取自报告原文，是台账的存量口径。
  · 本脚本负责「ledger → 实时现值」：只把 px / px_n 换成实时行情，并记下行情时点。
    潜在空间（updown）与距买点（gap）由 render_watchlist.py 的 enrich() 按新 px 重算，
    因此这里必须同步刷新 updown，否则与渲染结果不一致。

口径红线：期望价、买入胜率、观察买点**不得**随现价改动 —— 它们锚定在报告写作时的基准价上。
页面已在页头标注「现价时点」并把胜率列标注为「报告口径」，以显式呈现这一时点差。

行情源：腾讯 qt.gtimg.cn（GBK），字段 [3]=现价、[32]=涨跌幅%。
"""
import argparse
import io
import json
import ssl
import time
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
ssl._create_default_https_context = ssl._create_unverified_context


def tx_code(code):
    """代码 → (腾讯代码, 币种)。港股 5 位；北交所 920xxx 用 bj 前缀。"""
    c = code.split('.')[0]
    if len(c) == 5:
        return 'hk' + c, '港元'
    if c.startswith('6'):
        return 'sh' + c, '元'
    if c.startswith(('0', '3')):
        return 'sz' + c, '元'
    if c.startswith('9'):
        return 'bj' + c, '元'
    return 'sh' + c, '元'


def fetch_quotes(codes):
    """批量拉取（每批 50），返回 {腾讯代码: [字段...]}。"""
    out = {}
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        url = 'http://qt.gtimg.cn/q=' + ','.join(batch)
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        for line in raw.decode('gbk', 'ignore').split(';'):
            line = line.strip()
            if not line or '=' not in line:
                continue
            out[line.split('=')[0].replace('v_', '').strip()] = \
                line.split('=', 1)[1].strip().strip('"').split('~')
        time.sleep(0.3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ledger', default='ledger_final.json')
    ap.add_argument('--out', default='ledger_live.json')
    ap.add_argument('--asof', default='')
    ap.add_argument('--dry', action='store_true', help='只打印不写文件')
    a = ap.parse_args()

    rows = json.load(io.open(a.ledger, encoding='utf-8'))
    txcodes = {r['code']: tx_code(r['code']) for r in rows}
    quotes = fetch_quotes(sorted({v[0] for v in txcodes.values()}))

    miss, changed = [], []
    for r in rows:
        txc, cur = txcodes[r['code']]
        f = quotes.get(txc)
        if not f or len(f) < 33 or not f[3]:
            miss.append('%s %s' % (r['code'], r['name']))
            continue
        old_px = r.get('px_n') or ''
        r['px'] = f[3]
        r['px_n'] = f[3]
        r['px_chg'] = f[32]                       # 当日涨跌幅 %
        r['px_prev'] = old_px                      # 报告基准价，留痕
        try:
            r['updown'] = round((float(r['exp_n']) / float(f[3]) - 1) * 100, 1) \
                if r.get('exp_n') else None
        except (ValueError, ZeroDivisionError):
            r['updown'] = None
        if old_px and old_px != f[3]:
            changed.append('%s %s %s→%s (%s%%)'
                           % (r['code'], r['name'], old_px, f[3], f[32]))

    if a.asof:
        for r in rows:
            r['px_asof'] = a.asof

    print('标的 %d | 取到行情 %d | 缺行情 %d | 现价变动 %d'
          % (len(rows), len(rows) - len(miss), len(miss), len(changed)))
    if miss:
        print('! 缺行情:', miss)
    if changed:
        print('现价变动明细:')
        for x in changed:
            print('   ', x)

    if a.dry:
        return
    json.dump(rows, io.open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('written', a.out)


if __name__ == '__main__':
    main()
