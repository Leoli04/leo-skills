# -*- coding: utf-8 -*-
"""观察池「计划持仓」同步：资料库『持仓与计划』表 → 本地 plan_table.json

真源裁定（2026-10-29 用户确认）：**资料库数据表是计划持仓的唯一真源**。
台账渲染只读本地缓存 plan_table.json，不在渲染时联网；用户在任何设备改表后，
本机跑一次 pull 即可让台账跟上。

与 manifest 的分工（不可混）：
  - 资料库表《持仓与计划》→ 计划持仓（状态=计划中）→ plan_table.json → 台账「计划持仓」区
  - manifest.positions        → 实际持仓（股数 / 成本 / 买卖阶梯）→ 台账持仓卡
  两边职责分离，脚本只做对账告警，不互相覆盖。

用法（在 assets/watchlist 目录下）：
  python sync_plan_table.py pull        # 表 → plan_table.json（并打印对账告警）
  python sync_plan_table.py check       # 只对账、不落盘
  python sync_plan_table.py pull --out /path/plan_table.json --manifest /path/watchlist_manifest.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from datetime import datetime

# 资料库「持仓与计划」表（投资空间 · 挂在观察池台账页内）
PLAN_DB_ID = "LmhN0eFhk6hgXCjbOcSlaz"

_LIB_TRIED = []


def _find_library_dir():
    """定位 WorkBuddy library skill 目录（需含 space_api.py）。

    不写死用户名与安装路径：先认环境变量，再按相对位置往上找兄弟目录，
    最后用系统的 LOCALAPPDATA / APPDATA / 用户主目录拼出内置与用户级安装位。
    全部失败返回空串，调用方负责给清晰报错（见 _lib_missing_msg）。
    """
    def hit(p):
        return bool(p) and os.path.isfile(os.path.join(p, "space_api.py"))

    here = os.path.dirname(os.path.abspath(__file__))
    cands = []
    for env in ("WORKBUDDY_LIBRARY_DIR", "CODEBUDDY_SKILL_DIR"):
        v = os.environ.get(env)
        if v:
            cands.extend((v, os.path.join(v, "library")))
    root = here
    for _ in range(4):
        root = os.path.dirname(root)
        cands.append(os.path.join(root, "library"))
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")):
        if base:
            cands.append(os.path.join(
                base, "Programs", "WorkBuddy", "resources", "app.asar.unpacked",
                "resources", "plugins", "workbuddy-builtin", "skills", "library"))
    cands.append(os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "library"))

    del _LIB_TRIED[:]
    seen = set()
    for d in cands:
        if not d or d in seen:
            continue
        seen.add(d)
        _LIB_TRIED.append(d)
        if hit(d):
            return d
    return ""


def _lib_missing_msg():
    return ("未找到 WorkBuddy library skill（该目录需含 space_api.py）。已探测：\n"
            + "\n".join("  - " + p for p in _LIB_TRIED)
            + "\n用环境变量 WORKBUDDY_LIBRARY_DIR=<library 目录> 指定后重试。")

LIB = _find_library_dir()

SELF_DIR = os.path.dirname(os.path.abspath(__file__))


def _query(db_id: str) -> list:
    """分页拉取全表记录。"""
    if not LIB:
        raise SystemExit(_lib_missing_msg())
    out, cursor = [], None
    while True:
        args = [sys.executable, os.path.join(LIB, "database", "query_database_record.py"),
                "--database-id", db_id, "--page-size", "100"]
        if cursor:
            args += ["--start-cursor", cursor]
        p = subprocess.run(args, cwd=LIB, capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise SystemExit("查询失败：\n%s" % (p.stderr or p.stdout)[-800:])
        line = next((l for l in (p.stdout or "").splitlines() if l.strip().startswith("{")), "")
        if not line:
            raise SystemExit("查询返回非 JSON：%s" % (p.stdout or "")[:400])
        js = json.loads(line)
        out += js.get("results", [])
        cursor = js.get("next_cursor")
        if not js.get("has_more") or not cursor:
            break
    return out


def _link(v):
    """『报告链接』是 [{link,text}]，取第一条 URL。"""
    if isinstance(v, list):
        for it in v:
            if isinstance(it, dict) and it.get("link"):
                return it["link"]
        return ""
    return v or ""


def _num(v):
    return None if v in (None, "") else float(v)


def normalize(rec: dict) -> dict:
    """表记录 → 渲染用扁平结构（字段名固定，render 依赖它）。"""
    code = (rec.get("代码") or "").strip()
    return {
        "code": code,
        "name": (rec.get("标的名称") or "").strip(),
        "status": (rec.get("状态") or "").strip(),
        "strategy": (rec.get("策略") or "").strip(),
        "held_shares": _num(rec.get("持仓股数")),
        "plan_shares": _num(rec.get("计划股数")),
        "cost": _num(rec.get("成本价")),
        "cost_note": rec.get("成本备注") or "",
        "judge": (rec.get("报告判定") or "").strip(),
        "exp": _num(rec.get("期望价")),
        "obs": _num(rec.get("观察买点")),
        "ladder": rec.get("计划阶梯") or "",
        "note": rec.get("持仓备注") or "",
        "url": _link(rec.get("报告链接")),
        "opened": rec.get("建仓日") or "",
        "added": rec.get("加入日期") or "",
        "_record_id": rec.get("_id") or "",
    }


def reconcile(records: list, manifest: dict) -> list:
    """口径对账：返回到账告警列表（不修改任何数据）。"""
    held = {p.get("code"): p for p in (manifest.get("positions") or [])}
    warns = []
    for r in records:
        st, code, nm = r["status"], r["code"], r["name"]
        if st == "计划中" and code in held:
            warns.append("⚠ %s %s：表内「计划中」，但 manifest 已有 %.0f 股实际持仓 —— 表的计划字段不会渲染，"
                         "请确认是漏改状态还是计划加仓。" % (nm, code, held[code].get("shares") or 0))
        elif st == "持仓中" and code not in held:
            warns.append("⚠ %s %s：表内「持仓中」，但 manifest 无该持仓（可能已清仓/已移出） —— "
                         "台账不会显示它，请确认是否该改「已清仓」。" % (nm, code))
        elif st not in ("计划中", "持仓中", "已清仓"):
            warns.append("⚠ %s %s：状态为空或非枚举值（%r），台账将忽略该行。" % (nm, code, st))
    planned = [r for r in records if r["status"] == "计划中" and r["code"] not in held]
    print("表内 %d 条 | 计划中 %d | 持仓中 %d | 已清仓 %d"
          % (len(records), sum(1 for r in records if r["status"] == "计划中"),
             sum(1 for r in records if r["status"] == "持仓中"),
             sum(1 for r in records if r["status"] == "已清仓")))
    print("台账「计划持仓」将渲染 %d 只：%s"
          % (len(planned), "、".join("%s %s" % (r["name"], r["code"]) for r in planned) or "—"))
    for w in warns:
        print(w)
    if not warns:
        print("对账通过：表与 manifest 口径一致。")
    return warns


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "check"])
    ap.add_argument("--out", default=os.path.join(SELF_DIR, "plan_table.json"))
    ap.add_argument("--manifest", default=os.path.join(SELF_DIR, "watchlist_manifest.json"))
    ap.add_argument("--database-id", default=PLAN_DB_ID)
    a = ap.parse_args()

    recs = [normalize(x) for x in _query(a.database_id)]
    man = {}
    if os.path.isfile(a.manifest):
        man = json.load(io.open(a.manifest, encoding="utf-8"))
    else:
        print("! manifest 不存在，跳过对账：%s" % a.manifest)
    warns = reconcile(recs, man) if man else []

    if a.cmd == "check":
        return
    payload = {
        "_说明": "由 sync_plan_table.py pull 生成，勿手改；真源 = 资料库《持仓与计划》表。",
        "database_id": a.database_id,
        "pulled_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warnings": warns,
        "records": recs,
    }
    io.open(a.out, "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=1))
    print("written %s | %d 条 | 对账告警 %d 条" % (a.out, len(recs), len(warns)))


if __name__ == "__main__":
    main()
