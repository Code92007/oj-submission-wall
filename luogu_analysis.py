"""Public Luogu problem metadata and a reviewed, approximate CF color calibration.

No credentials or user profiles are fetched here. Analysis reads snapshots only.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

CATALOG = Path(__file__).resolve().parent / "catalog"
CALIBRATION = json.loads((CATALOG / "luogu_calibration.json").read_text())
ALGORITHMS = json.loads((CATALOG / "luogu_algorithm_tags.json").read_text())["tags"]


def algorithm_tags(values):
    if not isinstance(values, list):
        return []
    # Origin, year, region and special-problem IDs are deliberately excluded.
    return sorted({ALGORITHMS[str(v)]["key"] for v in values
                   if type(v) is int and str(v) in ALGORITHMS})


@lru_cache(maxsize=4)
def _read_snapshot(path, stamp):
    try:
        return json.loads(Path(path).read_text()).get("problems", {})
    except (OSError, ValueError, AttributeError):
        return {}


def problem_catalog(app):
    result = {}
    for path in (app.ROOT / "catalog/luogu_problems.json", app.CACHE_DIR / "luogu-analysis.json"):
        if path.exists():
            result.update(_read_snapshot(str(path), path.stat().st_mtime_ns))
    return result


def problem_metadata(problem, cached=None):
    p = {**problem, **(cached or {})}
    difficulty = p.get("difficulty")
    band = CALIBRATION["bands"].get(str(difficulty)) if type(difficulty) is int else None
    return {"rating": band["mean"] if band else None, "tags": algorithm_tags(p.get("tags")),
            "contest": None, "source": "luogu-color" if band else None,
            "ratingRange": band["range"] if band else None,
            "evidenceWeight": band["evidenceWeight"] if band else 1,
            "luoguDifficulty": difficulty if band else None}


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="luogu-analysis-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def refresh_once(app, max_pages=8):
    """Resume a bounded public P-list scan; a failed page keeps the prior snapshot."""
    path = app.CACHE_DIR / "luogu-analysis.json"
    try:
        snapshot = json.loads(path.read_text())
    except (OSError, ValueError):
        snapshot = {"problems": {}, "nextPage": 1}
        seed = app.ROOT / "catalog/luogu_problems.json"
        if seed.exists():
            snapshot["completedAt"] = json.loads(seed.read_text()).get("fetchedAt", 0)
    now = app.utcnow()
    if snapshot.get("completedAt", 0) > now-30*86400:
        return 0
    if snapshot.get("completedAt"):
        snapshot["nextPage"] = 1
        snapshot.pop("completedAt")
    count = 0
    for _ in range(max_pages):
        page = snapshot.get("nextPage", 1)
        body, _ = app.http_get(f"https://www.luogu.com.cn/problem/list?type=P&page={page}",
                               cache_write=False, allow_stale_cache=False)
        context = app.LuoguAdapter._parse_luogu_payload(body.decode("utf-8"))
        data = app.LuoguAdapter._context_data(context).get("problems", {})
        rows, total, per_page = data.get("result"), data.get("count"), data.get("perPage")
        if (not isinstance(rows, list) or not rows or type(total) is not int or total < 1
                or type(per_page) is not int or per_page < 1):
            raise ValueError("Incomplete public Luogu problem list")
        clean = {}
        for p in rows:
            if (not isinstance(p, dict) or not isinstance(p.get("pid"), str)
                    or not p["pid"].startswith("P") or not p["pid"][1:].isdigit()
                    or type(p.get("difficulty")) is not int or not 0 <= p["difficulty"] <= 7
                    or not isinstance(p.get("tags"), list) or any(type(t) is not int for t in p["tags"])):
                raise ValueError("Invalid public Luogu problem metadata")
            clean[p["pid"]] = {k: p[k] for k in ("difficulty", "tags")}
        snapshot["problems"].update(clean)
        snapshot.update(nextPage=page+1, fetchedAt=now, source="https://www.luogu.com.cn/problem/list?type=P")
        if page >= math.ceil(total/per_page):
            snapshot["completedAt"] = now
        atomic_json(path, snapshot)
        count += len(clean)
        if snapshot.get("completedAt"):
            break
    return count


def start_refresh(app):
    def worker():
        while True:
            try:
                refresh_once(app)
            except Exception:
                # Public metadata failure must not interrupt records or discard a successful cache.
                pass
            threading.Event().wait(1800)
    threading.Thread(target=worker, daemon=True, name="luogu-analysis-metadata").start()
