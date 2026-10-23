"""台账差集自检：本地工作目录有哪些报告，已上传的观察池台账里没有对应行。

**为什么需要这个脚本**（2026-10-21 事故）：
SKILL.md 第 48 / 676 行早已写明「每产出一份新报告，必须同步更新台账」，但这是
**人工声明型**要求 —— 只靠自己说「我同步了」。同一时期「旧版归档」有
`lib_reports.py audit` 兜底，于是归档从未漏过，而台账一次漏 4 只：

  - 建滔积层板 01888 / 华测检测 300012：从未入池（交付时根本没做这一步）
  - 浙江荣泰 603119：10:15 加过，17:57 并发会话「全池换价」整链重建时被吃掉，
    补另一个标的的人只补被用户提到的，没做全量差集所以没发现
  - 宇通客车 600066：行在，但 `data-win` 停在修订前的 70%，报告已改 75%

结论：**能机器验证的规则才会被执行**。本脚本就是台账版的 audit。

输出三分类：
  MISSING  本地有报告、台账无行            -> 必须补行
  STALE    台账胜率 ≠ 报告胜率             -> 该行数值停在旧版，必须改
  EXTRA    台账有行、本地无报告            -> 正常（历史标的 / 报告已移走），仅提示

判据为什么用「胜率」而不是「潜在空间」：
  胜率是模型的产物，只随情景概率与折现价修订而变，**不随股价波动**；
  潜在空间（`data-up`）会在「全池换价」时按当日收盘重算，拿它判会全表误报。
  实测 104 只：只命中宇通 1 只、其余 100 行零误报。

用法：
    python assets/watchlist/check_ledger_gap.py --root <工作目录>
    python assets/watchlist/check_ledger_gap.py --root . --pull
    python assets/watchlist/check_ledger_gap.py --root . --ledger <拉回的台账.html>

退出码：0 = CLEAN，1 = NEEDS_ACTION，2 = 找不到台账快照
"""
from __future__ import annotations

import argparse
import datetime
import glob
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SPACE_ID = "lWmChDNEl28HPp3VjuY5W7"
DEFAULT_LEDGER_NODE = "D7PSM0kGVEWKGFnUaSehu7"   # 「投资观察池决策驾驶舱」

# 名称(代码)_<类型>_YYYY-MM-DD.html；代码兼容 600206 / 00700 / 8883.HK
REPORT_RE = re.compile(r"^(.+?)[(（]([0-9]{5,6}(?:\.[A-Za-z]{2})?)[)）]_", re.U)
# <tr ... data-k="名称 代码 判定 观察买点 ">
RE_K_RE = re.compile(r'data-k="([^"\s]+)\s+([0-9]{5,6}(?:\.[A-Za-z]{2})?)')
RE_UP = re.compile(r'data-up="(-?[0-9.]+)"')
RE_WIN = re.compile(r'data-win="(-?[0-9.]+)"')
# 报告 hero：<span class="vb-k">买入胜率</span><span class="vb-v…">30%</span>
# 正则与 verify_report.py 的 check_conclusion_consistency 保持一致
RE_VBK = re.compile(
    r'<span[^>]*class\s*=\s*["\'][^"\']*\bvb-k\b[^"\']*["\'][^>]*>\s*([^<]+?)\s*</span>\s*'
    r'<span[^>]*class\s*=\s*["\'][^"\']*\bvb-v\b[^"\']*["\'][^>]*>\s*([^<]+?)\s*</span>',
    re.S)


def local_reports(root: str) -> dict[str, dict]:
    """扫根目录一层（manifest 只 listdir 一层），同一标的多份取日期最新。"""
    out: dict[str, dict] = {}
    for p in glob.glob(os.path.join(root, "*.html")):
        name = os.path.basename(p)
        if "台账" in name or "驾驶舱" in name:
            continue
        m = REPORT_RE.match(name)
        if not m:
            continue
        stock, code = m.group(1), m.group(2).upper()
        dm = re.search(r"_(\d{4}-\d{2}-\d{2})", name)
        asof = dm.group(1) if dm else ""
        prev = out.get(code)
        if prev is None or asof > prev["asof"]:
            out[code] = {"code": code, "name": stock, "asof": asof, "file": name,
                         "size": os.path.getsize(p), "mtime": int(os.path.getmtime(p))}
    return out


def ledger_rows(path: str) -> dict[str, dict]:
    s = io.open(path, encoding="utf-8", errors="replace").read()
    rows: dict[str, dict] = {}
    for m in RE_K_RE.finditer(s):
        tail = s[m.end(): m.end() + 300]
        w, u = RE_WIN.search(tail), RE_UP.search(tail)
        rows[m.group(2).upper()] = {
            "name": m.group(1),
            "win": float(w.group(1)) if w else None,
            "up": float(u.group(1)) if u else None,
        }
    return rows


def report_win(path: str) -> float | None:
    s = io.open(path, encoding="utf-8", errors="replace").read()
    for label, val in RE_VBK.findall(s):
        if "胜率" in label:
            mm = re.search(r"(-?[0-9.]+)", val)
            if mm:
                return float(mm.group(1))
    return None


def newest_snapshot(root: str) -> str | None:
    pats = [os.path.join(root, ".tmp", "*_ledger", "ledger", "pull_*", "*.html"),
            os.path.join(root, ".tmp", "_gap_ledger", "*.html"),
            os.path.join(root, ".tmp", "*_ledger", "ledger", "投资观察池*.html"),
            os.path.join(root, ".tmp", "*_ledger", "ledger", "out_*.html")]
    cands: list[str] = []
    for pat in pats:
        cands += glob.glob(pat)
    return max(cands, key=os.path.getmtime) if cands else None


def pull(root: str, node_id: str, space_id: str) -> str | None:
    """从库端拉最新台账 HTML。依赖 library skill 的 space_api.py。"""
    api_candidates = [
        os.environ.get("WORKBUDDY_LIBRARY_DIR", ""),
        r"C:/Users/86130/AppData/Local/Programs/WorkBuddy/resources/app.asar.unpacked"
        r"/resources/plugins/workbuddy-builtin/skills/library",
    ]
    api = ""
    for d in api_candidates:
        if d and os.path.exists(os.path.join(d, "space_api.py")):
            api = os.path.join(d, "space_api.py")
            break
    if not api:
        print("PULL: 未找到 space_api.py，改用手头快照（可用 WORKBUDDY_LIBRARY_DIR 指定）")
        return None
    out_dir = os.path.join(root, ".tmp", "_gap_ledger")
    os.makedirs(out_dir, exist_ok=True)
    r = subprocess.run([sys.executable, api, "space.workspace.download-node",
                        "--space-id", space_id, "--node-id", node_id,
                        "--out-dir", out_dir],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    txt = ((r.stdout or "") + (r.stderr or "")).strip()
    print("PULL:", txt[-400:] if txt else "(无输出)")
    cands = sorted(glob.glob(os.path.join(out_dir, "*.html")), key=os.path.getmtime)
    return cands[-1] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="工作目录（报告所在，manifest 同层）")
    ap.add_argument("--pull", action="store_true", help="先从库端拉最新台账再比对")
    ap.add_argument("--ledger", default="", help="指定台账 HTML 路径")
    ap.add_argument("--node-id", default=DEFAULT_LEDGER_NODE)
    ap.add_argument("--space-id", default=DEFAULT_SPACE_ID)
    ap.add_argument("--quiet", action="store_true", help="只输出结论行")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    led = a.ledger or (pull(root, a.node_id, a.space_id) if a.pull else None) or newest_snapshot(root)
    if not led or not os.path.exists(led):
        print("ERR 找不到台账快照；加 --pull 从库端拉一次，或用 --ledger 指定")
        return 2
    if not a.quiet:
        print(f"台账：{os.path.relpath(led, root)}  ({os.path.getsize(led):,} B, "
              f"mtime {datetime.datetime.fromtimestamp(os.path.getmtime(led)):%Y-%m-%d %H:%M})")

    loc, rows = local_reports(root), ledger_rows(led)
    if not a.quiet:
        print(f"本地报告 {len(loc)} 个标的 / 台账 {len(rows)} 行\n")

    missing = [v for k, v in loc.items() if k not in rows]
    stale = []
    for k, v in loc.items():
        if k not in rows:
            continue
        lw = rows[k]["win"]
        rw = report_win(os.path.join(root, v["file"]))
        if lw is not None and rw is not None and abs(lw - rw) > 0.5:
            stale.append(dict(v, ledger_win=lw, report_win=rw, ledger_up=rows[k]["up"]))
    extra = [k for k in rows if k not in loc]

    if not a.quiet:
        print(f"=== MISSING（本地有报告、台账无行）{len(missing)} ===")
        for v in sorted(missing, key=lambda x: x["asof"]):
            print(f"  {v['code']:<10} {v['name']:<10} {v['asof']}  {v['file']}")
        print(f"\n=== STALE（台账胜率 ≠ 报告胜率 → 数值停在旧版）{len(stale)} ===")
        for v in sorted(stale, key=lambda x: -x["mtime"]):
            print(f"  {v['code']:<10} {v['name']:<10} 台账 win {v['ledger_win']:.0f}% "
                  f"→ 报告 {v['report_win']:.0f}%   up {v['ledger_up']}   {v['file']}")
        print(f"\n=== EXTRA（台账有、本地无报告）{len(extra)} ===  （正常，历史标的）")
        print("  " + (" ".join(sorted(extra)) if extra else "无"))
        print()

    bad = len(missing) + len(stale)
    print(f"LEDGER_GAP_RESULT: {'CLEAN' if bad == 0 else 'NEEDS_ACTION'} "
          f"(missing {len(missing)} / stale {len(stale)} / extra {len(extra)})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
