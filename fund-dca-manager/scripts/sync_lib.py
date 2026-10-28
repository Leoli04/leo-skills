# -*- coding: utf-8 -*-
"""基金台账 · 跨端数据同步（资料库数据表 ⇄ 本地 JSON）

资料库两张表是**真源**，本地 holdings.json / dca_plan.json 是渲染用的缓存：
  - 在任意设备（网页 / 手机 / 另一台电脑）改表 → 本机跑 pull 即可拿到最新持仓
  - 本机批量改 JSON（如脚本回算）后 → 跑 push 把差异写回表

用法（在数据目录下执行，数据目录 = 放 holdings.json / dca_plan.json 的目录）：
  python sync_lib.py pull            # 表 → 本地 JSON（覆盖表内字段，保留本地专属字段）
  python sync_lib.py push --dry      # 本地 JSON → 表，只打印差异不写
  python sync_lib.py push            # 实际写入（增量更新，只改有变化的字段）
  python sync_lib.py diff            # 只对比，不写
  python sync_lib.py pull --dir D:\\基金台账   # 指定数据目录（默认当前目录）

database_id 不写死在这里，从 dca_plan.json 的 library.databases.{account,position} 读。

表结构（不要改字段名，改了本脚本要同步改）：
  「基金定投-账户」：账户ID 账户名称 总资金 周预算基准 周预算上限 说明
  「基金定投-持仓」：账户 代码 名称 当前市值 成本价 累计投入 份额 单期定投额
                    周期周 平台策略 周投基准 [额度上限·可选] 估值指数 指数偏差说明 手工分位 备注
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime

LIB = os.environ.get("CODEBUDDY_SKILL_DIR") or os.path.expanduser(
    r"C:\Users\86130\AppData\Local\Programs\WorkBuddy\resources\app.asar.unpacked"
    r"\resources\plugins\workbuddy-builtin\skills\library")
if not os.path.isdir(LIB) or not os.path.exists(os.path.join(LIB, "space_api.py")):
    LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library")
PY = sys.executable

ACC_FIELDS = ["账户ID", "账户名称", "总资金", "周预算基准", "周预算上限", "说明"]
POS_FIELDS = ["账户", "代码", "名称", "当前市值", "成本价", "累计投入", "份额", "单期定投额",
              "周期周", "平台策略", "周投基准", "额度上限", "估值指数", "指数偏差说明",
              "手工分位", "备注"]


# ---------- 资料库读写 ----------
def _run(script, *args, stdin_data=None):
    p = subprocess.run([PY, os.path.join(LIB, script)] + list(args), cwd=LIB,
                       input=stdin_data, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise SystemExit("调用 %s 失败：\n%s" % (script, (p.stderr or p.stdout)[-800:]))
    txt = (p.stdout or "").strip()
    line = next((l for l in txt.splitlines() if l.strip().startswith("{")), "")
    return json.loads(line) if line else {}


def query(db, page_size=100):
    out = []
    cursor = None
    while True:
        args = ["--database-id", db, "--page-size", str(page_size)]
        if cursor:
            args += ["--start-cursor", cursor]
        js = _run("database/query_database_record.py", *args)
        out += js.get("results", [])
        cursor = js.get("next_cursor")
        if not js.get("has_more") or not cursor:
            break
    return out


def update_records(db, changes):
    """changes: [{record_id, properties}]"""
    if not changes:
        return {"results": []}
    payload = json.dumps({"database_id": db, "records": changes}, ensure_ascii=False)
    return _run("database/batch_update_database_records.py", "--stdin", stdin_data=payload)


def add_records(db, rows):
    if not rows:
        return {"results": []}
    payload = json.dumps({"database_id": db, "records": rows}, ensure_ascii=False)
    return _run("database/batch_add_database_records.py", "--stdin", stdin_data=payload)


# ---------- 值转换 ----------
def n(v, nd=None):
    """本地数值 → {number/currency}；空值 → None（不写）"""
    if v is None or v == "":
        return None
    return v


def fmt(v, money=False):
    if v is None or v == "":
        return ""
    if money:
        return "%.0f" % v if abs(v - round(v)) < 1e-9 else "%.2f" % v
    return ("%.4f" % v).rstrip("0").rstrip(".")


def ledger_cum(plan, data_dir):
    """台账累计已投 {account|code: 金额}，口径与 dca_weekly.load_ledger 一致（按 actual 累加）。

    存在的理由：表里的「累计投入」是**总累计投入**（用户视角），而配置里的 invested 是
    **启用台账之前的历史持仓**（dca_weekly 会再加一遍台账累计）。两者若无桥，pull 会把
    投资金句直接写进 invested，渲染时累计投入被重复计一次（001592 实测 2700+2500=5200）。
    """
    out_dir = plan.get("output_dir") or os.path.join(data_dir, "定投记录")
    p = os.path.join(out_dir, "ledger.csv")
    tot = {}
    if not os.path.exists(p):
        return tot
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            k = "%s|%s" % (row.get("account", ""), row.get("fund_code", ""))
            try:
                amt = float(row.get("actual") or 0)
            except ValueError:
                amt = 0
            tot[k] = tot.get(k, 0) + amt
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pull", "push", "diff"])
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--dir", default="", help="数据目录（放 holdings.json / dca_plan.json），默认当前目录")
    a = ap.parse_args()

    data_dir = os.path.abspath(a.dir or os.getcwd())
    holdings_p = os.path.join(data_dir, "holdings.json")
    plan_p = os.path.join(data_dir, "dca_plan.json")
    cache_p = os.path.join(data_dir, "_lib_tables_cache.json")
    if not os.path.exists(holdings_p) or not os.path.exists(plan_p):
        raise SystemExit("数据目录里缺 holdings.json / dca_plan.json：%s" % data_dir)

    hold = json.load(open(holdings_p, encoding="utf-8"))
    plan = json.load(open(plan_p, encoding="utf-8"))

    db = (plan.get("library") or {}).get("databases") or {}
    db_acc, db_pos = db.get("account", ""), db.get("position", "")
    if not db_acc or not db_pos:
        raise SystemExit("dca_plan.json 的 library.databases 缺 account / position，先建表并写入 database_id")
    acc_rows = query(db_acc)
    pos_rows = query(db_pos)
    cum = ledger_cum(plan, data_dir)

    local = {}   # code -> 合并后的本地视图
    acct_of = {}
    for acc in hold["accounts"]:
        for f in acc["funds"]:
            local[f["code"]] = dict(f, _acct=acc["id"])
            acct_of[f["code"]] = acc["id"]
    cfg = {f["code"]: f for f in plan["funds"]}

    # 本地期望值（以表字段名组织）
    def local_view(code, acct):
        f = local.get(code, {})
        g = cfg.get(code, {})
        # 表里的「累计投入」= 总累计；配置 invested = 台账前历史 → 用台账累计补齐差额
        base_inv = f.get("invested_known") if f.get("amount") is None else g.get("invested")
        if base_inv is None:
            base_inv = g.get("invested")
        return {
            "当前市值": f.get("amount"),
            "成本价": f.get("cost"),
            "累计投入": (base_inv or 0) + cum.get("%s|%s" % (acct, code), 0),
            "份额": f.get("shares") or g.get("shares"),
            "单期定投额": f.get("dca_amount"),
            "周期周": f.get("cadence_weeks"),
            "周投基准": g.get("base_weekly"),
            "额度上限": g.get("pool"),
            "估值指数": g.get("index_code") or "",
            "手工分位": g.get("manual_percentile"),
            "平台策略": f.get("strategy") or "",
            "备注": f.get("note") or "",
        }

    # ---------- push ----------
    if a.cmd in ("push", "diff"):
        changes, adds = [], []
        by_code = {r.get("代码"): r for r in pos_rows}
        for acct, code in [(acc["id"], f["code"]) for acc in hold["accounts"] for f in acc["funds"]]:
            want = local_view(code, acct)
            row = by_code.get(code)
            if not row:
                adds.append(code)
                continue
            props = {}
            for k, v in want.items():
                cur = row.get(k)
                if isinstance(v, (int, float)) or isinstance(cur, (int, float)):
                    same = (v is None and cur is None) or (
                        isinstance(v, (int, float)) and isinstance(cur, (int, float))
                        and abs(float(v) - float(cur)) < 1e-6)
                else:
                    same = (v or "") == (cur or "")
                if not same:
                    if k == "额度上限":
                        # 可选字段：本地没设限额时要能「删掉」，所以显式传 null 清空
                        props[k] = {"number": float(v)} if v is not None else {"number": None}
                    elif k in ("当前市值", "累计投入", "单期定投额", "周投基准"):
                        props[k] = {"currency": float(v)} if v is not None else None
                    elif k in ("成本价", "份额", "周期周", "手工分位"):
                        props[k] = {"number": float(v)} if v is not None else None
                    else:
                        props[k] = {"text": str(v or "")}
            props = {k: v for k, v in props.items() if v is not None}
            if props:
                changes.append({"record_id": row["record_id"], "properties": props})

        print("本地 → 表：待更新 %d 行，待新增 %d 只%s" % (
            len(changes), len(adds), "（dry，不写入）" if a.dry or a.cmd == "diff" else ""))
        for c in changes:
            code = next((k for k, v in by_code.items() if v["record_id"] == c["record_id"]), "?")
            print("  %-7s %s" % (code, ", ".join("%s=%s" % (k, list(v.values())[0]) for k, v in c["properties"].items())))
        for c in adds:
            print("  %-7s 表中缺行，需新增" % c)
        if a.cmd == "push" and not a.dry:
            r1 = update_records(db_pos, changes)
            ok = sum(1 for x in r1.get("results", []) if x.get("success"))
            print("更新结果：%d/%d 成功" % (ok, len(changes)))
            if adds:
                rows = []
                for code in adds:
                    f = dict(local[code])
                    g = cfg.get(code, {})
                    w = local_view(code, f["_acct"])
                    rows.append({
                        "账户": {"select": "主账户" if f["_acct"] == "A" else "副账户"},
                        "代码": {"text": code},
                        "名称": {"text": f.get("name") or g.get("name") or ""},
                        **{k: ({"currency": float(v)} if k in ("当前市值", "累计投入", "单期定投额", "周投基准", "额度上限")
                               else {"number": float(v)} if k in ("成本价", "份额", "周期周", "手工分位")
                               else {"text": str(v or "")})
                           for k, v in w.items() if v is not None},
                    })
                print("新增：", add_records(db_pos, rows).get("results"))
        return

    # ---------- pull ----------
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    accmap = {r.get("账户ID"): r for r in acc_rows}
    for acc in plan["accounts"]:
        r = accmap.get(acc["id"])
        if not r:
            print("  [警告] 表里没有账户 %s，跳过" % acc["id"])
            continue
        for k, src in [("total_capital", "总资金"), ("weekly_budget_base", "周预算基准"),
                       ("weekly_budget_cap", "周预算上限")]:
            if r.get(src) is not None:
                acc[k] = r[src]

    name2id = {"主账户": "A", "副账户": "B"}
    pos_by_code = {r.get("代码"): r for r in pos_rows}
    missing = []
    for acc in hold["accounts"]:
        for f in acc["funds"]:
            r = pos_by_code.get(f["code"])
            if not r:
                missing.append(f["code"])
                continue
            for k, src in [("amount", "当前市值"), ("cost", "成本价"), ("dca_amount", "单期定投额"),
                           ("cadence_weeks", "周期周"), ("strategy", "平台策略")]:
                if src in r:
                    f[k] = r.get(src)
            if r.get("备注"):
                f["note"] = r["备注"]
            if r.get("当前市值") is None and r.get("累计投入") is not None:
                f["invested_known"] = r["累计投入"]
            g = cfg.get(f["code"])
            if g is not None:
                for k, src in [("base_weekly", "周投基准"), ("manual_percentile", "手工分位")]:
                    if src in r:
                        g[k] = r.get(src)
                # 额度上限是可选字段：表里为空 = 未设单只限额，本地不要留 "pool": null
                if r.get("额度上限") not in (None, ""):
                    g["pool"] = r["额度上限"]
                else:
                    g.pop("pool", None)
                if "估值指数" in r:
                    g["index_code"] = r.get("估值指数") or ""
                if r.get("累计投入") is not None:
                    # 表值是总累计；扣掉台账已记部分，剩下的才是台账前历史
                    g["invested"] = (r["累计投入"]
                                     - cum.get("%s|%s" % (acc["id"], f["code"]), 0))
                if r.get("份额") is not None:
                    g["shares"] = r["份额"]

    # 表里有、本地没有的代码 → 报告（不自动加，避免误建）
    extra = [c for c in pos_by_code if c not in local]

    hold["_sync"] = {"source": "library", "database_id": db_pos, "pulled_at": now}
    plan["_sync"] = {"source": "library", "database_id": db_pos, "account_db": db_acc, "pulled_at": now}
    hold["asof"] = plan["asof"] = datetime.now().strftime("%Y-%m-%d")

    json.dump(hold, open(holdings_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(plan, open(plan_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"pulled_at": now, "account": acc_rows, "position": pos_rows},
              open(cache_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("已从资料库拉取：账户 %d 行 / 持仓 %d 行 → %s" % (
        len(acc_rows), len(pos_rows), datetime.now().strftime("%H:%M:%S")))
    if missing:
        print("  [缺口] 表里没有这些代码：" + "、".join(missing))
    if extra:
        print("  [提示] 表里有本地未收录的代码：" + "、".join(extra))
    print("  缓存已写 _lib_tables_cache.json（含 record_id，供 push 用）")


if __name__ == "__main__":
    main()
