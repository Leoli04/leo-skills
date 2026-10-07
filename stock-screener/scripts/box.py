# -*- coding: utf-8 -*-
"""箱体形态识别 —— 网格交易的真正判据

=====================================================================
为什么单独一个文件：
横截面财务接口给不了时间序列形态。「箱体」是时间序列概念，必须拉 K 线算。

⚠️ 周K 线的 scale 参数（实测踩坑）：
    scale=240  → **日线**（曾误当周线用，算出「Q4 有 43 周」的荒谬结果）
    scale=1200 → 周线（2011 年起，datalen=800 可取约 15 年）
    别用 datalen 猜：800 根周线 = 15 年，800 根日线 = 3 年。

数据源：新浪 CN_MarketData.getKLineData（GBK/UTF-8 均可，实测返回 UTF-8）。
东财全线限流，勿用。

—————————————————————————————————————————————————————————————
网格的判据不是「波动率」，而是「箱体」：
    箱体振幅 = (箱顶 − 箱底) / 箱底
用随机游走假设折算的波动率（÷ √N）会严重低估箱体宽度，
因为它假设价格无界游走，而网格要的是「被约束在区间内来回」。

三个维度缺一不可：
  1. 箱体振幅  —— 太窄没利润空间，太宽说明趋势失控（会被穿出边界）
  2. 箱内穿越次数 —— 价格是否真的在箱内反复来回，而非单边穿越
  3. 单边性判定 —— 净位移占比高说明是趋势不是箱体，网格会失效
"""
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BOX_CACHE = os.path.join(HERE, "box_cache.json")

_KLINE = ("http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
          "CN_MarketData.getKLineData?symbol={sym}&scale=1200&ma=no&datalen={n}")


def _fetch_weekly(sym, n=800):
    """拉周 K。返回 [{'day','high','low','close'}]，失败返回 []。"""
    r = urllib.request.Request(
        _KLINE.format(sym=sym, n=n),
        headers={"User-Agent": "Mozilla/5.0",
                 "Referer": "https://finance.sina.com.cn/"})
    txt = urllib.request.urlopen(r, timeout=25).read().decode("utf-8", "ignore")
    return json.loads(txt) if txt.strip() and txt.strip() != "null" else []


def analyze_box(sym, weeks=52, mid_cross_needed=4):
    """算单只票的箱体形态。weeks=52 即近一年。

    ⚠️ **窗口选择实测结论**（52 / 78 / 104 周三档对比）：
       - 104 周会把 2021 那种结构性重估期算进箱体 → 白酒、消费股全部
         被误判成 wide（泸州老窖137%、五粮液 160%）
       - 78 周仍偏宽（海康 45% 被判 wide，其实是很好的箱体）
       - **52 周最准**：伊利 25.3%/12 次穿越 → good，海康 36.9% → good，
         茅台 36.2% 但只穿越 3 次 → trend（准确，近期确在单边下行）
       故默认 52 周。

    返回 dict：
      amp        箱体振幅 %   = (high − low) / low
      pos        现价分位 %   = (close − low) / (high − low)
      crosses    穿越中轴次数（衡量是否真在箱内来回）
      drift      单边性 %     = |净位移| / (箱体宽度)，越小越像箱体
      box_high / box_low / close
      verdict    评级：good / narrow / trend / wide
    """
    bars = _fetch_weekly(sym)
    if not bars:
        return None
    bars = [b for b in bars if b.get("high") and b.get("low")][-weeks:]
    if len(bars) < 26:                     # 不足半年，样本太少不可信
        return None

    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    closes = [float(b["close"]) for b in bars]
    hi, lo, cur = max(highs), min(lows), closes[-1]
    if lo <= 0 or hi <= lo:
        return None

    box_h, box_l = hi, lo
    mid = (box_h + box_l) / 2
    amp = (box_h - box_l) / box_l * 100
    pos = (cur - box_l) / (box_h - box_l) * 100

    # 穿越中轴次数：周收盘跨过中轴算一次
    crosses = sum(1 for i in range(1, len(closes))
                  if (closes[i - 1] - mid) * (closes[i] - mid) < 0)

    # 单边性：净位移占箱体宽度的比例。来回晃 ≈ 0，单边走 ≈ 100。
    drift = abs(closes[-1] - closes[0]) / (box_h - box_l) * 100

    # 评级。wide 阈值取 60%：再宽就不是「箱体」而是「失控的区间」，
    # 挂网格会被直接穿出边界。窄于 12% 则扣完手续费没赚头。
    if amp < 12:
        verdict = "narrow"                # 箱体太窄
    elif amp > 60:
        verdict = "wide"                  # 箱体过宽，多半是趋势失控
    elif crosses < mid_cross_needed or drift > 55:
        verdict = "trend"                 # 箱内不反复来回 = 趋势
    else:
        verdict = "good"

    return dict(symbol=sym, box_high=round(box_h, 2), box_low=round(box_l, 2),
                close=round(cur, 2), amp=round(amp, 1),
                pos=round(pos, 1), crosses=crosses, drift=round(drift, 1),
                weeks=len(bars), verdict=verdict)


def load_boxes(codes, allow_net=True, sleep=0.15):
    """批量算箱体。返回 ({code: box}, 数据来源说明)。优先读缓存。"""
    if os.path.exists(BOX_CACHE):
        try:
            with open(BOX_CACHE, encoding="utf-8") as f:
                cached = json.load(f)
            if set(codes) <= set(cached):
                return cached, "本地缓存"
        except (json.JSONDecodeError, OSError):
            cached = {}
    else:
        cached = {}
    if not allow_net:
        return {}, "已跳过"

    out, fail = {}, 0
    for i, c in enumerate(codes):
        try:
            b = analyze_box(c)
            if b:
                out[c] = b
            else:
                fail += 1
        except Exception:
            fail += 1
        time.sleep(sleep)
    if out:
        merged = dict(cached)
        merged.update(out)
        with open(BOX_CACHE, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=1)
        note = f"周K箱体（{len(out)} 只"
        if fail:
            note += f"，{fail} 只数据不足或取数失败"
        return merged, note + "）"
    return {}, "取数失败已降级"


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] or ["sh600887", "sh600519", "sz002415"]
    for c in codes:
        b = analyze_box(c)
        if b:
            print("%-9s 箱体 %6.2f~%6.2f  振幅%5.1f%%  现价分位%5.1f%%  "
                  "穿越%2d次  单边性%5.1f%%  → %s"
                  % (c, b["box_low"], b["box_high"], b["amp"], b["pos"],
                     b["crosses"], b["drift"], b["verdict"]))
        else:
            print("%-9s 数据不足" % c)
