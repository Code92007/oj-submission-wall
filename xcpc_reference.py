"""Cached, identity-scoped reference from Hei-MaoM's public XCPC export.

This retrospective scale is kept separate from CF training and predictions.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import unicodedata
from urllib.parse import quote
from urllib.request import Request, build_opener

from cpc_common import NoRedirect

BASE = "https://hei-maom.github.io/xcpcrating/"
AXES = [("adhoc", "思维与模拟"), ("technique", "基础技巧"), ("search", "搜索"),
        ("offline", "分治与离线"), ("random", "随机与近似"), ("dataStructure", "数据结构"),
        ("graph", "图论"), ("flow", "网络流与匹配"), ("dp", "动态规划"),
        ("string", "字符串"), ("math", "数学"), ("probability", "概率与博弈"), ("geometry", "计算几何")]
FIELDS = ["score", "mastery", "topPercent", "grade", "coverage", "uniqueProblems", "successWeight",
          "exposureWeight", "validContests", "rankScore", "rawMastery", "effectiveProblems", "confidence",
          "evidenceLevel", "rankEligible", "expectedMastery", "ability", "posteriorSd", "rank"]


def player_key(member):
    return "@".join(unicodedata.normalize("NFKC", member[k]).strip() for k in ("name", "school"))


def public_json(path):
    # Paths are generated locally, never supplied by a browser or external profile.
    with build_opener(NoRedirect()).open(Request(BASE+path, headers={"User-Agent": "OJ-Wall-XCPC-reference/1.0"}), timeout=20) as response:
        raw = response.read(15_000_001)
    if len(raw) > 15_000_000:
        raise ValueError("XCPC 公开数据过大")
    return json.loads(raw)


def number(value, low=None, high=None):
    if type(value) not in {int, float} or not math.isfinite(value):
        return None
    if low is not None and value < low or high is not None and value > high:
        return None
    return value


def decode_panel(panel):
    result = {}
    if not isinstance(panel, dict):
        return result
    for mode in ("all", "official"):
        tier = (panel.get(mode) or {}).get("overall")
        if not isinstance(tier, dict):
            continue
        axes = tier.get("axes")
        if not isinstance(axes, (list, dict)) or isinstance(axes, list) and len(axes) != len(AXES):
            continue  # Never remap an old seven-dimensional taxonomy into thirteen axes.
        decoded = []
        for i, (key, label) in enumerate(AXES):
            raw = axes[i] if isinstance(axes, list) else axes.get(key, {})
            values = dict(zip(FIELDS, raw)) if isinstance(raw, list) else raw
            if not isinstance(values, dict):
                values = {}
            decoded.append({"key": key, "label": label,
                "score": number(values.get("score")), "topPercent": number(values.get("topPercent"), 0, 100),
                "grade": values.get("grade") if values.get("grade") in {"SSS", "SS", "S", "A", "B", "C", "D", "E", "F"} else None,
                "uniqueProblems": number(values.get("uniqueProblems"), 0) or 0,
                "confidence": number(values.get("confidence"), 0, 1),
                "posteriorSd": number(values.get("posteriorSd"), 0),
                "evidenceLevel": values.get("evidenceLevel") if values.get("evidenceLevel") in {"missing", "exploratory", "provisional", "established", "legacy"} else "missing"})
        result[mode] = {"contests": number(tier.get("contests"), 0) or 0,
            "coverage": number(tier.get("coverage"), 0, 1), "uniqueProblems": number(tier.get("uniqueProblems"), 0) or 0,
            "taxonomyVersion": str(tier.get("taxonomyVersion") or "")[:100],
            "scoreModel": str(tier.get("scoreModel") or "")[:100],
            "scoreScale": tier.get("scoreScale") if tier.get("scoreScale") in {"rating", "percent"} else "unknown", "axes": decoded}
    return result


def load_player(key, meta, shards):
    shard = hashlib.md5(key.encode()).hexdigest()[:2]
    if shard not in shards:
        shards[shard] = public_json("data/players/"+shard+".json")
    row = shards[shard].get(key)
    if not isinstance(row, dict) or row.get("key") != key or player_key({"name": row.get("name", ""), "school": row.get("org", "")}) != key:
        raise ValueError("未找到姓名与学校完全一致的 XCPC 档案")
    history = []
    for h in row.get("history", []):
        if not isinstance(h, dict):
            continue
        history.append({"title": str(h.get("title") or "")[:300], "date": str(h.get("startAt") or "")[:40],
            "official": h.get("official"), "solved": number(h.get("solved"), 0),
            "rank": number(h.get("rank"), 1), "teamCount": number(h.get("teamCount"), 1),
            "firstAcMinutes": number(h.get("firstATime"), 0), "wrongAttempts": number(h.get("dirtWrong"), 0)})
    return {"url": BASE+"#/player/"+quote(key, safe="")+"?board=all",
        "generatedAt": meta.get("generatedAt"), "source": "Hei-MaoM/xcpcrating",
        "sourceHash": hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "panels": decode_panel(row.get("skillPanel")), "history": history,
        "usedForPrediction": False}


def sync_references(service, force=False):
    from team_analysis import approved_owners
    now = int(time.time())
    with service.db() as conn:
        remote, checked = service.remote(conn)
        if checked+86400 <= now:
            return
        owners = approved_owners(service, conn, remote)
    people = {p["id"]: p for p in remote["roster"]["members"]}
    pending = []
    for person in owners:
        member = people.get(person)
        if not member:
            continue
        key = player_key(member)
        with service.db() as conn:
            old = conn.execute("SELECT * FROM cpc_xcpc_reference WHERE person=?", (person,)).fetchone()
        interval = 300 if old and old["error"] else 86400
        if not force and old and old["player_key"] == key and old["attempted"]+interval > now:
            continue
        pending.append((person, key))
    if not pending:
        return
    meta, shards = None, {}
    for person, key in pending:
        try:
            if meta is None:
                meta = public_json("data/meta.json")
            body = load_player(key, meta, shards)
            with service.db() as conn:
                conn.execute("INSERT OR REPLACE INTO cpc_xcpc_reference VALUES(?,?,?,?,?,?)",
                    (person, key, json.dumps(body, ensure_ascii=False), now, now, ""))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Preserve the last good public evidence for the same identity only.
            with service.db() as conn:
                old = conn.execute("SELECT * FROM cpc_xcpc_reference WHERE person=?", (person,)).fetchone()
                body = old["body"] if old and old["player_key"] == key else "{}"
                checked = old["checked"] if old and old["player_key"] == key else 0
                conn.execute("INSERT OR REPLACE INTO cpc_xcpc_reference VALUES(?,?,?,?,?,?)",
                    (person, key, body, checked, now, "公开档案暂不可用或姓名学校未精确匹配，稍后重试"))


def analysis_reference(service, principal, keys, remote, checked, linked, now):
    result = {"status": "unavailable", "message": "登录并选入已实名认证的本人，可查看现场赛十三维参考。", "usedForPrediction": False}
    if not principal or principal["type"] != "user" or "user:"+str(principal["id"]) not in keys or checked+86400 <= now:
        return result
    person = next((p for p, owner in linked.items() if owner == "user:"+str(principal["id"])), None)
    member = next((m for m in remote["roster"]["members"] if m["id"] == person), None)
    if not member:
        result["message"] = "本人尚未完成实名认证，认证后自动匹配现场赛参考。"
        return result
    with service.db() as conn:
        row = conn.execute("SELECT * FROM cpc_xcpc_reference WHERE person=? AND player_key=?", (person, player_key(member))).fetchone()
    if not row or not row["checked"]:
        if service.configured:
            service.wake.set()
        result.update(status="pending", message=row["error"] if row else "公开现场档案正在后台匹配，稍后刷新分析。")
        return result
    body = json.loads(row["body"])
    return {**body, "status": "stale" if row["error"] or row["checked"]+7*86400 < now else "ready",
        "checkedAt": row["checked"], "owner": "user:"+str(principal["id"]),
        "message": "现场题型评分采用该站独立刻度，供复核训练雷达；不直接与 CF 分数相加。"}
