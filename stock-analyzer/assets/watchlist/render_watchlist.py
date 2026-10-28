# -*- coding: utf-8 -*-
"""观察池台账 · 决策驾驶舱渲染（v2）

用法：
  python render_watchlist.py --data ledger_final.json \
      --out "投资观察池台账-YYYYMMDD.html" --asof 2026-10-09 --prev-cutoff "本轮新增"

v1 -> v2 的四处根因改造（均针对「无法一眼做决策」这一根因）：
  1. 语义色解耦：v1 里 #c62828 同时表示「回避」和「下跌」，红绿被两套语义抢占。
     v2 把红绿收敛为经济语义唯一载体（红=潜在空间为正，A 股惯例），
     判定改用 slate / indigo / amber 三色，色相完全避开红绿。
  2. 信息架构重排：v1 把 51 行按「不买(32) → 中性(18) → 减持(1)」平铺，
     真正有正空间的 5 只被压在 32 行名单中。v2 改为
     结论条 → KPI → 全池总览 → 四分区（A 卡片 / BCD 表格）→ 复核时间轴。
  3. 可视编码：潜在空间由「±% 文本」升级为 0 轴居中双色条；
     胜率由裸数字升级为五格点阵；新增派生字段「距买点」（买点上界 ÷ 现价 − 1）。
  4. 设计 token 化：颜色/字号/间距/圆角/阴影全部变量化，
     字号由 v1 的 7 档（13/12.5/12/11.5/11/10.5/10）收敛为 6 档。

渲染约定（与 v1 一致，不得违反）：
  · 涨用红、跌用绿；不使用任何 CDN / 外链资源，样式与脚本全部内联，双击即可打开。
  · 数值一律取自 ledger_final.json，不在渲染层做估算。
"""
import io
import json
import os
import re
import argparse
from html import escape

# ── 潜在空间条的取值窗口（超出即裁剪），0 轴位置由窗口推导 ──────────────
SPACE_MIN, SPACE_MAX = -65.0, 20.0
SPACE_SPAN = SPACE_MAX - SPACE_MIN          # 85
ZERO_PCT = (-SPACE_MIN) / SPACE_SPAN * 100  # 76.47%

# ── 判定三桶（色相刻意避开红/绿）──────────────────────────────────────
BUCKET = {
    'N': ('tag--n', '回避 / 不买'),
    'H': ('tag--h', '持有 / 观察'),
    'S': ('tag--s', '减持'),
}

ZONE_META = [
    ('A', 'A', '贴近买点', '期望价高于现价（潜在空间 ≥ 0）；仍需回调至观察买点',
     '上行空间为正，但胜率均低于 30%，尚不构成建仓信号。'),
    ('H', 'B', '持有观察', '判定为持有 / 中性，当前不新增买入',
     '已给出的期望价均低于现价；等待复核时点验证后再定。'),
    ('N', 'C', '回避 / 不买', '期望价低于现价，或未达建仓门槛',
     '占全池多数，是本轮扫描的排除结果，保留跟踪价值。'),
    ('S', 'D', '减持', '报告给出减仓 / 减持结论',
     None),
]

# ── 结语文案模板（2026-10-23 立）─────────────────────────────────────────
# 页内「刷新现价」要重算结语，若 JS 里另写一套措辞，两处必然漂移。
# 故文案只在此定义一次：Python 用 .format() 渲染首屏，同一份模板串也塞进页面
# （wl-model.tpl），JS 只做数字替换，不持有任何文字。
V_T_PASS = ('覆盖 <b>{n}</b> 只标的，其中 <b>{nq}</b> 只具备量化期望价。'
            '<span class="hl-up">{npos} 只</span>期望价高于现价（正空间），'
            '且其中 <span class="hl-up">{npass} 只</span>同时满足'
            '「潜在空间 ≥ +15% 且胜率 ≥ 30%」的建仓门槛。')
V_T_ZERO = ('覆盖 <b>{n}</b> 只标的，其中 <b>{nq}</b> 只具备量化期望价。'
            '<span class="hl-up">{npos} 只</span>期望价高于现价（正空间），'
            '但 <b>0 只</b>同时满足「潜在空间 ≥ +15% 且胜率 ≥ 30%」的建仓门槛；{tail}'
            '<b>当前观察池无一只达到建仓标准。</b>')
V_T_TAIL0 = '{nw30} 只胜率 ≥ 30%，但其期望价均低于现价。'
V_T_TAIL1 = ('{nw30} 只胜率 ≥ 30%，其中 {nw30pos} 只期望价高于现价，'
             '但仍未同时达到 +15% 门槛。')
V_T_HINT_P = '其中 {npass} 只同时达标'
V_T_HINT_P0 = '正空间，但胜率均 &lt; 30%'
V_T_HINT_W = '其中 {nw30pos} 只期望价高于现价'
V_T_HINT_W0 = '期望价均低于现价'
Z_T_DESC_IN = '期望价高于现价（潜在空间 ≥ 0）；其中 {nin} 只现价已进入观察买点区间'
Z_T_DESC_OUT = '期望价高于现价（潜在空间 ≥ 0）；尚未进入观察买点区间'
Z_T_DESC_NEG = '；另有 {nneg} 只空间已转负（分区为快照口径，需重渲台账重新分区）'
Z_T_DESC_GAIN = '；另有 {ngain} 只空间已转正、但仍列在下方分区（同上，需重渲台账重新分区）'
Z_T_NOTE_OK = ('上行空间为正；其中 {nok} 只同时满足「潜在空间 ≥ +15% 且胜率 ≥ 30%」的建仓门槛，'
               '另有 {rest} 只胜率达标但空间未达门槛。仍须回到报告原文逐个核验证点。')
Z_T_NOTE_HI = ('上行空间为正，且已有 {nhi} 只胜率 ≥ 30%，但空间均未达 +15% 门槛，'
               '尚不构成建仓信号。')
Z_T_NOTE_NO = '上行空间为正，但胜率均低于 30%，尚不构成建仓信号。'
SP_T_FOOT = ('0 轴右侧为「期望价高于现价」；建仓门槛为潜在空间 ≥ +15% 且胜率 ≥ 30%，'
             '<b class="hl-up">本轮 {npass} 只达标</b>。分档左闭右开，如 −5.0% 计入「−5 ~ 0」档。')
SP_T_FOOT0 = ('0 轴右侧为「期望价高于现价」；建仓门槛为潜在空间 ≥ +15% 且胜率 ≥ 30%'
              '（本轮 0 只达标）。分档左闭右开，如 −5.0% 计入「−5 ~ 0」档。')
MX_T_FOOT = ('右上角（高胜率 × 正空间）<b class="hl-up">有 {hi} 只</b> —— '
             '即全池存在「胜率与赔率同时达标」的标的，见各区名单。')
MX_T_FOOT0 = '右上角（高胜率 × 正空间）为空 —— 即全池不存在「胜率与赔率同时达标」的标的。'

TPL_BAG = {
    'vpass': V_T_PASS, 'vzero': V_T_ZERO, 'vtail0': V_T_TAIL0, 'vtail1': V_T_TAIL1,
    'hintp': V_T_HINT_P, 'hintp0': V_T_HINT_P0, 'hintw': V_T_HINT_W, 'hintw0': V_T_HINT_W0,
    'zdesc_in': Z_T_DESC_IN, 'zdesc_out': Z_T_DESC_OUT, 'zdesc_neg': Z_T_DESC_NEG,
    'zdesc_gain': Z_T_DESC_GAIN,
    'znote_ok': Z_T_NOTE_OK, 'znote_hi': Z_T_NOTE_HI, 'znote_no': Z_T_NOTE_NO,
    'spfoot': SP_T_FOOT, 'spfoot0': SP_T_FOOT0, 'mxfoot': MX_T_FOOT, 'mxfoot0': MX_T_FOOT0,
}


# ── 基础工具 ──────────────────────────────────────────────────────────
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def fmt_pct(v):
    """带符号百分比；用 ASCII 负号以保证等宽字体下对齐。"""
    if v is None:
        return '—'
    sign = '+' if v > 0 else ('-' if v < 0 else '')
    return '%s%.1f%%' % (sign, abs(v))


def parse_obs(s):
    """从「≈ 115–123 港元」「≤ 110 元」「17–19」中取 (下界, 上界)。

    上界即「需跌到该价才算进入买点」的阈值。
    """
    if not s:
        return None, None
    t = re.sub(r'[港元元¥￥\s]', '', s)
    nums = re.findall(r'\d+(?:\.\d+)?', t)
    if not nums:
        return None, None
    vals = [float(x) for x in nums]
    return min(vals), max(vals)


def px_secid(code):
    """台账代码 → 腾讯行情 secid。页内「刷新现价」按钮用它拼请求，
    JS 侧有一份同规则的镜像实现（secid()），改动须两处同步。

    前缀实测（2026-10-23）：沪 sh600415 / 深 sz000538 / 港 hk01810 / 北 bj920429
    全部可用，返回 `v_<secid>="…"` 形式的 JS 赋值，当普通 script 标签加载即绕过 CORS。
    """
    c = (code or '').strip().upper()
    if c.endswith('.HK'):
        return 'hk' + re.sub(r'\D', '', c).zfill(5)
    d = re.sub(r'\D', '', c)
    if not d:
        return ''
    if d.startswith('920') or d[0] in '48':
        return 'bj' + d
    if d[0] in '69':
        return 'sh' + d
    return 'sz' + d


def bucket_of(judge):
    head = re.split(r'[/·（(，,、]', judge or '')[0].strip()
    if re.match(r'^(不买|回避)', head):
        return 'N'
    if '减持' in head:
        return 'S'
    return 'H'


# 判定标签文字：取报告结论的首个结论词（不是三桶名），底色仍按三桶着色。
# 只用三桶名会让「中性偏空」和「持有 / 中性偏积极」显示成同一个标签，丢失原文差异。
TAG_HEADS = ('不买入', '不买', '回避', '减持', '增持', '买入',
             '中性偏积极', '中性偏空', '中性偏谨慎', '中性',
             '持有', '观望', 'HOLD', 'BUY', 'SELL')


def tag_text(judge, bkt):
    j = re.sub(r'\s+', '', judge or '')
    for k in TAG_HEADS:
        if j.startswith(k):
            return k
    for k in TAG_HEADS:
        if k in j:
            return k
    head = re.split(r'[/·（(，,、]', j)[0]
    if len(head) > 7:
        return head[:7] + '…'
    return head or BUCKET[bkt][1]


def enrich(r):
    """在原始抽取结果上补派生字段，渲染层只读这些字段。"""
    px, exp = _f(r.get('px_n')), _f(r.get('exp_n'))
    r['px_v'], r['exp_v'] = px, exp
    up = None
    if px and exp:
        up = round((exp / px - 1) * 100, 1)
    r['up'] = up

    w = str(r.get('win') or '').strip()
    r['win_v'] = int(w) if re.fullmatch(r'\d+', w) else None

    lo, hi = parse_obs(r.get('obs'))
    r['obs_lo'], r['obs_hi'] = lo, hi
    r['gap'] = round((hi / px - 1) * 100, 1) if (hi and px) else None

    b = r.get('bucket') or bucket_of(r.get('judge'))
    r['bkt'] = b
    r['pos'] = 1 if (up is not None and up >= 0) else 0
    r['zone'] = 'A' if r['pos'] else b

    r['target_v'] = _f(r.get('target'))
    r['search'] = ' '.join(str(r.get(k, '')) for k in ('name', 'code', 'judge', 'obs', 'alert'))
    return r


# ── 片段渲染 ──────────────────────────────────────────────────────────
def h_space(v, big=False):
    """0 轴居中的潜在空间条。data-f="bar" 供页内刷新按新现价重绘几何。"""
    cls = 'sb--lg' if big else ''
    if v is None:
        return ('<div class="sb sb--na %s" data-f="bar"><i class="sb__z" '
                'style="left:%.2f%%"></i></div>' % (cls, ZERO_PCT))
    c = max(SPACE_MIN, min(SPACE_MAX, v))
    if c >= 0:
        left, width, tone = ZERO_PCT, c / SPACE_SPAN * 100, ('is-up' if c > 0 else 'is-flat')
    else:
        width = (-c) / SPACE_SPAN * 100
        left, tone = ZERO_PCT - width, 'is-down'
    return ('<div class="sb %s" data-f="bar"><i class="sb__z" style="left:%.2f%%"></i>'
            '<span class="sb__b %s" style="left:%.2f%%;width:%.2f%%"></span></div>'
            % (cls, ZERO_PCT, tone, left, max(width, 1.0)))


def h_space_cell(v):
    tone = 'is-up' if (v or 0) > 0 else ('is-down' if (v or 0) < 0 else 'is-flat')
    num = ('<span class="sp__n %s" data-f="up" data-fb="sp__n">%s</span>'
           % (tone, fmt_pct(v)))
    return '<div class="sp">%s%s</div>' % (num, h_space(v))


def h_win(w):
    if w is None:
        return '<div class="win"><span class="dim">—</span></div>'
    tier = 'low' if w < 30 else ('mid' if w < 50 else 'high')
    filled = max(0, min(5, int(round(w / 20.0))))
    dots = ''.join('<i class="%s"></i>' % ('on' if i < filled else '') for i in range(5))
    label = '低' if w < 30 else ('中' if w < 50 else '高')
    return ('<div class="win win--%s"><div class="dots">%s</div>'
            '<span class="win__n n">%d%%</span><span class="win__t">%s</span></div>'
            % (tier, dots, w, label))


def h_gap(g):
    """data-f="gap" / data-fb="gp"：刷新时按新现价重算「距买点」。
    表内用 gp 样式（负值为等宽数字、跨过 0 变「已在区间」）。"""
    if g is None:
        return '<span class="dim" data-f="gap" data-fb="">—</span>'
    if g >= 0:
        return '<span class="gp is-up" data-f="gap" data-fb="gp">已在区间</span>'
    return '<span class="gp is-wait n" data-f="gap" data-fb="gp">%s</span>' % fmt_pct(g)


def h_price(r):
    """价格带「现价 → 期望价」。现价 span 打 data-f="px"，期望价为报告口径、
    刷新时不动（打 data-f="exp" 只作定位，不参与重算）。"""
    px = r.get('px') or r.get('px_n') or '—'
    if r['exp_v'] is not None:
        exp = escape(str(r.get('exp_n') or r.get('exp') or ''))
        return ('<span class="pb"><span class="pb__c n" data-f="px" data-fb="pb__c n">%s</span>'
                '<span class="pb__a">→</span><span class="pb__e n" data-f="exp">%s</span></span>'
                % (escape(str(px)), exp))
    if r['target_v'] is not None:
        return ('<span class="pb"><span class="pb__c n" data-f="px" data-fb="pb__c n">%s</span>'
                '<span class="pb__a">·</span><span class="pb__t n">机构目标 %s</span></span>'
                % (escape(str(px)), escape(str(r.get('target')))))
    return ('<span class="pb"><span class="pb__c n" data-f="px" data-fb="pb__c n">%s</span></span>'
            % escape(str(px)))


def h_link(r):
    if not r.get('url'):
        return '<span class="dim">—</span>'
    return '<a class="lk" href="%s" target="_blank" rel="noopener">原文</a>' % escape(r['url'])


def op_badge_html(op, held=False, pos=None):
    """观察池持仓徽标：manifest positions 中的标的固定标「持仓中」（tooltip 带摘要）；
    非持仓标的保留报告「操作」字段的压缩文案口径（如贵州茅台的「持有中」）。

    held 时 tooltip **由 positions 现算**（股数 / 成本 / 策略），不再读报告里的 op 字段——
    op 是报告写作时的历史口径，减仓或改成本后不会自动更新，曾出现「5500股·成本4.45」
    与台账「2500股·成本4.28」并存的分叉。"""
    o = (op or '').strip()
    if held:
        if pos:
            sh = pos.get('shares')
            st = (pos.get('strategy') or '').strip()
            if pos.get('cost') is not None:
                core = '%s股 · 成本%g' % (sh, pos['cost'])
            else:
                core = '%s股 · %s' % (sh, (pos.get('cost_label') or '—').replace('\u00a0', ' '))
            tip = core + ('（%s）' % st if st else '')
        else:
            tip = o if o else '持仓中'
        return '<span class="opb" title="%s">持仓中</span>' % escape(tip, quote=True)
    if not o:
        return ''
    if len(o) <= 8:
        lab = o
    elif '建仓' in o:
        lab = '建仓中'
    elif '持有' in o:
        lab = '持有中'
    elif '减仓' in o or '减持' in o:
        lab = '减持中'
    else:
        head = re.split(r'[；;，,。/（(（\s]', o)[0]
        lab = head[:8] + ('…' if len(head) > 8 else '')
    return '<span class="opb" title="%s">%s</span>' % (escape(op, quote=True), escape(lab))


def row_html(r, idx):
    tcls, _ = BUCKET[r['bkt']]
    attrs = (
        'data-row data-b="%s" data-zone="%s" data-pos="%d" data-fresh="%d" '
        'data-up="%s" data-win="%s" data-gap="%s" data-k="%s" '
        'data-code="%s" data-e="%s" data-hi="%s"'
        % (r['bkt'], r['zone'], r['pos'], int(r.get('fresh') or 0),
           '' if r['up'] is None else r['up'],
           '' if r['win_v'] is None else r['win_v'],
           '' if r['gap'] is None else r['gap'],
           escape(r['search'], quote=True),
           escape(str(r['code']), quote=True),
           '' if r['exp_v'] is None else r['exp_v'],
           '' if r.get('obs_hi') is None else r['obs_hi'])
    )
    fresh = ' is-fresh' if r.get('fresh') else ''
    chg = ''
    if r.get('chg'):
        chg = '<span class="chg" title="上期判定：%s">%s</span>' % (
            escape(str(r.get('prev_judge') or '')), escape(r['chg']))
    judge_note = escape(r.get('judge') or '')[:46]
    cut = '…' if len(r.get('judge') or '') > 46 else ''
    al_txt = str(r.get('alert') or '').strip()
    al_html = ('<span class="al" title="%s">行情更新</span>'
               % escape(al_txt, quote=True)) if al_txt else ''
    op = r.get('op') or ''
    op_attr = ' title="%s"' % escape(op, quote=True) if op else ''
    op_badge = op_badge_html(op, bool(r.get('_held')), r.get('_pos'))
    return (
        '<tr%s %s><td class="idx n"></td>'
        '<td class="nm"><b>%s</b><span class="cd">%s</span></td>'
        '<td class="jd"><span class="tag %s">%s</span>'
        '<span class="jd__n">%s%s</span>%s%s%s</td>'
        '<td class="ta-r">%s</td>'
        '<td>%s</td>'
        '<td class="ta-c">%s</td>'
        '<td class="ta-r"%s>%s</td>'
        '<td class="ta-c dt n">%s</td>'
        '<td class="ta-c">%s</td></tr>'
        % (fresh, attrs, escape(r['name']), escape(r['code']), tcls, escape(tag_text(r.get('judge'), r['bkt'])),
           judge_note, cut, chg, al_html, op_badge,
           h_price(r), h_space_cell(r['up']), h_win(r['win_v']),
           op_attr, h_gap(r['gap']), escape(r.get('date') or '—'), h_link(r))
    )


def card_html(r):
    tcls, _ = BUCKET[r['bkt']]
    tone = 'is-up' if (r['up'] or 0) >= 0 else 'is-down'
    attrs = (
        'data-row data-b="%s" data-zone="%s" data-pos="%d" data-fresh="%d" '
        'data-up="%s" data-win="%s" data-gap="%s" data-k="%s" '
        'data-code="%s" data-e="%s" data-hi="%s"'
        % (r['bkt'], r['zone'], r['pos'], int(r.get('fresh') or 0),
           '' if r['up'] is None else r['up'],
           '' if r['win_v'] is None else r['win_v'],
           '' if r['gap'] is None else r['gap'],
           escape(r['search'], quote=True),
           escape(str(r['code']), quote=True),
           '' if r['exp_v'] is None else r['exp_v'],
           '' if r.get('obs_hi') is None else r['obs_hi'])
    )
    win_txt = ('%d%%' % r['win_v']) if r['win_v'] is not None else '—'
    gap_txt = '—' if r['gap'] is None else ('已在区间' if r['gap'] >= 0 else '需回调 %.1f%%' % abs(r['gap']))
    exp_txt = ('%.2f' % r['exp_v']) if r['exp_v'] is not None else '—'
    px_txt = r.get('px_n') or r.get('px') or '—'
    al_txt = str(r.get('alert') or '').strip()
    al_html = ('<div class="zcard__alert"><b>行情更新 · 报告出具后</b>%s</div>'
               % escape(al_txt)) if al_txt else ''
    fresh_cls = ' is-fresh' if r.get('fresh') else ''
    op = r.get('op') or ''
    op_badge = op_badge_html(op, bool(r.get('_held')), r.get('_pos'))
    return (
        '<article class="zcard%s" %s>'
        '<div class="zcard__top"><span class="zcard__idx n"></span>'
        '<div class="zcard__id"><b>%s</b><span class="cd">%s</span></div>'
        '<span class="tag %s">%s</span>%s</div>'
        '<div class="zcard__hero"><div class="zh__v %s n" data-f="up" data-fb="zh__v n">%s</div>'
        '<div class="zh__l">潜在空间 <span class="dim">= 期望价 ÷ 现价 − 1</span></div>%s</div>'
        '<div class="zcard__kv">'
        '<div><dt>现价 → 期望价</dt><dd class="n"><span data-f="px" data-fb="">%s</span> '
        '<span class="pb__a">→</span> <span data-f="exp">%s</span></dd></div>'
        '<div><dt>买入胜率</dt><dd class="n">%s</dd></div>'
        '<div><dt>距观察买点</dt><dd data-f="gap" data-fb="zcard__gap">%s</dd></div>'
        '<div><dt>报告日期</dt><dd class="n">%s</dd></div>'
        '</div>'
        '%s'
        '<p class="zcard__j">%s</p>'
        '%s</article>'
        % (fresh_cls, attrs, escape(r['name']), escape(r['code']), tcls, escape(tag_text(r.get('judge'), r['bkt'])), op_badge,
           tone, fmt_pct(r['up']), h_space(r['up'], big=True),
           escape(str(px_txt)), escape(exp_txt), win_txt, gap_txt,
           escape(r.get('date') or '—'), al_html, escape(r.get('judge') or ''),
           ('<a class="lk zcard__lk" href="%s" target="_blank" rel="noopener">查看报告原文 →</a>'
            % escape(r['url'])) if r.get('url') else '')
    )


THEAD = (
    '<thead><tr><th class="c-idx">#</th><th class="c-nm">标的</th>'
    '<th class="c-jd">当前判定</th>'
    '<th class="c-px ta-r">价格带　现价 → 期望价</th>'
    '<th class="c-sp">潜在空间 <span class="th-h">0 轴居中</span></th>'
    '<th class="c-win ta-c">@@WIN_TH@@</th>'
    '<th class="c-gp ta-r">距买点</th>'
    '<th class="c-dt ta-c">报告日</th>'
    '<th class="c-lk ta-c">原文</th></tr></thead>'
)

COLGROUP = (
    '<colgroup><col style="width:34px"><col style="width:148px"><col style="width:196px">'
    '<col style="width:150px"><col style="width:184px"><col style="width:118px">'
    '<col style="width:96px"><col style="width:92px"><col style="width:58px"></colgroup>'
)


def zone_table(rows_):
    body = ''.join(row_html(r, i) for i, r in enumerate(rows_))
    return ('<div class="tw"><table class="wl">%s%s<tbody>%s</tbody></table></div>'
            % (COLGROUP, THEAD, body))


def _zoneA_text(rows_):
    """A 区结语按数据生成 —— 现价一变，达标数与「是否已进买点区间」都会变，
    写死文案会与图表自相矛盾（2026-10-12 现价刷新时实测踩到）。
    文案模板与页内 JS 共用 TPL_BAG，刷新时 JS 只换数字不换措辞。"""
    n_ok = sum(1 for r in rows_ if r['up'] is not None and r['up'] >= 15
               and r['win_v'] is not None and r['win_v'] >= 30)
    n_hi = sum(1 for r in rows_ if r['win_v'] is not None and r['win_v'] >= 30)
    n_in = sum(1 for r in rows_ if r['gap'] is not None and r['gap'] >= 0)
    n_neg = sum(1 for r in rows_ if r['up'] is not None and r['up'] < 0)
    desc = (Z_T_DESC_IN.format(nin=n_in) if n_in else Z_T_DESC_OUT)
    if n_neg:
        desc += Z_T_DESC_NEG.format(nneg=n_neg)
    if n_ok:
        note = Z_T_NOTE_OK.format(nok=n_ok, rest=n_hi - n_ok)
    elif n_hi:
        note = Z_T_NOTE_HI.format(nhi=n_hi)
    else:
        note = Z_T_NOTE_NO
    return desc, note


def zone_block(zone, rows_):
    _, letter, title, desc, note = next(z for z in ZONE_META if z[0] == zone)
    if zone == 'A':
        desc, note = _zoneA_text(rows_)
    body = ('<div class="zcards">%s</div>' % ''.join(card_html(r) for r in rows_)) \
        if zone == 'A' else zone_table(rows_)
    note_html = ('<div class="zone__note" data-agg="znote">%s</div>' % escape(note)) if note else ''
    dattr = ' data-agg="zdesc"' if zone == 'A' else ''
    return (
        '<section class="zone zone--%s">'
        '<div class="zone__head"><span class="zone__bar"></span>'
        '<span class="zone__t">%s · %s</span>'
        '<span class="zone__d"%s>%s</span>'
        '<span class="zone__n n">%d</span><span class="zone__chev">▼</span></div>'
        '<div class="zone__body">%s%s</div></section>'
        % (zone, letter, escape(title), dattr, escape(desc), len(rows_), note_html, body)
    )


# ── 总览可视化 ────────────────────────────────────────────────────────
SPACE_BUCKETS = [
    ('≥ 0', '正空间', 0, 1e9),
    ('−5 ~ 0', None, -5, 0),
    ('−10 ~ −5', None, -10, -5),
    ('−15 ~ −10', None, -15, -10),
    ('−20 ~ −15', None, -20, -15),
    ('−30 ~ −20', None, -30, -20),
    ('< −30', None, -1e9, -30),
]


def viz_space(rows_):
    vals = [r['up'] for r in rows_ if r['up'] is not None]
    tally = []
    for lab, sub, lo, hi in SPACE_BUCKETS:
        c = sum(1 for v in vals if lo <= v < hi)
        tally.append((lab, sub, c))
    mx = max([c for _, _, c in tally] or [1])
    cols = []
    for i, (lab, sub, c) in enumerate(tally):
        h = (c / mx * 100) if mx else 0
        tone = 'is-up' if lab.startswith('≥') else ('is-warn' if lab.startswith('<') else 'is-down')
        cols.append(
            '<div class="cbar %s"><div class="cbar__c">'
            '<span class="cbar__f" data-agg="dist-b%d" style="height:%.1f%%">'
            '<b class="cbar__v n" data-agg="dist-n%d">%d</b></span>'
            '</div><div class="cbar__x n">%s</div>%s</div>'
            % (tone, i, h, i, c, escape(lab), '<div class="cbar__s">%s</div>' % sub if sub else '')
        )
    n_pass = sum(1 for r in rows_ if r['up'] is not None and r['up'] >= 15
                 and r['win_v'] is not None and r['win_v'] >= 30)
    foot = SP_T_FOOT.format(npass=n_pass) if n_pass else SP_T_FOOT0
    return (
        '<div class="viz"><div class="viz__h">潜在空间分布'
        '<span class="viz__s">%d 只有量化期望价 · 单位 %%</span></div>'
        '<div class="bars">%s</div>'
        '<div class="viz__f" data-agg="spfoot">%s</div>'
        '</div>' % (len(vals), ''.join(cols), foot)
    )


WIN_ROWS = [('≥ 30%', 30, 1e9), ('25% ~ 29%', 25, 30), ('≤ 20%', -1e9, 25)]
COL_DEFS = [('≥ 0%', 0, 1e9), ('−10% ~ 0', -10, 0), ('−20% ~ −10%', -20, -10), ('< −20%', -1e9, -20)]


def viz_matrix(rows_):
    pool = [r for r in rows_ if r['up'] is not None and r['win_v'] is not None]
    body = []
    col_tot = [0] * len(COL_DEFS)
    for ri, (rlab, wlo, whi) in enumerate(WIN_ROWS):
        cells, rt = [], 0
        for ci, (clab, clo, chi) in enumerate(COL_DEFS):
            n = sum(1 for r in pool if wlo <= r['win_v'] < whi and clo <= r['up'] < chi)
            rt += n
            col_tot[ci] += n
            lvl = 'is-z' if n == 0 else ('is-1' if n <= 2 else ('is-2' if n <= 5 else 'is-3'))
            cells.append('<td class="mx__c %s n" data-agg="mxd-%d-%d">%s</td>'
                         % (lvl, ri, ci, n if n else '·'))
        body.append('<tr><th>%s</th>%s<td class="mx__t n" data-agg="mxrt-%d">%d</td></tr>'
                    % (escape(rlab), ''.join(cells), ri, rt))
    head = ''.join('<th class="ta-c">%s</th>' % escape(c) for c, _, _ in COL_DEFS)
    foot = ''.join('<td class="mx__t n" data-agg="mxct-%d">%d</td>' % (i, c)
                   for i, c in enumerate(col_tot))
    # 右上角 = 「胜率 ≥ 30%」行 × 「潜在空间 ≥ 0」列，即「胜率与赔率同时达标」
    hi_cell = sum(1 for r in pool if r['win_v'] >= 30 and r['up'] >= 0)
    mx_foot = MX_T_FOOT.format(hi=hi_cell) if hi_cell else MX_T_FOOT0
    return (
        '<div class="viz"><div class="viz__h">赔率矩阵'
        '<span class="viz__s">胜率 ＼ 潜在空间 · 单位：只</span></div>'
        '<table class="mx"><thead><tr><th class="mx__h">胜率 ＼ 空间</th>%s'
        '<th class="ta-c">合计</th></tr></thead><tbody>%s</tbody>'
        '<tfoot><tr><th>合计</th>%s<td class="mx__t n" data-agg="mxgt">%d</td></tr></tfoot></table>'
        '<div class="viz__f" data-agg="mxfoot">%s</div>'
        '</div>' % (head, ''.join(body), foot, len(pool), mx_foot)
    )


def comp_bar(rows_):
    n = len(rows_) or 1
    order = [('N', '回避 / 不买'), ('H', '持有 / 观察'), ('S', '减持')]
    segs, legs = [], []
    for b, lab in order:
        c = sum(1 for r in rows_ if r['bkt'] == b)
        if c:
            segs.append('<span class="cp--%s" style="width:%.2f%%"></span>' % (b, c / n * 100))
        legs.append('<span class="cmp__i"><i class="cp--%s"></i>%s <b class="n">%d</b></span>'
                    % (b, escape(lab), c))
    return ('<div class="cmp"><div class="cmp__bar">%s</div>'
            '<div class="cmp__lg">%s</div></div>' % (''.join(segs), ''.join(legs)))


# ── 复核时间轴 ────────────────────────────────────────────────────────
def norm_valid(v, cat):
    s = re.sub(r'\s+', ' ', (v or '').strip())
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', s)
    for m, d in re.findall(r'(?<!\d)(\d{1,2})-(\d{2})(?!\d)', s):
        cand = '2026-%02d-%s' % (int(m), d)
        if cand not in dates:
            dates.append(cand)
    if not s:
        return ('未标注复核时点' if cat == 'B' else '按下次定期报告'), 9, []
    if '三季' in s:
        lab = '2026 三季报'
        if '经营数据' in s:
            lab += ' · 经营数据快报'
        return lab, 1, sorted(set(dates))
    if '年报' in s and '一季报' in s:
        return '2026 年报 + 2027 一季报', 2, sorted(set(dates))
    if '年报' in s:
        return '2026 年报', 3, sorted(set(dates))
    return s[:44], 8, sorted(set(dates))


def calendar(rows_):
    groups = {}
    for r in rows_:
        lab, rank, dates = norm_valid(r.get('valid'), r.get('cat'))
        g = groups.setdefault((rank, lab), {'who': [], 'dates': []})
        g['who'].append((r['name'], r['code'], dates))
    items = []
    for (rank, lab), g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        named = [(n, c, d[0]) for n, c, d in g['who'] if d]
        named.sort(key=lambda x: x[2])
        who = ' · '.join(n for n, _, _ in g['who'])
        extra = ''
        if named:
            extra = ('<div class="tl__x">已披露预约日：' +
                     ' · '.join('%s <b class="n">%s</b>' % (escape(n), escape(d[5:])) for n, _, d in named) +
                     '</div>')
        items.append(
            '<li class="tl"><span class="tl__d"></span><div class="tl__b">'
            '<div class="tl__h"><b>%s</b><span class="tl__n n">%d 只</span></div>'
            '<div class="tl__w">%s</div>%s</div></li>'
            % (escape(lab), len(g['who']), escape(who), extra)
        )
    return '<ol class="tls">%s</ol>' % ''.join(items)


# ── 主流程 ────────────────────────────────────────────────────────────
def positions_html(positions, rows_by_code):
    """持仓与后期计划 Tab：概览表（点击行跳转对应计划卡）→ 汇总条 → 持仓卡。
    数据来自 manifest 顶层 positions 段，现价与观察池行情联动。"""
    if not positions:
        return '<div class="pos-empty">manifest 未配置 positions 段，暂无持仓数据。</div>'
    rows_by_code = rows_by_code or {}
    total_mv = 0.0
    total_cost = 0.0
    neg_mv = 0.0          # 无 cost（负成本 / 利润仓）标的的市值合计，单独披露
    n_cost = 0
    items = []
    cards = []

    def _mv_key(p):
        """持仓卡排序键：市值降序。现价缺失时退化为股数×成本，再退化为 0。
        代码内排序而非依赖 manifest 手写顺序——否则股数一改（如 808→100 股）顺序就错。"""
        r = rows_by_code.get(p['code']) or {}
        px_s = r.get('px_n') or r.get('px') or ''
        try:
            px = float(px_s) if px_s else float(p.get('cost') or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        return -(float(p.get('shares') or 0) * px)

    positions = sorted(positions, key=_mv_key)
    for p in positions:
        r = rows_by_code.get(p['code']) or {}
        px_s = r.get('px_n') or r.get('px') or ''
        px = float(px_s) if px_s else 0.0
        cur = r.get('cur', '元')
        chg = r.get('px_chg', '')
        shares = p.get('shares', 0)
        mv = shares * px
        total_mv += mv
        cost = p.get('cost')
        cost_html = ''
        pl_html = ''
        if cost is not None and px:
            cost_v = cost * shares
            total_cost += cost_v
            n_cost += 1
            pl = mv - cost_v
            plp = (px / cost - 1) * 100
            cls = 'is-up' if pl >= 0 else 'is-down'
            pl_html = ('<div class="pos__pl"><dt>浮动盈亏（对成本）</dt>'
                       '<dd class="%s n" data-f="pl" data-fb="">%+.1f%% <span data-f="plv">%+.0f 元</span></dd></div>'
                       % (cls, plp, pl))
            cost_html = '%.3f %s' % (cost, cur)
            pl_txt = '<span class="%s n">%+.1f%%</span>' % (cls, plp)
        else:
            cost_html = p.get('cost_label') or '—'
            # 无成本基准（负成本 / 纯利润仓）时「浮动盈亏」列没有可算的百分比，
            # 允许用 pl_label 覆盖该列文案，避免与「成本」列显示同一串造成误读。
            pl_txt = '<span class="dim">%s</span>' % escape(
                p.get('pl_label') or p.get('cost_label') or '—')
            # 无成本基准的标的（负成本摊薄 / 纯利润仓）不参与「在管成本」，
            # 但其市值会进入总市值与总浮动盈亏 → 必须单独披露，否则汇总口径被隐性放大。
            neg_mv += mv
        px_html = ('<span data-f="px" data-fb="">%s</span>'
                   ' <span class="pos__chg">今日 %s%%</span>' % (escape(str(px_s)), escape(str(chg)))
                   ) if px_s and chg != '' else ('<span data-f="px" data-fb="">%s</span>' % escape(str(px_s))
                                                 if px_s else '—')
        max_n = p.get('shares_total')
        shares_txt = '%d 股' % shares if shares else '—'
        if max_n and max_n != shares:
            shares_txt += ' <span class="dim">/ 计划 %d</span>' % max_n
        items.append({'code': p['code'], 'name': p['name'], 'strategy': p.get('strategy', ''),
                      'shares_txt': shares_txt, 'cost_html': cost_html, 'px_s': px_s or '—',
                      'mv': mv, 'cur': cur, 'pl_txt': pl_txt,
                      'has_cost': cost is not None and bool(px)})
        plans = ''.join(
            '<tr><td class="pos__trg">%s</td><td>%s</td></tr>' % (escape(t), escape(d))
            for t, d in (p.get('plan') or []))
        note = p.get('note') or ''
        # 未记录建仓日时不要渲染「… 建仓」，避免出现只有「建仓」二字的空壳
        opened_txt = ('<span class="pos__open">%s 建仓</span>' % escape(p['opened'])) if p.get('opened') else ''
        cards.append(
            '<article class="pos-card" id="pos-%s">'
            '<div class="pos-card__top"><div class="pos-card__id"><b>%s</b><span class="cd">%s</span></div>'
            '<span class="posv">%s</span>%s</div>'
            '<div class="pos-card__kv">'
            '<div><dt>持仓 / 计划</dt><dd class="n">%s</dd></div>'
            '<div><dt>成本</dt><dd class="n">%s</dd></div>'
            '<div><dt>现价</dt><dd class="n" data-f="pxw">%s</dd></div>'
            '<div><dt>市值</dt><dd class="n" data-f="mv">%.0f %s</dd></div>'
            '%s</div>'
            '<p class="pos__note">%s</p>'
            '<table class="pos__plan"><thead><tr><th>环节</th><th>触发与动作</th></tr></thead>'
            '<tbody>%s</tbody></table>'
            '<a class="lk" href="%s" target="_blank" rel="noopener">观察池报告原文 →</a>'
            '</article>'
            % (escape(p['code']), escape(p['name']), escape(p['code']), escape(p.get('strategy', '')),
               opened_txt, shares_txt, cost_html, px_html, mv, cur,
               pl_html, escape(note), plans,
               escape((r or {}).get('url') or '#')))
    ov_rows = ''.join(
        '<tr class="pos-ov__row" data-code="%s">'
        '<td class="pos-ov__nm"><b>%s</b><span class="cd">%s</span></td>'
        '<td><span class="posv">%s</span></td>'
        '<td class="n">%s</td>'
        '<td class="n">%s</td>'
        '<td class="n"><span data-f="px" data-fb="">%s</span></td>'
        '<td class="n" data-f="mv">%.0f %s</td>'
        '<td class="n"%s>%s</td>'
        '<td class="pos-ov__go">计划 ↓</td></tr>'
        % (escape(it['code']), escape(it['name']), escape(it['code']), escape(it['strategy']),
           it['shares_txt'], it['cost_html'], escape(str(it['px_s'])), it['mv'], it['cur'],
           ' data-f="pl" data-fb=""' if it['has_cost'] else '', it['pl_txt'])
        for it in items)
    ov_html = ('<div class="pos-ovw"><table class="pos-ov">'
               '<thead><tr><th>标的</th><th>策略</th><th>持仓</th><th>成本</th>'
               '<th>现价</th><th>市值</th><th>浮动盈亏</th><th></th></tr></thead>'
               '<tbody>%s</tbody></table></div>' % ov_rows)
    sum_pl = total_mv - total_cost
    cost_scope = '、'.join(it['name'] for it in items if it['pl_txt'].startswith('<span class="is-'))
    pl_lbl = '浮动盈亏（对在管成本）'
    pl_note = ''
    if neg_mv > 0:
        pl_lbl = '浮动盈亏（含利润仓市值）'
        pl_note = (' <span class="dim" data-f="sum-plnote">'
                   '（负成本仓 %.0f 元全额计入）</span>' % neg_mv)
    sum_html = ('<div class="pos-sum"><div><dt>持仓标的</dt><dd class="n">%d 只</dd></div>'
                '<div><dt>总市值</dt><dd class="n" data-f="sum-mv">%.0f 元</dd></div>'
                '<div><dt>在管成本（%s）</dt><dd class="n">%.0f 元</dd></div>'
                '<div><dt>%s</dt><dd class="n %s" data-f="sum-pl">%+.0f 元%s</dd></div>'
                '<div><dt>利润仓（负成本）</dt><dd data-f="sum-profit">%s</dd></div></div>'
                % (len(positions), total_mv,
                   escape(cost_scope or '—'), total_cost,
                   pl_lbl, 'is-up' if sum_pl >= 0 else 'is-down', sum_pl, pl_note,
                   ' · '.join('%s %.0f %s' % (it['name'], it['mv'], it['cur']) for it in items
                              if not it['pl_txt'].startswith('<span class="is-')) or '—'))
    return ov_html + sum_html + ''.join(cards)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--asof', default='')
    ap.add_argument('--records', default='')
    ap.add_argument('--prev-cutoff', default='本轮新增')
    ap.add_argument('--fresh-from', default='')
    # 现价时点：仅当提供了「实时行情刷新」的台账才传；不传则行为与本改造前完全一致。
    ap.add_argument('--px-asof', default='')
    # 持仓数据源：manifest 顶层 positions 段；缺省自动探测脚本同目录的 watchlist_manifest.json
    ap.add_argument('--manifest', default='')
    a = ap.parse_args()

    man = {}
    man_path = a.manifest or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watchlist_manifest.json')
    if os.path.isfile(man_path):
        man = json.load(io.open(man_path, encoding='utf-8'))
    positions = man.get('positions') or []
    held = {p['code']: p for p in positions}

    rows = [enrich(r) for r in json.load(io.open(a.data, encoding='utf-8'))]
    for r in rows:
        r['_held'] = r['code'] in held
        r['_pos'] = held.get(r['code'])
    rows_by_code = {r['code']: r for r in rows}

    # 全局排序：有量化期望价的在前，按潜在空间降序；无期望价的按报告日降序垫底。
    # 区内顺序沿用该全局序，渲染层不再二次排序（前端 sbtn 只改 DOM 顺序）。
    rows.sort(key=lambda r: (r.get('date') or ''), reverse=True)
    rows.sort(key=lambda r: (0 if r['up'] is not None else 1, -(r['up'] or 0)))

    zones = {z: [r for r in rows if r['zone'] == z] for z, *_ in ZONE_META}

    n = len(rows)
    n_pos = sum(1 for r in rows if r['pos'])
    n_pass = sum(1 for r in rows if r['up'] is not None and r['up'] >= 15
                 and r['win_v'] is not None and r['win_v'] >= 30)
    n_w30 = sum(1 for r in rows if r['win_v'] is not None and r['win_v'] >= 30)
    n_w30_pos = sum(1 for r in rows if r['win_v'] is not None and r['win_v'] >= 30
                    and r['up'] is not None and r['up'] >= 0)
    n_quant = sum(1 for r in rows if r['up'] is not None)
    fresh_n = sum(1 for r in rows if r.get('fresh'))
    fresh_from = a.fresh_from or a.prev_cutoff
    cnt = {b: sum(1 for r in rows if r['bkt'] == b) for b in ('N', 'H', 'S')}

    if n_pass:
        verdict = V_T_PASS.format(n=n, nq=n_quant, npos=n_pos, npass=n_pass)
    else:
        tail = (V_T_TAIL0.format(nw30=n_w30) if n_w30_pos == 0
                else V_T_TAIL1.format(nw30=n_w30, nw30pos=n_w30_pos))
        verdict = V_T_ZERO.format(n=n, nq=n_quant, npos=n_pos, tail=tail)

    # KPI 副标同样按数据生成：现价刷新后「正空间但胜率均 < 30%」等写死说法会失真
    hint_pos = V_T_HINT_P.format(npass=n_pass) if n_pass else V_T_HINT_P0
    hint_w30 = V_T_HINT_W.format(nw30pos=n_w30_pos) if n_w30_pos else V_T_HINT_W0
    # 第 5 项为「页内刷新可改」的节点 id（值 / 副标），空串表示静态
    kpis = [
        ('kpi--plain', str(n), '覆盖标的', '取各标的<strong>最新一版</strong>报告', '', ''),
        ('kpi--up', str(n_pos), '期望价 &gt; 现价', hint_pos, 'kpi-pos-v', 'kpi-pos-h'),
        ('kpi--plain', str(n_w30), '胜率 ≥ 30%', hint_w30, '', 'kpi-w30-h'),
        ('kpi--plain', str(cnt['N']), '回避 / 不买', '本轮扫描的排除结果', '', ''),
        ('kpi--brand', str(fresh_n), escape(a.prev_cutoff), '报告日 ≥ %s' % escape(fresh_from), '', ''),
    ]
    kpi_html = ''.join(
        '<div class="kpi %s"><div class="kpi__v n"%s>%s</div>'
        '<div class="kpi__l">%s</div><div class="kpi__h"%s>%s</div></div>'
        % (c, (' data-agg="%s"' % vid) if vid else '', v, l,
           (' data-agg="%s"' % hid) if hid else '', h)
        for c, v, l, h, vid, hid in kpis)

    chips = [('all', '全部', n), ('pos', '正空间', n_pos),
             ('H', '持有观察', cnt['H']), ('N', '回避 / 不买', cnt['N']),
             ('S', '减持', cnt['S']), ('fresh', '最新批次', fresh_n)]
    chip_html = ''.join(
        '<button class="chip%s" data-zone-filter="%s">%s<b%s>%d</b></button>'
        % (' on' if k == 'all' else '', k, escape(l),
           ' data-agg="chip-pos"' if k == 'pos' else '', v) for k, l, v in chips)

    # 页内刷新用的最小数据模型：只有它和 TPL_BAG 进页面，渲染逻辑仍只在本文件里。
    model = {
        'rows': [{'c': r['code'], 'e': r['exp_v'], 'h': r.get('obs_hi'),
                  'p': r.get('px_n') or r.get('px') or '', 'w': r['win_v'],
                  'g': r['gap'], 'u': r['up'], 'z': r['zone']} for r in rows],
        'pos': {p['code']: {'s': p.get('shares', 0), 'c': p.get('cost'),
                            'n': p.get('name', ''),
                            'cur': (rows_by_code.get(p['code']) or {}).get('cur', '元'),
                            'px0': _f((rows_by_code.get(p['code']) or {}).get('px_n'))}
                for p in positions},
        'tpl': TPL_BAG,
        'const': {'smin': SPACE_MIN, 'smax': SPACE_MAX, 'zero': round(ZERO_PCT, 4)},
        'asof': (a.px_asof or '').strip() or (a.asof or ''),
    }
    model_json = (json.dumps(model, ensure_ascii=False, separators=(',', ':'))
                  .replace('</', '<\\/'))

    html = TEMPLATE
    px_asof = (a.px_asof or '').strip()
    repl = {
        '@@ASOF@@': escape(a.asof or '—'),
        '@@PX_ASOF@@': escape(px_asof or '—'),
        # 有实时现价时：页头加「现价时点」并高亮；胜率列标注为报告口径（未随实时价重算）
        '@@PX_SEG@@': (' ｜ 现价时点 <b>%s</b>' % escape(px_asof)) if px_asof else '',
        '@@ASOF_LABEL@@': '报告数据时点' if px_asof else '数据时点',
        '@@PX_DL@@': ('<dt>现价与报告的时点差</dt><dd>本页「现价」已刷新至<b>实时行情</b>'
                      '（时点见页头），<strong>潜在空间与距买点按实时现价重算</strong>；'
                      '而<strong>期望价、买入胜率、观察买点仍为各报告原文口径</strong> —— '
                      '其中买入胜率按报告写作时的现价（基准价）计算，未随实时价重算，'
                      '故与「潜在空间」存在时点差。读两列时须把这一层记在心里，'
                      '并按各报告的复核有效期决定是否重跑验证点。</dd>') if px_asof else '',
        '@@PX_FOOT@@': ('报告日期为各报告数据时点；<b>现价为实时行情快照</b>（时点见页头），'
                        '期望价 / 买入胜率 / 观察买点仍取自报告原文（胜率按报告写作时现价计算，'
                        '未随实时价重算）。' if px_asof else '报告日期为各报告数据时点，行情为该时点快照。'),
        '@@WIN_TH@@': ('买入胜率 <span class="th-h">报告口径</span>' if px_asof else '买入胜率'),
        '@@N@@': str(n),
        '@@VERDICT@@': verdict,
        '@@KPIS@@': kpi_html,
        '@@CHIPS@@': chip_html,
        '@@COMP@@': comp_bar(rows),
        '@@VIZ_SPACE@@': viz_space(rows),
        '@@VIZ_MATRIX@@': viz_matrix(rows),
        '@@ZONES@@': ''.join(zone_block(z, zones[z]) for z, *_ in ZONE_META),
        '@@CALENDAR@@': calendar(rows),
        '@@FRESH_FROM@@': escape(fresh_from),
        '@@POSITIONS@@': positions_html(positions, rows_by_code),
        # ── 页内「刷新现价」所需的三样东西：数据模型、条窗口常量、快照时点
        '@@PX_MODEL@@': model_json,
        '@@SPACE_MIN@@': '%.1f' % SPACE_MIN,
        '@@SPACE_MAX@@': '%.1f' % SPACE_MAX,
        '@@ZERO_PCT@@': '%.4f' % ZERO_PCT,
        '@@PX_SNAP@@': escape(px_asof or a.asof or '—'),
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    # @@WIN_TH@@ 位于模块级 THEAD 常量内，随 @@ZONES@@ 一起进入页面，需再补一次替换
    html = html.replace('@@WIN_TH@@', repl['@@WIN_TH@@'])

    io.open(a.out, 'w', encoding='utf-8').write(html)
    print('written %s | %d bytes | %d rows' % (a.out, len(html), n))
    print('zones: A=%d H=%d N=%d S=%d | pos=%d pass=%d win30=%d fresh=%d'
          % (len(zones['A']), len(zones['H']), len(zones['N']), len(zones['S']),
             n_pos, n_pass, n_w30, fresh_n))
    missing = [r['name'] for r in rows if not r.get('judge')]
    if missing:
        print('! 缺判定:', missing)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>投资观察池 · 决策驾驶舱</title>
<style>
/* ══ 设计 token ═══════════════════════════════════════════════════════
   语义分层是本版的核心：红/绿只承担经济含义（潜在空间正负，A 股红涨绿跌），
   判定三桶改用 slate / indigo / amber，色相与红绿完全不重叠，杜绝 v1 中
   「同一个 #c62828 既表示回避又表示下跌」的语义抢占。                 */
:root{
  /* ── 配色三档 ───────────────────────────────────────────────────────
     2026-10-09 中途修订：首版为「柔和(#f8fafc) / 标准(#fff) / 深色」，用户反馈
     前者与后者观感差异过小（层次差仅 4% 明度），故合并为一档，空出的位置换成
     暖色低蓝光的「护眼」。现为 标准（默认）/ 护眼 / 深色。
     切换器在 masthead 右上角，选择存 localStorage（键 wl-theme）。
     三档共用同一套语义分层：红绿只服务涨跌，判定三桶走 slate / indigo / amber。

     档位一 · 标准：卡面 #f8fafc（非纯白），页面底 #e9edf4，层次差 5%；
     正文 #333d52 在 #f8fafc 上对比度 10.4:1，仍达 WCAG AAA（AA 只要 4.5:1）。*/
  --bg:#e9edf4; --surface:#f8fafc; --surface-2:#eff2f8; --surface-3:#e4e8f1;
  --line:#dde3ec; --line-2:#eaeef5;
  --ink-900:#131a2a; --ink-700:#333d52; --ink-500:#5c667c; --ink-400:#858fa3; --ink-300:#aab2c2;
  --brand:#3557c9; --brand-soft:#eaeffb; --brand-fill:#3557c9;
  --solid:#131a2a; --on-solid:#fff; --on-brand:#fff;
  --up:#d42b2b; --up-soft:#fdecec; --down:#0d8a54; --down-soft:#e8f6ef;
  --j-n:#525c74; --j-n-bg:#eef0f6; --j-h:#2f5fd0; --j-h-bg:#e9effd; --j-s:#95590f; --j-s-bg:#fdf2e2;
  --heat1-bg:#eaeffb; --heat1-ink:#3557c9;
  --heat2-bg:#cddcf8; --heat2-ink:#1e3f9c;
  --heat3-bg:#a9c1f2; --heat3-ink:#15307a;
  --dot-off:#e7ebf3; --dot-low:#98a1b3; --dot-mid:#c98a1c; --dot-mid-ink:#8a5c00;
  --chg-bg:#fdf3d6; --chg-ink:#7a5400;
  --alert-bg:#fdf1e3; --alert-ink:#8a4b00; --alert-line:#d98324;
  --opb-bg:#e8f0fe; --opb-ink:#1d5fbf;
  --mast-a:#131a2e; --mast-b:#1a2547; --mast-c:#22396e;
  --mast-eyebrow:#89a0d6; --mast-glow:rgba(88,128,255,.30);
  --tt-ink:#b7c4e2; --tt-on:#16204a;
  --sh1:0 1px 2px rgba(19,26,42,.06); --sh2:0 4px 14px rgba(19,26,42,.09);
  --fs-xs:11.5px; --fs-sm:12.5px; --fs-md:14px; --fs-lg:16px; --fs-xl:20px; --fs-2xl:32px;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:20px; --s6:24px; --s8:32px; --s10:40px;
  --r1:6px; --r2:10px; --r3:14px; --rp:999px;
  --font:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif;
  --mono:"Consolas","SF Mono",Menlo,"DejaVu Sans Mono",monospace;
}
:root[data-theme="eye"]{
  /* 档位二 · 护眼：暖纸调，压低蓝光，长时间阅读。色相整体由 218° 蓝灰旋至约 40° 暖黄，
     明度梯度与标准档完全对应（底 / 卡 / 三级底同样 5% 间隔），层次关系不丢。
     正文 #3f3b32 在 #f7f4ec 上对比度 10.97:1；次要 #6b6455 = 5.68:1 —— 均过 AA。
     品牌色改取赭石 #8a5a1e：作文字 5.37:1，作实心块承白字 5.90:1。          */
  --bg:#e8e3d8; --surface:#f7f4ec; --surface-2:#f1ece1; --surface-3:#e8e2d5;
  --line:#dcd5c6; --line-2:#e7e1d4;
  --ink-900:#24221d; --ink-700:#3f3b32; --ink-500:#6b6455; --ink-400:#8e8776; --ink-300:#b2aa97;
  --brand:#8a5a1e; --brand-soft:#f2e9d8; --brand-fill:#8a5a1e;
  --solid:#3a352b; --on-solid:#fff; --on-brand:#fff;
  --up:#c62a2a; --up-soft:#fae8e4; --down:#0b7a4b; --down-soft:#e6f3ea;
  --j-n:#5b5449; --j-n-bg:#efeadf; --j-h:#3d51b0; --j-h-bg:#e9ecf7; --j-s:#8a5a0f; --j-s-bg:#f8eed9;
  --heat1-bg:#f2e9d8; --heat1-ink:#8a5a1e;
  --heat2-bg:#e6d4b0; --heat2-ink:#6f4614;
  --heat3-bg:#d8bd8a; --heat3-ink:#552f06;
  --dot-off:#e3dccd; --dot-low:#a49a86; --dot-mid:#c0861b; --dot-mid-ink:#7a5200;
  --chg-bg:#f6e8c8; --chg-ink:#6b4500;
  --alert-bg:#f4e3ca; --alert-ink:#7a4405; --alert-line:#b8760f;
  --opb-bg:#f2e9d8; --opb-ink:#6f4614;
  --mast-a:#231e17; --mast-b:#332a1d; --mast-c:#4a3a22;
  --mast-eyebrow:#c0a878; --mast-glow:rgba(180,140,80,.26);
  --tt-ink:#c9bda6; --tt-on:#2b2419;
  --sh1:0 1px 2px rgba(60,48,28,.08); --sh2:0 4px 14px rgba(60,48,28,.11);
}
:root[data-theme="dark"]{
  /* 档位三 · 深色：夜间盯盘。两个易错点：
     ① --brand（当文字用，深底上须提亮）与 --brand-fill（当实心块背景，须够深
        以承白字）必须分开取值，否则 chip 选中态会变成浅蓝底白字、对比度不足；
     ② --solid（排序选中态底色）不能用 --ink-900 ——它在深色档是近白色，
        配 #fff 会成白底白字，必须单独给值。                              */
  --bg:#111419; --surface:#1a1f28; --surface-2:#161a22; --surface-3:#232a36;
  --line:#2c3442; --line-2:#212836;
  --ink-900:#edf1f8; --ink-700:#c6d0e0; --ink-500:#8f9aad; --ink-400:#6f7a8c; --ink-300:#5b6576;
  --brand:#7d9bff; --brand-soft:#1d2540; --brand-fill:#4d6ee0;
  --solid:#39445a; --on-solid:#fff; --on-brand:#fff;
  --up:#ff6b6b; --up-soft:#3a1e22; --down:#3ecf92; --down-soft:#12332a;
  --j-n:#9aa5ba; --j-n-bg:#262d3a; --j-h:#88a4ff; --j-h-bg:#1e2743; --j-s:#e0a952; --j-s-bg:#3a2c17;
  --heat1-bg:#1e2743; --heat1-ink:#88a4ff;
  --heat2-bg:#2a3a66; --heat2-ink:#b9caff;
  --heat3-bg:#3c5490; --heat3-ink:#e0e9ff;
  --dot-off:#2b323f; --dot-low:#5d6674; --dot-mid:#c98a1c; --dot-mid-ink:#e5b256;
  --chg-bg:#3a2c17; --chg-ink:#e0a952;
  --alert-bg:#3a2a12; --alert-ink:#f0b45c; --alert-line:#c9821f;
  --opb-bg:#1d2540; --opb-ink:#9db4ff;
  --mast-a:#0e1220; --mast-b:#141b33; --mast-c:#1b2b52;
  --sh1:0 1px 2px rgba(0,0,0,.45); --sh2:0 6px 18px rgba(0,0,0,.55);
}
*,*::before,*::after{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink-700);font:var(--fs-md)/1.62 var(--font)}
.n{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-.1px}
.dim{color:var(--ink-300)}
.ta-r{text-align:right}.ta-c{text-align:center}
.page{max-width:1380px;margin:0 auto;padding:0 var(--s5) var(--s10)}
@media(max-width:900px){.page{padding:0 var(--s3) var(--s8)}}

/* ── masthead ─────────────────────────────────────────────────────── */
.mast{position:relative;overflow:hidden;margin:0 calc(var(--s5)*-1) var(--s5);
  padding:var(--s8) var(--s5) var(--s6);
  background:linear-gradient(135deg,var(--mast-a) 0%,var(--mast-b) 46%,var(--mast-c) 100%);color:#fff}
.mast::after{content:"";position:absolute;right:-90px;top:-110px;width:340px;height:340px;
  border-radius:50%;background:radial-gradient(circle,var(--mast-glow),transparent 68%)}
.mast__eyebrow{font-size:var(--fs-xs);letter-spacing:.18em;color:var(--mast-eyebrow);font-weight:600}
.mast__title{margin:var(--s2) 0 var(--s3);font-size:30px;font-weight:650;letter-spacing:.5px}
.mast__sub{margin:0;font-size:var(--fs-sm);color:#a9b7d7;line-height:2}
.mast__sub b{color:#fff}
@media(max-width:900px){.mast{margin:0 calc(var(--s3)*-1) var(--s4);padding:var(--s6) var(--s3) var(--s5)}
  .mast__title{font-size:24px}}

/* ── 配色档位切换器（大屏浮于 masthead 右上，窄屏转为流式避开标题） ────── */
.tt{position:absolute;top:18px;right:20px;z-index:3;display:flex;gap:2px;padding:3px;
  background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.18);border-radius:var(--rp)}
.tt__b{border:0;background:transparent;color:var(--tt-ink);font:600 var(--fs-sm)/1.5 var(--font);
  padding:5px 13px;border-radius:var(--rp);cursor:pointer;transition:.15s;white-space:nowrap}
.tt__b:hover{color:#fff;background:rgba(255,255,255,.10)}
.tt__b[aria-pressed="true"]{background:rgba(255,255,255,.94);color:var(--tt-on)}
.tt__b:focus-visible{outline:2px solid #fff;outline-offset:2px}
@media(max-width:900px){.tt{top:12px;right:12px;padding:2px}
  .tt__b{padding:4px 10px;font-size:11.5px}}
@media(max-width:560px){.tt{position:static;margin-top:var(--s4);display:inline-flex}}

/* ── verdict ──────────────────────────────────────────────────────── */
.verdict{display:flex;gap:var(--s4);align-items:flex-start;background:var(--surface);
  border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:var(--r2);
  padding:var(--s4) var(--s5);box-shadow:var(--sh1);margin-bottom:var(--s5)}
.verdict__ico{flex:none;width:26px;height:26px;border-radius:var(--r1);background:var(--brand-soft);
  color:var(--brand);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:var(--fs-sm)}
.verdict__t{font-size:var(--fs-md);line-height:1.9;margin:0;color:var(--ink-700)}
.verdict__t b{color:var(--ink-900)}
.hl-up{color:var(--up);font-weight:700}

/* ── KPI ──────────────────────────────────────────────────────────── */
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:var(--s3);margin-bottom:var(--s5)}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--r2);
  padding:var(--s4) var(--s4) var(--s3);box-shadow:var(--sh1)}
.kpi__v{font-size:28px;font-weight:700;line-height:1.1;color:var(--ink-900)}
.kpi__l{font-size:var(--fs-sm);color:var(--ink-700);font-weight:600;margin-top:var(--s2)}
.kpi__h{font-size:var(--fs-xs);color:var(--ink-400);margin-top:2px;line-height:1.5}
.kpi--up .kpi__v{color:var(--up)}
.kpi--brand .kpi__v{color:var(--brand)}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}}
@media(max-width:680px){.kpis{grid-template-columns:repeat(2,1fr)}}

/* ── panel ────────────────────────────────────────────────────────── */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  box-shadow:var(--sh1);margin-bottom:var(--s5);overflow:hidden}
.panel__head{display:flex;align-items:center;gap:var(--s3);padding:var(--s4) var(--s5);
  border-bottom:1px solid var(--line-2);flex-wrap:wrap}
.panel__no{font-size:var(--fs-xs);font-weight:700;color:var(--brand);background:var(--brand-soft);
  border-radius:var(--rp);padding:3px 10px;letter-spacing:.05em}
.panel__t{margin:0;font-size:var(--fs-lg);font-weight:650;color:var(--ink-900)}
.panel__d{margin-left:auto;font-size:var(--fs-sm);color:var(--ink-400)}
.panel__body{padding:var(--s5)}

/* ── toolbar ──────────────────────────────────────────────────────── */
.bar{display:flex;flex-wrap:wrap;gap:var(--s2);align-items:center;
  padding:var(--s3) var(--s5);border-bottom:1px solid var(--line-2);background:var(--surface-2)}
.chip{border:1px solid var(--line);background:var(--surface);border-radius:var(--rp);
  padding:5px 13px;font:600 var(--fs-sm)/1.5 var(--font);color:var(--ink-500);cursor:pointer;transition:.15s}
.chip:hover{border-color:var(--brand);color:var(--brand)}
.chip.on{background:var(--brand-fill);border-color:var(--brand-fill);color:var(--on-brand)}
.chip b{font-family:var(--mono);font-weight:600;opacity:.8;margin-left:4px}
.sbtn{border:1px solid var(--line);background:var(--surface);border-radius:var(--r1);
  padding:5px 11px;font:600 var(--fs-sm)/1.5 var(--font);color:var(--ink-500);cursor:pointer}
.sbtn:hover{border-color:var(--brand);color:var(--brand)}
.sbtn.on{background:var(--solid);border-color:var(--solid);color:var(--on-solid)}
.sbtn.on.desc::after{content:" ↓"}
.sbtn.on.asc::after{content:" ↑"}
#q{border:1px solid var(--line);border-radius:var(--rp);padding:6px 14px;
  font:var(--fs-sm)/1.5 var(--font);background:var(--surface);color:var(--ink-700);
  outline:none;min-width:190px;transition:.15s}
#q:focus{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.sep{width:1px;height:20px;background:var(--line);margin:0 var(--s1)}
.grow{flex:1}
.hint{font-size:var(--fs-xs);color:var(--ink-400)}
.hint b{font-family:var(--mono);color:var(--brand)}

/* ── viz ──────────────────────────────────────────────────────────── */
.vizs{display:grid;grid-template-columns:1fr 1fr;gap:var(--s5)}
@media(max-width:1000px){.vizs{grid-template-columns:1fr}}
.viz{border:1px solid var(--line);border-radius:var(--r2);padding:var(--s4) var(--s5);background:var(--surface-2)}
.viz__h{font-size:var(--fs-md);font-weight:650;color:var(--ink-900);margin-bottom:var(--s4);
  display:flex;align-items:baseline;gap:var(--s2);flex-wrap:wrap}
.viz__s{font-size:var(--fs-xs);font-weight:400;color:var(--ink-400)}
.viz__f{font-size:var(--fs-xs);color:var(--ink-400);margin-top:var(--s3);line-height:1.7;
  border-top:1px dashed var(--line);padding-top:var(--s3)}
/* 分布柱状图（类名刻意与工具栏 .bar 区分，避免样式互相覆盖） */
.bars{display:flex;align-items:flex-end;gap:var(--s3);height:196px;padding-top:var(--s5)}
.cbar{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.cbar__c{position:relative;width:100%;flex:1}
.cbar__f{position:absolute;bottom:0;left:13%;right:13%;min-height:4px;
  border-radius:var(--r1) var(--r1) 0 0}
.cbar__v{position:absolute;top:-19px;left:50%;transform:translateX(-50%);
  font-size:var(--fs-sm);font-weight:700;color:var(--ink-900);white-space:nowrap}
.cbar__x{font-size:var(--fs-xs);color:var(--ink-500);margin-top:var(--s2);white-space:nowrap}
.cbar__s{font-size:10px;color:var(--ink-300);line-height:1.2}
.cbar.is-up .cbar__f{background:var(--up)}
.cbar.is-down .cbar__f{background:var(--down);opacity:.78}
.cbar.is-warn .cbar__f{background:var(--ink-300)}
.mx{width:100%;border-collapse:separate;border-spacing:3px;font-size:var(--fs-sm)}
.mx th{font-weight:600;color:var(--ink-500);font-size:var(--fs-xs);padding:var(--s2) var(--s1);white-space:nowrap}
.mx__h{text-align:left}
.mx__c{text-align:center;border-radius:var(--r1);padding:9px 4px;font-weight:700;color:var(--ink-700)}
.mx__c.is-z{color:var(--ink-300);background:var(--surface-3)}
.mx__c.is-1{background:var(--heat1-bg);color:var(--heat1-ink)}
.mx__c.is-2{background:var(--heat2-bg);color:var(--heat2-ink)}
.mx__c.is-3{background:var(--heat3-bg);color:var(--heat3-ink)}
.mx__t{text-align:center;font-weight:700;color:var(--ink-900);padding:9px 4px}
.cmp{margin-top:var(--s5);border-top:1px dashed var(--line);padding-top:var(--s4)}
.cmp__bar{display:flex;height:14px;border-radius:var(--rp);overflow:hidden;background:var(--surface-3)}
.cmp__bar span{height:100%}
.cp--N{background:var(--j-n)}.cp--H{background:var(--j-h)}.cp--S{background:var(--j-s)}
.cmp__lg{display:flex;flex-wrap:wrap;gap:var(--s4);margin-top:var(--s3);font-size:var(--fs-sm);color:var(--ink-500)}
.cmp__i{display:flex;align-items:center;gap:6px}
.cmp__i i{width:10px;height:10px;border-radius:3px;display:inline-block}
.cmp__i b{color:var(--ink-900)}

/* ── zone ─────────────────────────────────────────────────────────── */
.zone{border-top:1px solid var(--line-2)}
.zone:first-child{border-top:none}
.zone.is-empty{display:none}
.zone__head{display:flex;align-items:center;gap:var(--s3);padding:var(--s3) var(--s5);
  background:var(--surface-2);cursor:pointer;user-select:none}
.zone__head:hover{background:var(--surface-3)}
.zone__bar{width:3px;height:18px;border-radius:2px;flex:none}
.zone--A .zone__bar{background:var(--up)}
.zone--H .zone__bar{background:var(--j-h)}
.zone--N .zone__bar{background:var(--j-n)}
.zone--S .zone__bar{background:var(--j-s)}
.zone__t{font-size:var(--fs-md);font-weight:650;color:var(--ink-900);white-space:nowrap}
.zone__d{font-size:var(--fs-sm);color:var(--ink-400)}
.zone__n{margin-left:auto;font-size:var(--fs-xs);font-weight:700;color:var(--ink-500);
  background:var(--surface);border:1px solid var(--line);border-radius:var(--rp);padding:2px 9px}
.zone__chev{font-size:9px;color:var(--ink-300);transition:transform .18s}
.zone.is-collapsed .zone__body{display:none}
.zone.is-collapsed .zone__chev{transform:rotate(-90deg)}
.zone__note{padding:var(--s2) var(--s5) 0;font-size:var(--fs-xs);color:var(--ink-400)}
@media(max-width:760px){.zone__d{display:none}}

/* ── table ────────────────────────────────────────────────────────── */
.tw{overflow-x:auto}
table.wl{width:100%;border-collapse:collapse;font-size:var(--fs-sm);min-width:1000px}
table.wl th{position:sticky;top:0;z-index:1;background:var(--surface);text-align:left;
  font-size:var(--fs-xs);font-weight:600;color:var(--ink-400);letter-spacing:.03em;
  padding:var(--s2) var(--s3);border-bottom:1px solid var(--line);white-space:nowrap}
.th-h{font-weight:400;color:var(--ink-300)}
table.wl td{padding:9px var(--s3);border-bottom:1px solid var(--line-2);vertical-align:middle}
table.wl tbody tr:last-child td{border-bottom:none}
table.wl tbody tr:hover td{background:var(--surface-2)}
tr.is-fresh td:first-child{box-shadow:inset 3px 0 0 var(--brand)}
th.c-idx,td.idx{color:var(--ink-300);font-size:var(--fs-xs);width:34px}
td.nm b{color:var(--ink-900);font-weight:650}
.is-fresh td.nm b::after{content:"NEW";font-size:9px;font-weight:700;letter-spacing:.06em;
  color:var(--brand);background:var(--brand-soft);border-radius:3px;padding:1px 4px;margin-left:6px;vertical-align:1.5px}
.cd{display:block;font-family:var(--mono);font-size:10.5px;color:var(--ink-300);margin-top:1px}
td.jd .tag{display:inline-block}
.jd__n{display:block;font-size:var(--fs-xs);color:var(--ink-500);margin-top:3px;line-height:1.5}
.jd .chg{display:inline-block;margin-top:4px;font-size:10.5px;font-weight:600;color:var(--chg-ink);
  background:var(--chg-bg);border-radius:3px;padding:1px 6px;cursor:help}
.opb{display:inline-block;margin-left:8px;vertical-align:2px;font-size:10.5px;font-weight:600;
  color:var(--opb-ink);background:var(--opb-bg);border-radius:3px;padding:1px 6px;cursor:help;
  max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:none}

/* ── 行情刷新条（2026-10-23 新增）────────────────────────────────────
   取价走 qt.gtimg.cn 的 `v_<secid>="…"` 赋值式脚本，用 script 标签加载即绕过
   CORS；资料库页面的 CSP script-src 白名单含 *.gtimg.cn，故线上同样可用。
   失败一律降级为「保持渲染时快照」，不抛异常、不置空。               */
.pxbar{display:flex;align-items:center;gap:var(--s3);flex-wrap:wrap;
  margin:var(--s4) 0 0;padding:10px 14px;background:var(--surface);
  border:1px solid var(--line);border-left:3px solid var(--brand);border-radius:var(--r2)}
.pxbtn{appearance:none;border:1px solid var(--brand);background:var(--brand-fill);color:var(--on-brand);
  font:600 var(--fs-sm)/1 var(--font);padding:8px 16px;border-radius:var(--rp);cursor:pointer}
.pxbtn:hover{filter:brightness(1.08)}
.pxbtn:disabled{opacity:.55;cursor:progress}
.pxst{font-size:var(--fs-sm);color:var(--ink-500)}
.pxst b{color:var(--ink-900)}
.pxauto{display:flex;align-items:center;gap:6px;font-size:var(--fs-xs);color:var(--ink-400);cursor:pointer}
.pxmsg{font-size:var(--fs-xs);color:var(--ink-400);margin-left:auto}
.pxmsg.is-err{color:var(--j-s)}

/* ── 视图 Tab（观察池 / 持仓与计划） ─────────────────────────────── */
.vtabs{display:flex;gap:8px;margin:18px 0 0}
.vtab{appearance:none;border:1px solid var(--line);background:var(--surface);color:var(--ink-500);
  font:600 var(--fs-sm)/1 var(--font);padding:9px 22px;border-radius:999px;cursor:pointer}
.vtab.on{background:var(--brand-fill);border-color:var(--brand-fill);color:var(--on-brand)}
.vtab:not(.on):hover{color:var(--brand);border-color:var(--brand)}

/* ── 持仓与计划 ─────────────────────────────────────────────────── */
.pos-ovw{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  overflow:hidden;margin-bottom:var(--s5)}
.pos-ov{width:100%;border-collapse:collapse;font-size:var(--fs-xs)}
.pos-ov th{text-align:left;font-weight:600;color:var(--ink-500);padding:9px 12px;
  border-bottom:1px solid var(--line);background:var(--surface-2)}
.pos-ov td{padding:10px 12px;border-bottom:1px dashed var(--line-2);color:var(--ink-700)}
.pos-ov tbody tr:last-child td{border-bottom:none}
.pos-ov__nm b{display:block;color:var(--ink-900);font-size:var(--fs-sm)}
.pos-ov__row{cursor:pointer}
.pos-ov__row:hover td{background:var(--surface-2)}
.pos-ov__row:hover .pos-ov__go{color:var(--brand-fill)}
.pos-ov__go{color:var(--brand);white-space:nowrap;font-weight:600;text-align:right}
.pos-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  padding:var(--s4) var(--s5);margin-bottom:var(--s4);scroll-margin-top:16px}
.pos-card.flash{animation:posflash 1.5s}
@keyframes posflash{0%,55%{background:var(--brand-soft);border-color:var(--brand)}100%{}}
.pos-sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:var(--s4);
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  padding:var(--s4) var(--s5);margin-bottom:var(--s5)}
.pos-sum dt,.pos-card__kv dt,.pos__pl dt{font-size:var(--fs-xs);color:var(--ink-500);margin-bottom:3px}
.pos-sum dd{font-size:var(--fs-lg);font-weight:700}
.pos-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r3);
  padding:var(--s4) var(--s5);margin-bottom:var(--s4)}
.pos-card__top{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap;margin-bottom:var(--s3)}
.pos-card__id{flex:1;min-width:0}
.pos-card__id b{font-size:var(--fs-md);color:var(--ink-900)}
.posv{display:inline-block;font-size:var(--fs-xs);font-weight:700;color:var(--brand);
  background:var(--brand-soft);border-radius:var(--rp);padding:2px 10px}
.pos__open{font-size:var(--fs-xs);color:var(--ink-400)}
.pos-card__kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:var(--s4)}
.pos-card__kv dd,.pos__pl dd{font-size:var(--fs-md);font-weight:650;color:var(--ink-900)}
.pos__pl dd span{font-size:var(--fs-xs);font-weight:400;color:var(--ink-500);margin-left:6px}
.pos__chg{font-size:var(--fs-xs);font-weight:400;color:var(--ink-500);margin-left:4px}
.pos__note{font-size:var(--fs-xs);color:var(--ink-500);line-height:1.6;margin:var(--s3) 0;
  padding:var(--s2) var(--s3);background:var(--surface-2);border-radius:var(--r1)}
.pos__plan{width:100%;border-collapse:collapse;font-size:var(--fs-xs)}
.pos__plan th{text-align:left;font-weight:600;color:var(--ink-500);padding:6px 10px;
  border-bottom:1px solid var(--line)}
.pos__plan td{padding:7px 10px;border-bottom:1px dashed var(--line-2);color:var(--ink-700);line-height:1.55}
.pos__plan .pos__trg{white-space:nowrap;font-weight:600;color:var(--ink-900);width:7em}
.pos__plan tbody tr:last-child td{border-bottom:none}
.pos-empty{color:var(--ink-500);font-size:var(--fs-sm);padding:var(--s5)}

/* 判定标签（色相避开红绿） */
.tag{display:inline-block;border-radius:var(--rp);padding:2px 9px;font-size:var(--fs-xs);
  font-weight:600;white-space:nowrap}
.tag--n{background:var(--j-n-bg);color:var(--j-n)}
.tag--h{background:var(--j-h-bg);color:var(--j-h)}
.tag--s{background:var(--j-s-bg);color:var(--j-s)}

/* 价格带 */
.pb{white-space:nowrap}
.pb__c{color:var(--ink-500)}
.pb__a{color:var(--ink-300);margin:0 5px}
.pb__e{color:var(--ink-900);font-weight:700}
.pb__t{color:var(--ink-400);font-size:var(--fs-xs)}

/* 潜在空间条 */
.sp{display:flex;flex-direction:column;gap:5px;min-width:150px}
.sp__n{font-family:var(--mono);font-weight:700;font-size:var(--fs-md)}
.sp__n.is-up{color:var(--up)}.sp__n.is-down{color:var(--down)}.sp__n.is-flat{color:var(--ink-400)}
.sb{position:relative;height:7px;border-radius:var(--rp);background:var(--surface-3)}
.sb--lg{height:10px}
.sb--na{background:repeating-linear-gradient(90deg,var(--surface-3) 0 6px,transparent 6px 12px)}
.sb__z{position:absolute;top:-2px;bottom:-2px;width:1px;background:var(--ink-300)}
.sb__b{position:absolute;top:0;bottom:0;border-radius:var(--rp)}
.sb__b.is-up{background:var(--up)}
.sb__b.is-down{background:var(--down)}
.sb__b.is-flat{background:var(--ink-300)}

/* 胜率点阵 */
.win{display:flex;align-items:center;gap:6px;justify-content:center;white-space:nowrap}
.dots{display:flex;gap:2px}
.dots i{width:7px;height:12px;border-radius:2px;background:var(--dot-off);display:block}
.win--low .dots i.on{background:var(--dot-low)}
.win--mid .dots i.on{background:var(--dot-mid)}
.win--high .dots i.on{background:var(--up)}
.win__n{font-weight:700;font-size:var(--fs-sm)}
.win--low .win__n{color:var(--ink-500)}
.win--mid .win__n{color:var(--dot-mid-ink)}
.win--high .win__n{color:var(--up)}
.win__t{font-size:10px;color:var(--ink-300)}

/* 距买点 */
.gp{font-weight:700}
.gp.is-wait{color:var(--down)}
.gp.is-up{color:var(--up);font-size:var(--fs-xs)}
.lk{color:var(--brand);text-decoration:none;font-size:var(--fs-xs);font-weight:600;
  border-bottom:1px solid transparent;transition:.15s}
.lk:hover{border-bottom-color:var(--brand)}

/* ── 分区 A 卡片 ──────────────────────────────────────────────────── */
.zcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(292px,1fr));gap:var(--s4);padding:var(--s5)}
.zcard{display:flex;flex-direction:column;gap:var(--s3);background:var(--surface);
  border:1px solid var(--line);border-top:3px solid var(--up);border-radius:var(--r2);
  padding:var(--s4) var(--s4) var(--s3);box-shadow:var(--sh1);transition:.18s}
.zcard:hover{box-shadow:var(--sh2);transform:translateY(-2px)}
.zcard__top{display:flex;align-items:center;gap:var(--s2)}
.zcard__idx{width:20px;height:20px;flex:none;border-radius:var(--rp);background:var(--surface-3);
  color:var(--ink-400);font-size:10.5px;font-weight:700;display:flex;align-items:center;justify-content:center}
.zcard__id{flex:1;min-width:0}
.zcard__id b{font-size:var(--fs-lg);color:var(--ink-900);font-weight:650}
.zcard.is-fresh .zcard__id b::after{content:"NEW";font-size:9px;font-weight:700;letter-spacing:.06em;
  color:var(--brand);background:var(--brand-soft);border-radius:3px;padding:1px 4px;margin-left:6px;vertical-align:1.5px}
.zcard.is-fresh{box-shadow:inset 3px 0 0 var(--brand),var(--sh1)}
.zcard.is-fresh:hover{box-shadow:inset 3px 0 0 var(--brand),var(--sh2)}
.zcard__hero{border-top:1px dashed var(--line);border-bottom:1px dashed var(--line);
  padding:var(--s3) 0}
.zh__v{font-size:30px;font-weight:700;line-height:1.1}
.zh__v.is-up{color:var(--up)}.zh__v.is-down{color:var(--down)}
.zh__l{font-size:var(--fs-xs);color:var(--ink-500);margin:2px 0 var(--s3)}
.zcard__kv{display:grid;grid-template-columns:1fr 1fr;gap:var(--s2) var(--s3)}
.zcard__kv dt{font-size:var(--fs-xs);color:var(--ink-400)}
.zcard__kv dd{margin:1px 0 0;font-size:var(--fs-md);font-weight:650;color:var(--ink-900)}
.zcard__kv dd .pb__a{margin:0 3px}
.zcard__j{margin:0;font-size:var(--fs-xs);color:var(--ink-500);line-height:1.7;
  background:var(--surface-2);border-radius:var(--r1);padding:var(--s2) var(--s3)}
.zcard__lk{margin-top:auto;align-self:flex-start}

/* 行情更新提示（overrides.alert）：报告出具后发生的、与报告结论方向相反的行情事件。
   刻意不用红/绿——本页红绿只承担涨跌语义；此条走琥珀，与「减持」桶同族但更重。 */
.zcard__alert{margin:0;padding:8px 11px 8px 10px;background:var(--alert-bg);
  border-left:3px solid var(--alert-line);border-radius:var(--r1);
  font-size:var(--fs-xs);line-height:1.6;color:var(--alert-ink)}
.zcard__alert b{display:block;font-weight:700;font-size:var(--fs-xs);letter-spacing:.02em;
  margin-bottom:2px;color:var(--alert-ink)}
.jd .al{display:inline-block;margin-left:5px;font-size:9.5px;font-weight:700;letter-spacing:.05em;
  color:var(--alert-ink);background:var(--alert-bg);border-left:2px solid var(--alert-line);
  border-radius:2px;padding:1px 5px;cursor:help;vertical-align:1.5px}

/* ── 复核时间轴 ───────────────────────────────────────────────────── */
.tls{list-style:none;margin:0;padding:0 0 0 var(--s4);position:relative}
.tls::before{content:"";position:absolute;left:5px;top:6px;bottom:6px;width:2px;
  background:linear-gradient(var(--brand),var(--line))}
.tl{position:relative;padding:0 0 var(--s5) var(--s5)}
.tl:last-child{padding-bottom:0}
.tl__d{position:absolute;left:-15px;top:5px;width:11px;height:11px;border-radius:50%;
  background:var(--surface);border:2px solid var(--brand)}
.tl__b{border:1px solid var(--line);border-radius:var(--r2);background:var(--surface-2);
  padding:var(--s3) var(--s4)}
.tl__h{display:flex;align-items:center;gap:var(--s2)}
.tl__h b{font-size:var(--fs-md);color:var(--ink-900)}
.tl__n{font-size:var(--fs-xs);font-weight:700;color:var(--brand);background:var(--brand-soft);
  border-radius:var(--rp);padding:1px 8px}
.tl__w{font-size:var(--fs-sm);color:var(--ink-500);margin-top:4px;line-height:1.75}
.tl__x{font-size:var(--fs-xs);color:var(--ink-400);margin-top:5px}
.tl__x b{color:var(--ink-900)}

/* ── notes / footer ───────────────────────────────────────────────── */
details.notes{border:1px solid var(--line);border-radius:var(--r2);background:var(--surface-2)}
details.notes>summary{padding:var(--s3) var(--s4);font-size:var(--fs-md);font-weight:650;
  color:var(--ink-900);cursor:pointer;list-style:none}
details.notes>summary::-webkit-details-marker{display:none}
details.notes>summary::before{content:"▸ ";color:var(--brand)}
details.notes[open]>summary::before{content:"▾ "}
.notes__b{padding:0 var(--s4) var(--s4);border-top:1px solid var(--line-2)}
.notes__b dl{margin:var(--s3) 0 0;font-size:var(--fs-sm);line-height:1.9}
.notes__b dt{font-weight:650;color:var(--ink-900);margin-top:var(--s3)}
.notes__b dd{margin:2px 0 0;color:var(--ink-500)}
.notes__b code{font-family:var(--mono);font-size:var(--fs-xs);background:var(--surface-3);
  border-radius:3px;padding:1px 5px;color:var(--ink-700)}
.tok{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:var(--s2);margin-top:var(--s3)}
.tok>div{border:1px solid var(--line);border-radius:var(--r1);padding:var(--s2) var(--s3);background:var(--surface)}
.tok span{display:block;font-family:var(--mono);font-size:10.5px;color:var(--ink-400)}
.tok b{font-size:var(--fs-sm);color:var(--ink-900)}
.sw{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.foot{margin-top:var(--s6);padding-top:var(--s4);border-top:1px solid var(--line);
  font-size:var(--fs-xs);color:var(--ink-400);line-height:1.95}
</style>
<script>/* 提前套用配色档位，避免深色档先闪一下浅色（FOUC）。
   std 档无独立覆盖规则，setAttribute 后继承 :root 默认值即该档效果。
   键值兼容：首版的 soft / std 两档已合并为「标准」，旧值一律落到 std。 */
(function(){try{var m={soft:'std',eye:'eye',std:'std',dark:'dark'};
var t=m[localStorage.getItem('wl-theme')];if(t){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();</script>
<script>/* 视图 Tab：持仓与计划（默认）/ 观察池。选择存 localStorage（键 wl-view2），点击切换在此。 */
(function(){
  function show(v){
    document.getElementById('view-pool').hidden = (v !== 'pool');
    document.getElementById('view-pos').hidden = (v !== 'pos');
    Array.prototype.forEach.call(document.querySelectorAll('.vtab'), function(b){
      var on = b.getAttribute('data-v') === v;
      b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    try{localStorage.setItem('wl-view2', v);}catch(e){}
  }
  document.addEventListener('click', function(e){
    var b = e.target.closest ? e.target.closest('.vtab') : null;
    if(b){ show(b.getAttribute('data-v')); return; }
    var tr = e.target.closest ? e.target.closest('.pos-ov__row') : null;
    if(tr){
      var card = document.getElementById('pos-' + tr.getAttribute('data-code'));
      if(card){
        card.scrollIntoView({behavior:'smooth', block:'start'});
        card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash');
      }
    }
  });
  document.addEventListener('DOMContentLoaded', function(){
    var v = 'pos';
    try{ v = localStorage.getItem('wl-view2') || 'pos'; }catch(e){}
    show(v);
  });
})();</script>
</head>
<body>
<div class="page">

<header class="mast">
  <div class="mast__eyebrow">OBSERVATION POOL · DECISION COCKPIT</div>
  <h1 class="mast__title">投资观察池</h1>
  <p class="mast__sub">
    覆盖 <b>@@N@@</b> 只标的 ｜ @@ASOF_LABEL@@ <b>@@ASOF@@</b>@@PX_SEG@@ ｜ 来源：资料库「投资」空间内各标的<strong>最新一版</strong>分析报告<br>
    台账口径：期望价为报告内「折现 + 概率加权」结果；建仓门槛为 潜在空间 ≥ +15% 且买入胜率 ≥ 30%
  </p>
  <div class="tt" role="group" aria-label="配色档位">
    <button type="button" class="tt__b" data-t="std" aria-pressed="true">标准</button><button type="button" class="tt__b" data-t="eye" aria-pressed="false">护眼</button><button type="button" class="tt__b" data-t="dark" aria-pressed="false">深色</button>
  </div>
</header>

<div class="pxbar" id="pxbar">
  <button type="button" class="pxbtn" id="px-refresh">↻ 刷新现价</button>
  <span class="pxst" id="px-status">现价为 <b>@@PX_SNAP@@</b> 快照 · 点左侧按钮可拉实时行情并重算全部派生统计</span>
  <label class="pxauto"><input type="checkbox" id="px-auto"> 交易时段每 60s 自动刷新</label>
  <span class="pxmsg" id="px-msg"></span>
</div>

<nav class="vtabs" role="tablist" aria-label="视图切换">
  <button type="button" class="vtab on" data-v="pos" aria-pressed="true">持仓与计划</button>
  <button type="button" class="vtab" data-v="pool" aria-pressed="false">观察池</button>
</nav>

<div id="view-pool">
<section class="verdict">
  <span class="verdict__ico">i</span>
  <p class="verdict__t" id="verdict-t">@@VERDICT@@</p>
</section>

<div class="kpis">@@KPIS@@</div>

<section class="panel">
  <div class="panel__head">
    <span class="panel__no">01</span>
    <h2 class="panel__t">全池总览</h2>
    <span class="panel__d">先看分布，再看名单</span>
  </div>
  <div class="panel__body">
    <div class="vizs">
      @@VIZ_SPACE@@
      @@VIZ_MATRIX@@
    </div>
    @@COMP@@
  </div>
</section>

<section class="panel">
  <div class="panel__head">
    <span class="panel__no">02</span>
    <h2 class="panel__t">分区台账</h2>
    <span class="panel__d">按可操作性分区 · 区内按潜在空间降序</span>
  </div>
  <div class="bar">
    @@CHIPS@@
    <span class="sep"></span>
    <button class="sbtn on desc" data-key="up">潜在空间</button>
    <button class="sbtn" data-key="win">胜率</button>
    <button class="sbtn" data-key="gap">距买点</button>
    <span class="sep"></span>
    <input type="search" id="q" placeholder="搜索名称 / 代码 / 判定…">
    <span class="grow"></span>
    <span class="hint">命中 <b id="hit">@@N@@</b> 只 · 点分区标题可折叠</span>
  </div>
  @@ZONES@@
</section>

<section class="panel">
  <div class="panel__head">
    <span class="panel__no">03</span>
    <h2 class="panel__t">复核时间轴</h2>
    <span class="panel__d">按报告有效期归集 · 到期前须重跑验证点</span>
  </div>
  <div class="panel__body">
    @@CALENDAR@@
  </div>
</section>
</div>

<div id="view-pos" hidden>
<section class="panel">
  <div class="panel__head">
    <span class="panel__no">P</span>
    <h2 class="panel__t">持仓与后期计划</h2>
    <span class="panel__d">实际持仓口径 · 现价与观察池行情联动 · 计划为既定纪律非即时建议</span>
  </div>
  <div class="panel__body">
    @@POSITIONS@@
  </div>
</section>
</div>

<section class="panel">
  <div class="panel__head">
    <span class="panel__no">04</span>
    <h2 class="panel__t">口径与设计说明</h2>
    <span class="panel__d">读数前必看</span>
  </div>
  <div class="panel__body">
    <details class="notes" open>
      <summary>指标口径 · 数据边界 · 与上一版（v1）的差异</summary>
      <div class="notes__b">
        <dl>
          <dt>潜在空间</dt>
          <dd>= 加权期望价 ÷ 现价 − 1。正为红（上行空间）、负为绿（现价已高于期望价）。全页仅此一处使用红绿，A 股惯例：红涨绿跌。</dd>
          <dt>距买点</dt>
          <dd>= 观察买点<strong>上界</strong> ÷ 现价 − 1，即「还需回调多少才进入报告给出的买点区间」。本页新增的派生字段，用于回答「现在离能动手还有多远」。</dd>
          <dt>买入胜率</dt>
          <dd>= 报告情景中「情景价 ≥ 现价 × 1.15」的概率之和。&lt; 30% 记低（灰）、30%–49% 记中（琥珀）、≥ 50% 记高（红）。</dd>
          <dt>判定与分区的区别</dt>
          <dd>判定是报告原文结论；分区是本页按可操作性所做的排布。<strong>「贴近买点」区按潜在空间 ≥ 0 划分，跨判定桶</strong>——例如科沃斯判定为回避，但期望价 51.86 &gt; 现价 47.80，故归入 A 区，其矛盾本身就是需要关注的信息。判定标签的<strong>文字取自报告结论原文的首个结论词，底色才代表三桶归类</strong>（回避 = 灰蓝 / 观察 = 靛蓝 / 减持 = 琥珀）；同色标签的文字可能不同，以文字为准。</dd>
          <dt>数据边界</dt>
          <dd>B 类为早期「首次覆盖报告」，无期望价与胜率字段，仅列评级与机构目标价；A 类为方法论全管线报告。表中数值一律取自报告原文，报告未给出者留空，<strong>不在渲染层做任何估算</strong>（唯一例外：经人工维护为「报告之后最新收盘价」的现价字段，见下方「行情更新」条）。标「NEW」为本轮新分析（报告日 ≥ @@FRESH_FROM@@）。</dd>
          @@PX_DL@@
          <dt>变化高亮</dt>
          <dd>与上一期快照比对，判定 / 期望价 / 胜率发生变动时，判定下方显示黄色标记，悬停可看上期判定。</dd>
          <dt>行情更新（琥珀条 · 现价维护）</dt>
          <dd>报告出具<strong>之后</strong>发生的行情事实（含与报告结论方向相反者），单独用琥珀条标出，条内自带日期、触发条件与规定动作。这是全页唯一允许引用「报告原文之外」数据的地方，分两种落法：<strong>①只提示不改数</strong>——现价 / 期望价 / 胜率 / 报告日期全部保持报告快照，条内只陈述行情与报告里已经写死的规则；<strong>②维护为最新价</strong>——经人工确认后把该标的<strong>现价</strong>覆盖为报告之后的最新收盘价，则现价、潜在空间、距买点随之按新价重算，而<strong>期望价 / 胜率 / 判定 / 报告日期仍是报告原值</strong>。因此同一卡片上「现价时点」可能晚于「报告日期」，这是刻意的——读潜在空间时须知道分母已是新价；条内会写明「现价已维护为 ……」。条内不用红绿，避免与涨跌语义抢占；出现琥珀条时，以条为准。</dd>
          <dt>配色档位</dt>
          <dd>右上角可切换三档：<strong>标准</strong>（默认，卡面 #f8fafc 而非纯白，明快不刺眼）、<strong>护眼</strong>（暖纸调、压低蓝光，长时间阅读）、<strong>深色</strong>（夜间盯盘）。选择记在本地浏览器，下次打开保持。三档共用同一套语义色逻辑——红绿只服务涨跌，判定三桶走 slate / indigo / amber，<strong>换档不改变任何含义</strong>。</dd>
          <dt>与 v1 的三处设计差异</dt>
          <dd>
            ① <strong>语义色解耦</strong>：v1 中 <code>#c62828</code> 同时表示「回避」与「下跌」，两套语义抢同一支红；本版红绿只服务涨跌，判定改用 slate / indigo / amber，色相与红绿不重叠。<br>
            ② <strong>信息架构</strong>：v1 把 51 行按「不买 → 中性 → 减持」平铺，正空间的 5 只被压在 32 行名单里；本版先给结论与世界分布，再按可操作性分区。<br>
            ③ <strong>字号收敛</strong>：v1 用了 13 / 12.5 / 12 / 11.5 / 11 / 10.5 / 10 共 7 档字号，本版收敛为 6 档，并统一为 tabular-nums 等宽数字以对齐数位。
          </dd>
        </dl>
        <div class="tok">
          <div><span>--up / --down</span><b><i class="sw" style="background:var(--up)"></i>涨 <i class="sw" style="background:var(--down)"></i>跌</b></div>
          <div><span>--j-n 回避</span><b><i class="sw" style="background:var(--j-n)"></i>slate</b></div>
          <div><span>--j-h 观察</span><b><i class="sw" style="background:var(--j-h)"></i>indigo</b></div>
          <div><span>--j-s 减持</span><b><i class="sw" style="background:var(--j-s)"></i>amber</b></div>
          <div><span>--alert-line 行情更新</span><b><i class="sw" style="background:var(--alert-line)"></i>amber 深</b></div>
          <div><span>--brand 强调</span><b><i class="sw" style="background:var(--brand)"></i>随档位</b></div>
          <div><span>字号 6 档</span><b>11.5 → 32px</b></div>
        </div>
      </div>
    </details>
  </div>
</section>

<div class="foot">
  本台账仅供参考，不构成投资建议。股市有风险，投资需谨慎。<br>
  数据源：资料库「投资」空间内各标的报告（A 类为方法论全管线报告，B 类为早期首次覆盖报告）；@@PX_FOOT@@<br>
  生成方式：由各报告结论区自动抽取 + 人工核对；期望价与胜率口径见各报告原文。单文件离线渲染，零外部依赖。
</div>

</div>

<script>
(function(){
  var rows = Array.prototype.slice.call(document.querySelectorAll('[data-row]'));
  var st = {zone:'all', q:'', key:'up', dir:-1};

  function valOf(el){
    var v = el.getAttribute('data-' + st.key);
    if(v === null || v === '') return null;
    var f = parseFloat(v);
    return isNaN(f) ? null : f;
  }
  function renumber(){
    Array.prototype.slice.call(document.querySelectorAll('table.wl tbody')).forEach(function(tb){
      Array.prototype.slice.call(tb.rows).forEach(function(tr, i){
        var c = tr.querySelector('.idx'); if(c) c.textContent = i + 1;
      });
    });
    Array.prototype.slice.call(document.querySelectorAll('.zcards')).forEach(function(g){
      Array.prototype.slice.call(g.children).forEach(function(c, i){
        var e = c.querySelector('.zcard__idx'); if(e) e.textContent = i + 1;
      });
    });
  }
  function sorter(a, b){
    var x = valOf(a), y = valOf(b);
    if(x === null && y === null) return 0;
    if(x === null) return 1;
    if(y === null) return -1;
    return (x - y) * st.dir;
  }
  function sortAll(){
    Array.prototype.slice.call(document.querySelectorAll('table.wl tbody')).forEach(function(tb){
      Array.prototype.slice.call(tb.rows).sort(sorter).forEach(function(tr){ tb.appendChild(tr); });
    });
    Array.prototype.slice.call(document.querySelectorAll('.zcards')).forEach(function(g){
      Array.prototype.slice.call(g.children).sort(sorter).forEach(function(c){ g.appendChild(c); });
    });
    renumber();
  }
  function apply(){
    var q = st.q.toLowerCase();
    rows.forEach(function(el){
      var ok = true;
      if(st.zone === 'pos') ok = el.getAttribute('data-pos') === '1';
      else if(st.zone === 'fresh') ok = el.getAttribute('data-fresh') === '1';
      else if(st.zone !== 'all') ok = el.getAttribute('data-b') === st.zone;
      if(ok && q) ok = (el.getAttribute('data-k') || '').toLowerCase().indexOf(q) >= 0;
      if(ok) el.removeAttribute('hidden'); else el.setAttribute('hidden', '');
    });
    Array.prototype.slice.call(document.querySelectorAll('.zone')).forEach(function(z){
      var vis = Array.prototype.slice.call(z.querySelectorAll('[data-row]'))
        .filter(function(e){ return !e.hasAttribute('hidden'); });
      z.classList.toggle('is-empty', vis.length === 0);
      var n = z.querySelector('.zone__n'); if(n) n.textContent = vis.length;
    });
    var tot = rows.filter(function(e){ return !e.hasAttribute('hidden'); }).length;
    var t = document.getElementById('hit'); if(t) t.textContent = tot;
  }

  Array.prototype.slice.call(document.querySelectorAll('.chip')).forEach(function(b){
    b.addEventListener('click', function(){
      Array.prototype.slice.call(document.querySelectorAll('.chip')).forEach(function(x){ x.classList.remove('on'); });
      b.classList.add('on'); st.zone = b.getAttribute('data-zone-filter'); apply();
    });
  });
  var inp = document.getElementById('q');
  if(inp) inp.addEventListener('input', function(){ st.q = inp.value || ''; apply(); });
  Array.prototype.slice.call(document.querySelectorAll('.sbtn')).forEach(function(b){
    b.addEventListener('click', function(){
      var k = b.getAttribute('data-key');
      if(st.key === k){ st.dir = -st.dir; } else { st.key = k; st.dir = -1; }
      Array.prototype.slice.call(document.querySelectorAll('.sbtn')).forEach(function(x){
        x.classList.remove('on', 'asc', 'desc');
      });
      b.classList.add('on'); b.classList.add(st.dir < 0 ? 'desc' : 'asc');
      sortAll();
    });
  });
  Array.prototype.slice.call(document.querySelectorAll('.zone__head')).forEach(function(h){
    h.addEventListener('click', function(){ h.parentNode.classList.toggle('is-collapsed'); });
  });

  sortAll(); apply();
  /* 行情刷新重算完 data-up / data-gap / data-pos 后要重排与重筛，
     故把这两个动作暴露出去（2026-10-23 新增，供下方行情模块调用）。 */
  window.__wlSort = function(){ sortAll(); apply(); };

  /* ── 配色档位切换 ────────────────────────────────────────────────
     与 head 里的预置脚本共用同一 localStorage 键（wl-theme）。
     std 档不写覆盖规则，直接继承 :root 的默认值。                 */
  (function(){
    var KEY = 'wl-theme';
    var bts = Array.prototype.slice.call(document.querySelectorAll('.tt__b'));
    if(!bts.length) return;
    function mark(t){
      bts.forEach(function(b){
        b.setAttribute('aria-pressed', b.getAttribute('data-t') === t ? 'true' : 'false');
      });
    }
    bts.forEach(function(b){
      b.addEventListener('click', function(){
        var t = b.getAttribute('data-t');
        document.documentElement.setAttribute('data-theme', t);
        mark(t);
        try{ localStorage.setItem(KEY, t); }catch(e){}
      });
    });
    mark(document.documentElement.getAttribute('data-theme') || 'std');
  })();
})();
</script>
<script>
/* 数据模型：供下方刷新模块消费。用 JS 赋值而非 type="application/json" ——
   后者的内容会被静态检查当成 JS 编译而误报语法错。 */
var WL_MODEL = @@PX_MODEL@@;</script>
<script>
/* ══ 行情刷新（2026-10-23）══════════════════════════════════════════════
   台账是离线单文件，不能起后端。取价走腾讯行情 qt.gtimg.cn：它返回的是
   `v_sh600415="1~名称~代码~现价~…"` 这种 JS 赋值，用 script 标签加载即执行，
   天然绕过 CORS（fetch 会被挡，因为对方不返 Access-Control-Allow-Origin）。

   实测结论（2026-10-23，headless Edge）：
     · 四板块前缀均可用：sh / sz / hk（5 位）/ bj；
     · 单批 30 只约 150ms 返回；
     · 资料库页面 CSP 的 script-src 白名单含 *.gtimg.cn，线上同样放行；
     · 现价在 split('~')[3]，涨跌幅 [32]，行情时间 [30]。

   🔴 刷新必须重算全部派生值，不能只改现价那一格 —— 顶部 verdict、KPI、
      分布柱、赔率矩阵、分区 chips、A 区结语、排序、持仓市值浮盈都吃现价，
      只改一格会让页面自相矛盾（2026-10-12 已踩过一次）。
   🔴 文案不在此处另写：模板串来自 Python 的 TPL_BAG，这里只做数字替换。
   🔴 分区归属（A / H / N / S）是快照口径，刷新不重新分区；若 A 区有卡片
      空间转负，结语会显式写出「另有 N 只空间已转负」，不静默说谎。
   ═══════════════════════════════════════════════════════════════════ */
(function(){
  var M = window.WL_MODEL;
  if(!M || !M.rows) return;
  var C = M.const, T = M.tpl;
  var BTN = document.getElementById('px-refresh'),
      ST  = document.getElementById('px-status'),
      MSG = document.getElementById('px-msg'),
      AUTO= document.getElementById('px-auto');
  var PX = {}, timer = null, busy = false;

  /* 初始化：以渲染时快照价为起点，未取到的标的一直用快照价 */
  (function(){
    var i, r, p;
    for(i = 0; i < M.rows.length; i++){
      r = M.rows[i];
      var v = parseFloat(r.p);
      PX[r.c] = { px: isNaN(v) ? 0 : v, str: r.p, chg: null };
    }
    for(var k in M.pos){
      if(!M.pos.hasOwnProperty(k)) continue;
      p = M.pos[k];
      if(!PX[k] || !PX[k].px){
        PX[k] = { px: p.px0 || 0, str: p.px0 ? p.px0.toFixed(2) : '—', chg: null };
      }
    }
  })();

  /* ── 与 Python px_secid() 同规则，改动须两处同步 ───────────────── */
  function secid(code){
    var c = String(code || '').toUpperCase();
    if(c.slice(-3) === '.HK'){
      var h = c.replace(/\D/g, '');
      while(h.length < 5){ h = '0' + h; }
      return 'hk' + h;
    }
    var d = c.replace(/\D/g, '');
    if(!d) return '';
    if(d.indexOf('920') === 0 || d.charAt(0) === '4' || d.charAt(0) === '8') return 'bj' + d;
    if(d.charAt(0) === '6' || d.charAt(0) === '9') return 'sh' + d;
    return 'sz' + d;
  }
  function fmtPct(v){
    if(v === null || v === undefined) return '—';
    return (v > 0 ? '+' : (v < 0 ? '-' : '')) + Math.abs(v).toFixed(1) + '%';
  }
  function r1(x){ return Math.round(x * 10) / 10; }
  function signN(v, d){ return (v >= 0 ? '+' : '') + v.toFixed(d); }
  function sub(t, o){
    return String(t).replace(/\{(\w+)\}/g, function(m, k){
      return (o[k] === undefined || o[k] === null) ? m : o[k];
    });
  }
  function q1(sel){ return document.querySelector(sel); }
  function qa(sel){ return Array.prototype.slice.call(document.querySelectorAll(sel)); }

  /* ── 逐行数值刷新 ─────────────────────────────────────────────── */
  function drawBar(el, v){
    var span = C.smax - C.smin, zero = C.zero;
    var base = 'sb' + (el.className.indexOf('sb--lg') >= 0 ? ' sb--lg' : '');
    var z = '<i class="sb__z" style="left:' + zero.toFixed(2) + '%"></i>';
    if(v === null || v === undefined){
      el.className = base + ' sb--na';
      el.innerHTML = z;
      return;
    }
    var c = Math.max(C.smin, Math.min(C.smax, v)), left, width, tone;
    if(c >= 0){ left = zero; width = c / span * 100; tone = c > 0 ? 'is-up' : 'is-flat'; }
    else { width = (-c) / span * 100; left = zero - width; tone = 'is-down'; }
    el.className = base;
    el.innerHTML = z + '<span class="sb__b ' + tone + '" style="left:' + left.toFixed(2) +
      '%;width:' + Math.max(width, 1.0).toFixed(2) + '%"></span>';
  }
  function setGap(el, g){
    var fb = el.getAttribute('data-fb') || '';
    if(g === null || g === undefined){ el.className = fb; el.textContent = '—'; return; }
    if(fb.indexOf('gp') >= 0){
      if(g >= 0){ el.className = 'gp is-up'; el.textContent = '已在区间'; }
      else { el.className = 'gp is-wait n'; el.textContent = fmtPct(g); }
    } else {
      el.className = fb;
      el.textContent = (g >= 0) ? '已在区间' : '需回调 ' + Math.abs(g).toFixed(1) + '%';
    }
  }
  function patchRow(el, r){
    el.setAttribute('data-up', (r.u === null || r.u === undefined) ? '' : r.u);
    el.setAttribute('data-gap', (r.g === null || r.g === undefined) ? '' : r.g);
    el.setAttribute('data-pos', (r.u !== null && r.u >= 0) ? '1' : '0');
    var pxEl = el.querySelector('[data-f="px"]');
    if(pxEl && r.p) pxEl.textContent = r.p;
    var upEl = el.querySelector('[data-f="up"]');
    if(upEl){
      var fb = upEl.getAttribute('data-fb') || '';
      var tone = (r.u !== null && r.u > 0) ? 'is-up'
               : ((r.u !== null && r.u < 0) ? 'is-down' : 'is-flat');
      if(fb.indexOf('zh__v') >= 0) tone = (r.u !== null && r.u >= 0) ? 'is-up' : 'is-down';
      upEl.className = (fb ? fb + ' ' : '') + tone;
      upEl.textContent = fmtPct(r.u);
    }
    var bar = el.querySelector('[data-f="bar"]');
    if(bar) drawBar(bar, r.u);
    var gp = el.querySelector('[data-f="gap"]');
    if(gp) setGap(gp, r.g);
  }

  /* ── 聚合重算 ─────────────────────────────────────────────────── */
  function recount(){
    var R = M.rows, i, r, n = R.length;
    var nq = 0, npos = 0, npass = 0, nw30 = 0, nw30pos = 0;
    var aN = 0, aOk = 0, aHi = 0, aIn = 0, aNeg = 0, aGain = 0;
    for(i = 0; i < n; i++){
      r = R[i];
      var hasU = (r.u !== null && r.u !== undefined);
      var hasW = (r.w !== null && r.w !== undefined);
      if(hasU) nq++;
      if(hasU && r.u >= 0) npos++;
      if(hasW && r.w >= 30){
        nw30++;
        if(hasU && r.u >= 0) nw30pos++;
        if(hasU && r.u >= 15) npass++;
      }
      if(r.z === 'A'){
        aN++;
        if(hasW && r.w >= 30){ aHi++; if(hasU && r.u >= 15) aOk++; }
        if(r.g !== null && r.g !== undefined && r.g >= 0) aIn++;
        if(hasU && r.u < 0) aNeg++;
      } else if(hasU && r.u >= 0){
        aGain++;
      }
    }
    return {n:n, nq:nq, npos:npos, npass:npass, nw30:nw30, nw30pos:nw30pos,
            aN:aN, aOk:aOk, aHi:aHi, aIn:aIn, aNeg:aNeg, aGain:aGain};
  }

  function fillAll(){
    var s = recount(), i, j, el;

    /* ① 结论条 */
    el = document.getElementById('verdict-t');
    if(el){
      if(s.npass){
        el.innerHTML = sub(T.vpass, s);
      } else {
        var tail = s.nw30pos ? sub(T.vtail1, s) : sub(T.vtail0, s);
        el.innerHTML = sub(T.vzero, {n:s.n, nq:s.nq, npos:s.npos, tail:tail});
      }
    }
    /* ② KPI */
    el = q1('[data-agg="kpi-pos-v"]'); if(el) el.textContent = s.npos;
    el = q1('[data-agg="kpi-pos-h"]');
    if(el) el.innerHTML = s.npass ? sub(T.hintp, s) : T.hintp0;
    el = q1('[data-agg="kpi-w30-h"]');
    if(el) el.innerHTML = s.nw30pos ? sub(T.hintw, s) : T.hintw0;
    /* ③ chips */
    el = q1('[data-agg="chip-pos"]'); if(el) el.textContent = s.npos;

    /* ④ 潜在空间分布 */
    var BK = [[0, 1e9], [-5, 0], [-10, -5], [-15, -10], [-20, -15], [-30, -20], [-1e9, -30]];
    var tal = [0, 0, 0, 0, 0, 0, 0], mx = 1;
    for(i = 0; i < M.rows.length; i++){
      var v = M.rows[i].u;
      if(v === null || v === undefined) continue;
      for(j = 0; j < BK.length; j++){ if(v >= BK[j][0] && v < BK[j][1]){ tal[j]++; break; } }
    }
    for(j = 0; j < tal.length; j++){ if(tal[j] > mx) mx = tal[j]; }
    for(j = 0; j < tal.length; j++){
      el = q1('[data-agg="dist-b' + j + '"]');
      if(el) el.style.height = (tal[j] / mx * 100).toFixed(1) + '%';
      el = q1('[data-agg="dist-n' + j + '"]');
      if(el) el.textContent = tal[j];
    }
    el = q1('[data-agg="spfoot"]');
    if(el) el.innerHTML = s.npass ? sub(T.spfoot, s) : T.spfoot0;

    /* ⑤ 赔率矩阵 */
    var WR = [[30, 1e9], [25, 30], [-1e9, 25]], CD = [[0, 1e9], [-10, 0], [-20, -10], [-1e9, -20]];
    var colT = [0, 0, 0, 0], pool = 0;
    for(i = 0; i < M.rows.length; i++){
      var rr = M.rows[i];
      if(rr.u === null || rr.u === undefined || rr.w === null || rr.w === undefined) continue;
      pool++;
    }
    for(i = 0; i < WR.length; i++){
      var rt = 0;
      for(j = 0; j < CD.length; j++){
        var cnt = 0;
        for(var k = 0; k < M.rows.length; k++){
          var rk = M.rows[k];
          if(rk.u === null || rk.u === undefined || rk.w === null || rk.w === undefined) continue;
          if(rk.w >= WR[i][0] && rk.w < WR[i][1] && rk.u >= CD[j][0] && rk.u < CD[j][1]) cnt++;
        }
        rt += cnt; colT[j] += cnt;
        el = q1('[data-agg="mxd-' + i + '-' + j + '"]');
        if(el){
          el.className = 'mx__c ' + (cnt === 0 ? 'is-z' : (cnt <= 2 ? 'is-1' : (cnt <= 5 ? 'is-2' : 'is-3'))) + ' n';
          el.textContent = cnt ? cnt : '·';
        }
      }
      el = q1('[data-agg="mxrt-' + i + '"]'); if(el) el.textContent = rt;
    }
    for(j = 0; j < colT.length; j++){
      el = q1('[data-agg="mxct-' + j + '"]'); if(el) el.textContent = colT[j];
    }
    el = q1('[data-agg="mxgt"]'); if(el) el.textContent = pool;
    el = q1('[data-agg="mxfoot"]');
    if(el){
      var hiN = countHi();
      el.innerHTML = hiN ? sub(T.mxfoot, {hi:hiN}) : T.mxfoot0;
    }

    /* ⑥ A 区结语 */
    el = q1('[data-agg="zdesc"]');
    if(el){
      var desc = s.aIn ? sub(T.zdesc_in, {nin:s.aIn}) : T.zdesc_out;
      if(s.aNeg) desc += sub(T.zdesc_neg, {nneg:s.aNeg});
      if(s.aGain) desc += sub(T.zdesc_gain, {ngain:s.aGain});
      el.textContent = desc;
    }
    el = q1('[data-agg="znote"]');
    if(el){
      el.textContent = s.aOk ? sub(T.znote_ok, {nok:s.aOk, rest:Math.max(0, s.aHi - s.aOk)})
                    : (s.aHi ? sub(T.znote_hi, {nhi:s.aHi}) : T.znote_no);
    }
  }
  function countHi(){
    var c = 0, i, r;
    for(i = 0; i < M.rows.length; i++){
      r = M.rows[i];
      if(r.u !== null && r.u !== undefined && r.u >= 0 && r.w !== null && r.w >= 30) c++;
    }
    return c;
  }

  /* ── 持仓 Tab ─────────────────────────────────────────────────── */
  function patchPositions(){
    var totalMv = 0, totalCost = 0, negMv = 0, anyCost = false, negList = [], k, p, q, px, mv, pl, plp, el, row;
    for(k in M.pos){
      if(!M.pos.hasOwnProperty(k)) continue;
      p = M.pos[k]; q = PX[k] || {px:p.px0 || 0, str:'—', chg:null};
      px = q.px || 0;
      if(!px) continue;
      mv = p.s * px;
      totalMv += mv;
      var want = (p.c !== null && p.c !== undefined);
      if(want){ totalCost += p.c * p.s; anyCost = true; }
      else { negMv += mv; negList.push({t:(p.n || k), mv:mv, cur:(p.cur || '元')}); }
      var scopes = [];
      row = q1('.pos-ov__row[data-code="' + k + '"]');
      if(row) scopes.push(row);
      var card = document.getElementById('pos-' + k);
      if(card) scopes.push(card);
      for(var t = 0; t < scopes.length; t++){
        el = scopes[t].querySelector('[data-f="px"]');
        if(el) el.textContent = q.str;
        el = scopes[t].querySelector('[data-f="pxw"]');
        if(el){
          var chgEl = el.querySelector('.pos__chg');
          el.innerHTML = '<span data-f="px" data-fb="">' + q.str + '</span>' +
            (chgEl ? ' <span class="pos__chg">今日 ' +
              (q.chg === null ? '—' : q.chg.toFixed(2)) + '%</span>' : '');
        }
        el = scopes[t].querySelector('[data-f="mv"]');
        if(el) el.textContent = Math.round(mv) + ' ' + (p.cur || '元');
        if(want){
          el = scopes[t].querySelector('[data-f="pl"]');
          if(el){
            pl = mv - p.c * p.s;
            plp = (px / p.c - 1) * 100;
            var tone = pl >= 0 ? 'is-up' : 'is-down';
            if(el.querySelector('[data-f="plv"]')){
              el.className = tone + ' n';
              el.innerHTML = signN(plp, 1) + '% <span data-f="plv">' +
                signN(Math.round(pl), 0) + ' 元</span>';
            } else {
              el.innerHTML = '<span class="' + tone + ' n">' + signN(plp, 1) + '%</span>';
            }
          }
        }
      }
    }
    el = q1('[data-f="sum-mv"]');
    if(el) el.textContent = Math.round(totalMv) + ' 元';
    el = q1('[data-f="sum-pl"]');
    if(el && anyCost){
      var spl = totalMv - totalCost;
      // 说明节点会被下面的 textContent 清掉 → 先留引用、写完再挂回去
      var noteEl = el.querySelector('[data-f="sum-plnote"]');
      el.className = 'n ' + (spl >= 0 ? 'is-up' : 'is-down');
      el.textContent = signN(Math.round(spl), 0) + ' 元';
      if(noteEl){
        noteEl.textContent = '（负成本仓 ' + Math.round(negMv) + ' 元全额计入）';
        el.appendChild(noteEl);
      }
    }
    // 利润仓市值随刷新重算；排序按市值降序，与静态渲染口径一致
    el = q1('[data-f="sum-profit"]');
    if(el){
      negList.sort(function(a, b){ return b.mv - a.mv; });
      el.textContent = negList.length
        ? negList.map(function(x){ return x.t + ' ' + Math.round(x.mv) + ' ' + x.cur; }).join(' · ')
        : '—';
    }
  }

  /* ── 取价 ─────────────────────────────────────────────────────── */
  function loadQuotes(codes, done){
    var batches = [], i, got = {}, left = 0, failed = 0;
    for(i = 0; i < codes.length; i += 30) batches.push(codes.slice(i, i + 30));
    if(!batches.length){ done(got, 0); return; }
    left = batches.length;
    function settle(ok){
      if(!ok) failed++;
      left--;
      if(left === 0) done(got, failed);
    }
    batches.forEach(function(b){
      var s = document.createElement('script');
      s.charset = 'gbk';
      var ids = b.map(secid);
      s.src = 'https://qt.gtimg.cn/q=' + ids.join(',');
      var done1 = false;
      function once(ok){ if(done1) return; done1 = true; settle(ok); }
      s.onload = function(){
        for(var j = 0; j < b.length; j++){
          var raw = window['v_' + ids[j]];
          if(!raw) continue;
          var f = String(raw).split('~');
          var px = parseFloat(f[3]);
          if(!px || px <= 0) continue;
          got[b[j]] = { px: px, str: px.toFixed(2), ts: f[30] || '',
                        chg: isNaN(parseFloat(f[32])) ? null : parseFloat(f[32]) };
        }
        once(true);
      };
      s.onerror = function(){ once(false); };
      setTimeout(function(){ once(false); }, 9000);
      document.head.appendChild(s);
    });
  }
  function applyQuotes(got){
    var k, updated = 0, i, r;
    for(k in got){
      if(!got.hasOwnProperty(k)) continue;
      if(!PX[k]) PX[k] = { px:0, str:'—', chg:null };
      PX[k].px = got[k].px; PX[k].str = got[k].str;
      PX[k].chg = got[k].chg; PX[k].ts = got[k].ts;
      updated++;
    }
    for(i = 0; i < M.rows.length; i++){
      r = M.rows[i];
      var q = PX[r.c];
      if(!q || !q.px) continue;
      r.p = q.str;
      r.u = r.e ? r1((r.e / q.px - 1) * 100) : null;
      r.g = (r.h !== null && r.h !== undefined) ? r1((r.h / q.px - 1) * 100) : null;
      qa('[data-row][data-code="' + r.c + '"]').forEach(function(el){ patchRow(el, r); });
    }
    return updated;
  }

  /* ── 交互 ─────────────────────────────────────────────────────── */
  function stamp(){
    var latest = '', k;
    for(k in PX){
      if(!PX[k] || !PX[k].ts) continue;
      if(PX[k].ts > latest) latest = PX[k].ts;
    }
    if(latest && latest.length >= 14){
      return latest.slice(0, 4) + '-' + latest.slice(4, 6) + '-' + latest.slice(6, 8) + ' ' +
             latest.slice(8, 10) + ':' + latest.slice(10, 12);
    }
    return '刚刚';
  }
  function refresh(manual){
    if(busy) return;
    busy = true;
    if(BTN) BTN.disabled = true;
    if(MSG){ MSG.className = 'pxmsg'; MSG.textContent = '正在获取行情…'; }
    var codes = M.rows.map(function(r){ return r.c; });
    for(var k in M.pos){ if(M.pos.hasOwnProperty(k) && codes.indexOf(k) < 0) codes.push(k); }
    loadQuotes(codes, function(got, failed){
      busy = false;
      if(BTN) BTN.disabled = false;
      var n = 0, kk;
      for(kk in got){ if(got.hasOwnProperty(kk)) n++; }
      if(!n){
        if(MSG){
          MSG.className = 'pxmsg is-err';
          MSG.textContent = '行情取不到（离线 / 被浏览器拦截 / 非交易时段），仍显示 ' + M.asof + ' 快照';
        }
        return;
      }
      var updated = applyQuotes(got);
      fillAll();
      patchPositions();
      if(window.__wlSort) window.__wlSort();
      if(ST) ST.innerHTML = '现价为 <b>' + stamp() + '</b> 实时行情 · 已重算潜在空间 / 距买点 / 分布 / 矩阵 / 持仓';
      if(MSG){
        MSG.className = 'pxmsg';
        MSG.textContent = '更新 ' + updated + ' 只' +
          (failed ? '（' + failed + ' 批失败）' : '') + ' · ' + new Date().toTimeString().slice(0, 8);
      }
    });
  }
  function inSession(d){
    var day = d.getDay();
    if(day === 0 || day === 6) return false;
    var m = d.getHours() * 60 + d.getMinutes();
    return (m >= 570 && m <= 690) || (m >= 780 && m <= 900);
  }
  function autoLoop(on){
    if(timer){ clearInterval(timer); timer = null; }
    if(!on) return;
    timer = setInterval(function(){ if(inSession(new Date())) refresh(false); }, 60000);
  }

  if(BTN) BTN.addEventListener('click', function(){ refresh(true); });
  if(AUTO){
    var saved = '0';
    try{ saved = localStorage.getItem('wl-pxauto') || '0'; }catch(e){}
    AUTO.checked = (saved === '1');
    if(AUTO.checked) autoLoop(true);
    AUTO.addEventListener('change', function(){
      autoLoop(AUTO.checked);
      try{ localStorage.setItem('wl-pxauto', AUTO.checked ? '1' : '0'); }catch(e){}
    });
  }
})();
</script>
</body>
</html>
"""

if __name__ == '__main__':
    main()
