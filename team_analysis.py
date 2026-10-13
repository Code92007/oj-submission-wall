"""Explainable three-person training estimates and retrospective regional diagnostics.

No network calls, model fitting on the test contests, or onsite-to-personal AC conversion.
The numbers are a versioned heuristic in CF-style units, not official ratings.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from pathlib import Path

from cpc_integration import problem_key

MODEL_VERSION = "team-tags-v2"
FAMILIES = {
    "implementation": ("实现 / 模拟", {"implementation", "brute force"}),
    "greedy": ("贪心", {"greedy", "sortings", "two pointers"}),
    "math": ("数学 / 数论", {"math", "number theory", "chinese remainder theorem"}),
    "combinatorics": ("组合 / 概率", {"combinatorics", "probabilities"}),
    "dp": ("动态规划", {"dp", "bitmasks"}),
    "graphs": ("图论 / 搜索", {"graphs", "dfs and similar", "bfs", "shortest paths", "flows", "graph matchings", "2-sat", "dsu"}),
    "trees": ("树", {"trees"}),
    "data-structures": ("数据结构", {"data structures"}),
    "strings": ("字符串", {"strings", "string suffix structures", "hashing"}),
    "geometry": ("几何", {"geometry"}),
    "constructive": ("构造", {"constructive algorithms"}),
    "search": ("二分 / 分治", {"binary search", "divide and conquer", "ternary search", "meet-in-the-middle", "fft", "expression parsing", "games", "interactive"}),
}
KNOWN_TAGS = set.union(*(tags for _, tags in FAMILIES.values())) | {"*special", "schedules"}
ERRORS = {"WA", "WRONG_ANSWER", "TLE", "TIME_LIMIT_EXCEEDED", "MLE", "MEMORY_LIMIT_EXCEEDED",
          "RE", "RTE", "RUNTIME_ERROR", "OUTPUT_LIMIT_EXCEEDED", "IDLENESS_LIMIT_EXCEEDED", "FAILED", "PE", "PRESENTATION_ERROR"}
WRONG = {"WA", "WRONG_ANSWER"}
PLATFORMS = [("codeforces", "Codeforces"), ("all", "全部可比数据")]


def load_release(root):
    path = Path(root) / "catalog/regional_ratings.json"
    return json.loads(path.read_text()) if path.exists() else {"problems": {}, "contests": {}}


def normalized_tags(value):
    if not isinstance(value, list):
        return []
    return sorted({s.strip().lower() for s in value if isinstance(s, str) and 0 < len(s.strip()) <= 80})


def valid_rating(value):
    return float(value) if type(value) in {int, float} and math.isfinite(value) and 800 <= value <= 4000 else None


def metadata(service, release, rows, app):
    """Regional aliases deduplicate cross-platform replays; no ratings from other scales."""
    result = {}
    for contest in service.contests.values():
        for p in contest["problems"]:
            rated = release["problems"].get(p["id"], {})
            result[p["id"]] = {"rating": valid_rating(rated.get("rating")), "tags": normalized_tags(p.get("tags")),
                "contest": contest["id"], "source": "cf-bot" if rated else None}
    # An optional reviewed tag release augments regional problems without guessing from titles.
    path = app.ROOT / "catalog/regional_tags.json"
    if path.exists():
        for pid, entry in json.loads(path.read_text()).get("problems", {}).items():
            if pid in result and isinstance(entry, dict) and entry.get("source"):
                result[pid]["tags"] = normalized_tags(entry.get("tags"))
    for row in rows:
        raw = app.raw_json_dict(row)
        problem = raw.get("problem") if isinstance(raw.get("problem"), dict) else {}
        key = problem_key(row["platform"], row["problem_id"])
        pid = service.aliases.get(key, key)
        if key.startswith("codeforces:") and row["platform"] == "codeforces":
            entry = result.setdefault(pid, {"rating": None, "tags": [], "contest": None, "source": None})
            rating = valid_rating(problem.get("rating"))
            if rating is not None and entry["source"] != "cf-bot":
                entry.update(rating=rating, source="codeforces")
            entry["tags"] = sorted(set(entry["tags"]) | set(normalized_tags(problem.get("tags"))))
    return result


def handle_sources(platform, handle):
    # Nowcoder supports a normalized personal+team profile ID binding.
    return [s.strip() for s in str(handle).split("+") if s.strip()] if platform == "nowcoder" else [handle]


def account_groups(conn):
    rows = conn.execute("""SELECT h.*, k.kind FROM handles h LEFT JOIN cpc_handle_kinds k ON k.handle_id=h.id
        WHERE h.active=1""").fetchall()
    groups = {}
    for r in rows:
        owner = f"{r['owner_type']}:{r['owner_id']}"
        for source in handle_sources(r["platform"], r["handle"]):
            key = (r["platform"], source.casefold())
            group = groups.setdefault(key, {"platform": r["platform"], "handle": source,
                "owners": set(), "bindings": set(), "team": False, "shared": False})
            group["owners"].add(owner)
            group["bindings"].add((owner, r["platform"], source))
            group["team"] |= r["kind"] == "team" or source.lower().startswith("ucup-team")
    for group in groups.values():
        group["shared"] = len(group["owners"]) > 1
        # Shared Nowcoder profiles are team evidence, never several independent players.
        group["team"] |= group["platform"] == "nowcoder" and group["shared"]
    return groups


def personal_handles(conn, groups=None):
    groups = account_groups(conn) if groups is None else groups
    return {b for g in groups.values() if not g["team"] for b in g["bindings"]}


def submission_source(row, raw):
    if row["platform"] != "nowcoder":
        return row["handle"]
    source = raw.get("nowcoderSourceId")
    if type(source) in {str, int} and str(source).strip():
        return str(source).strip()
    sources = handle_sources(row["platform"], row["handle"])
    # Legacy combined bindings without a source cannot be attributed to one player.
    return sources[0] if len(sources) == 1 else None


def analysis_options(app, service, principal):
    with app.connect_db() as conn:
        owners = app.visible_battle_owners(conn, principal)
        handles = personal_handles(conn)
        members = [{"key": key, "displayName": o["displayName"], "teamName": o["teamName"],
                    "isCurrent": o["isCurrent"], "platforms": sorted({p for k, p, _ in handles if k == key})}
                   for key, o in owners.items()]
    members.sort(key=lambda m: (not m["isCurrent"], m["displayName"].casefold(), m["key"]))
    return {"members": members, "platforms": [{"key": k, "label": v} for k, v in PLATFORMS],
            "contests": [{"id": c["id"], "name": c["name"], "year": c["year"]} for c in service.contests.values()],
            "families": [{"key": k, "label": label} for k, (label, _) in FAMILIES.items()]}


def problem_records(app, service, rows, handles, meta, platform, cutoff, excluded_contest=None, team_evidence=False):
    problems = {}
    coverage = {"submissions": 0, "problems": 0, "rated": 0, "tagged": 0, "usable": 0, "unrated": 0,
                "untagged": 0, "firstSubmission": None, "lastSubmission": None}
    seen_submissions = set()
    for r in rows:
        owner = f"{r['owner_type']}:{r['owner_id']}"
        raw = app.raw_json_dict(r)
        source = submission_source(r, raw)
        if (owner, r["platform"], source) not in handles or (platform != "all" and r["platform"] != platform):
            continue
        if r["submitted_at"] >= cutoff or not r["problem_id"]:
            continue
        author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
        # CF team submissions can appear in a personal handle's user.status.
        if (not team_evidence and len(author.get("members") or []) > 1) or raw.get("syntheticFromCalendar"):
            continue
        key = problem_key(r["platform"], r["problem_id"])
        pid = service.aliases.get(key, key)
        m = meta.get(pid, {"rating": None, "tags": [], "contest": None})
        if excluded_contest and m.get("contest") == excluded_contest:
            continue
        remote_id = str(r["remote_id"])
        if r["platform"] == "nowcoder" and remote_id.startswith(source + "-"):
            remote_id = remote_id[len(source)+1:]
        submission_key = (r["platform"], source if r["platform"] == "nowcoder" else "", remote_id)
        if submission_key in seen_submissions:
            continue
        seen_submissions.add(submission_key)
        verdict = app.normalize_verdict(r["verdict"])
        if verdict != "AC" and verdict not in ERRORS:
            continue  # CE, pending, system errors and activity are not failed solutions.
        coverage["submissions"] += 1
        coverage["firstSubmission"] = min(coverage["firstSubmission"] or r["submitted_at"], r["submitted_at"])
        coverage["lastSubmission"] = max(coverage["lastSubmission"] or 0, r["submitted_at"])
        p = problems.setdefault(pid, {"id": pid, **m, "solved": False, "errors": 0, "wa": 0,
            "firstAc": None, "lastAc": None, "lastPractice": r["submitted_at"], "contestMinutes": None})
        p["lastPractice"] = max(p["lastPractice"], r["submitted_at"])
        if verdict == "AC":
            if p["firstAc"] is None:
                elapsed = raw.get("relativeTimeSeconds")
                if author.get("participantType") in {"CONTESTANT", "VIRTUAL"} and type(elapsed) in {int, float} and 0 < elapsed <= 21600:
                    p["contestMinutes"] = elapsed / 60
            p["solved"] = True
            p["firstAc"] = min(p["firstAc"] or r["submitted_at"], r["submitted_at"])
            p["lastAc"] = max(p["lastAc"] or 0, r["submitted_at"])
        elif p["firstAc"] is None or r["submitted_at"] < p["firstAc"]:
            p["errors"] += 1
            p["wa"] += int(verdict in WRONG)
    for p in problems.values():
        coverage["problems"] += 1
        coverage["rated"] += int(p["rating"] is not None)
        coverage["tagged"] += bool(p["tags"])
        coverage["usable"] += int(p["rating"] is not None and bool(p["tags"]))
        coverage["unrated"] += int(p["rating"] is None)
        coverage["untagged"] += int(not p["tags"])
    return list(problems.values()), coverage


def team_account_evidence(app, service, groups, rows, keys, owners, meta, now, platform):
    accounts = []
    selected = set(keys)
    for _, group in sorted(groups.items()):
        if not group["team"] or not group["owners"] & selected:
            continue
        bindings = {b for b in group["bindings"] if b[0] in selected}
        records, coverage = problem_records(app, service, rows, bindings, meta, "all", now+1, team_evidence=True)
        accounts.append({"platform": group["platform"], "handle": group["handle"],
            "members": [owners[k]["displayName"] for k in keys if k in group["owners"]],
            "shared": group["shared"], "inSelectedSource": platform == "all" or platform == group["platform"],
            "coverage": coverage, "solved": sum(p["solved"] for p in records),
            "wa": sum(p["wa"] for p in records)})
    return accounts


def official_rating_histories(app, rows, handles):
    histories, seen = {}, set()
    for row in rows:
        owner = f"{row['owner_type']}:{row['owner_id']}"
        if row["platform"] != "codeforces" or (owner, "codeforces", row["handle"]) not in handles:
            continue
        raw = app.raw_json_dict(row)
        change = raw.get("ratingChange")
        if not isinstance(change, dict):
            continue
        value = change.get("newRating")
        timestamp = change.get("ratingUpdateTimeSeconds")
        # A contest's start time is too early to use its new rating in a backtest.
        if type(value) is not int or not 0 <= value <= 4000 or type(timestamp) is not int or timestamp <= 0:
            continue
        key = (owner, row["handle"].casefold(), str(change.get("contestId") or row["remote_id"]))
        if key in seen:
            continue
        seen.add(key)
        histories.setdefault(owner, []).append({"handle": row["handle"], "rating": value,
            "updatedAt": timestamp, "contest": str(change.get("contestId") or row["remote_id"])})
    for history in histories.values():
        history.sort(key=lambda p: (p["updatedAt"], p["contest"], p["handle"]))
    return histories


def official_baseline(history, cutoff, basis="current"):
    points = [p for p in history if p["updatedAt"] < cutoff]
    if not points:
        return None
    latest, counts = {}, {}
    for p in points:
        key = p["handle"].casefold()
        latest[key] = p
        counts[key] = counts.get(key, 0)+1
    current = max(latest.values(), key=lambda p: (p["rating"], p["updatedAt"]))
    peak = max(points, key=lambda p: (p["rating"], p["updatedAt"]))
    selected = peak if basis == "peak" else current
    count = counts[selected["handle"].casefold()]
    age = max(0, cutoff-selected["updatedAt"])/(365*86400)
    return {"rating": selected["rating"], "currentRating": current["rating"], "peakRating": peak["rating"],
        "handle": selected["handle"], "updatedAt": selected["updatedAt"], "ratedContests": count,
        "confidence": round((1-math.exp(-count/5))*(.6+.4*math.exp(-age)), 3),
        "reliable": count >= 3, "basis": basis}


def training_momentum(problems, cutoff):
    # First AC of a distinct CF-rated problem: repeat submissions cannot farm the window.
    solved = sorted([p for p in problems if p["solved"] and p["rating"] is not None
                     and p.get("source") == "codeforces" and p["firstAc"] < cutoff], key=lambda p: (p["firstAc"], p["id"]))
    recent = solved[-20:]
    result = {"recent20Count": len(recent), "recent20Mean": None, "recent20WeightedMean": None,
        "monthsWeightedMean": None, "trend": None, "recent180Count": 0, "confidence": 0,
        "lastAc": recent[-1]["firstAc"] if recent else None, "recentErrorPenalty": 0}
    if not recent:
        return result
    weight = lambda timestamp: math.exp(-max(0, cutoff-timestamp)/(90*86400))
    weights = [weight(p["firstAc"]) for p in recent]
    total = sum(weights)
    if total < 1e-100:
        return result
    latest = sum(p["rating"]*w for p, w in zip(recent, weights))/total
    windows = [(p["firstAc"], statistics.mean(s["rating"] for s in solved[max(0, i-19):i+1]))
               for i, p in enumerate(solved) if i >= 4 and p["firstAc"] >= cutoff-180*86400]
    months = sum(v*weight(t) for t, v in windows)/sum(weight(t) for t, _ in windows) if windows else None
    penalty = min(30, sum(min(3,p["errors"])*10*w for p,w in zip(recent,weights))/total)
    result.update(recent20Mean=round(statistics.mean(p["rating"] for p in recent)),
        recent20WeightedMean=round(latest), monthsWeightedMean=round(months) if months is not None else None,
        trend=round(.7*latest+.3*months) if months is not None else round(latest),
        recent180Count=sum(p["firstAc"] >= cutoff-180*86400 for p in solved),
        confidence=round(min(1, sum(math.exp(-max(0, cutoff-p["firstAc"])/(180*86400)) for p in recent)/20), 3),
        recentErrorPenalty=round(penalty))
    return result


def quantile(values, q):
    values = sorted(values)
    threshold = sum(w for _, w in values) * q
    acc = 0.0
    for value, weight in values:
        acc += weight
        if acc >= threshold:
            return value
    return values[-1][0]


def estimate(problems, cutoff):
    """Repeated AC cannot create new evidence; multi-tag tasks split evidence weight."""
    solved = [p for p in problems if p["solved"] and p["rating"] is not None]
    rated = [p for p in problems if p["rating"] is not None]
    weights = [(p, (0.8 + 0.2 * math.exp(-max(0, cutoff - p["lastAc"]) / (365 * 86400)))
                / max(1, len(p["tags"]))) for p in solved]
    effective = sum(w for _, w in weights)
    confidence = 1 - math.exp(-effective / 8)
    rating = None
    memory = penalty = 0
    base = None
    if solved:
        base = quantile([(p["rating"], w) for p, w in weights], .7)
        memory = sum(100 * (1 - math.exp(-max(0, cutoff-p["lastAc"]) / (365*86400))) * w for p, w in weights) / effective
        # Errors on harder unsolved tasks are not evidence of weakness at easier levels.
        near = [p for p in rated if p["rating"] <= base + 200]
        unresolved = sum(not p["solved"] for p in near) / max(1, len(near))
        retry = sum(min(5, p["errors"]) * 20 * w for p, w in weights) / effective
        penalty = min(120, retry + 80 * unresolved)
        rating = round(max(800, base - penalty - memory - 200 * (1-confidence)))
    hist = {}
    for p in solved:
        bucket = str(int(p["rating"] // 200) * 200)
        hist[bucket] = hist.get(bucket, 0) + 1
    return {"rating": rating, "baseRating": base, "confidence": round(confidence, 3),
        "reliable": len(solved) >= 5 and effective >= 3, "effectiveSolved": round(effective, 2),
        "practiced": len(problems), "solved": sum(p["solved"] for p in problems), "ratedSolved": len(solved),
        "errors": sum(p["errors"] for p in problems), "wa": sum(p["wa"] for p in problems),
        "unresolved": sum(not p["solved"] for p in problems),
        "averageTries": round(sum(1+p["errors"] for p in problems if p["solved"]) / max(1, sum(p["solved"] for p in problems)), 2) if any(p["solved"] for p in problems) else None,
        "lastPractice": max((p["lastPractice"] for p in problems), default=None),
        "memoryPenalty": round(memory), "errorPenalty": round(penalty), "distribution": hist}


def combine(members, target):
    reliable = sorted([m for m in members if m["reliable"] and m["rating"] is not None], key=lambda m: m["rating"], reverse=True)
    consensus = None
    specialist = None
    if len(reliable) >= 2:
        a, b = reliable[:2]
        consensus = b["rating"] + .15 * min(400, a["rating"]-b["rating"])
        if len(reliable) == 3:
            consensus += .1 * max(0, 400-(b["rating"]-reliable[2]["rating"]))
    if reliable and reliable[0]["ratedSolved"] >= 8 and reliable[0]["confidence"] >= .65:
        specialist = reliable[0]["rating"] - 250
    paths = [p for p in (consensus, specialist) if p is not None]
    rating = round(max(paths)) if paths else None
    support = sum(m["rating"] >= target for m in reliable)
    if support >= 2:
        status, label = "covered", "双人覆盖"
    elif specialist is not None and specialist >= target:
        status, label = "specialist", "单人专长 · 需备份"
    elif rating is None:
        status, label = "unknown", "证据不足"
    elif rating < target:
        status, label = "weak", "优先补强"
    else:
        status, label = "developing", "接近目标"
    return {"rating": rating, "consensusRating": round(consensus) if consensus is not None else None,
        "specialistRating": round(specialist) if specialist is not None else None, "status": status,
        "coverageLabel": label, "support": support, "reliableMembers": len(reliable),
        "confidence": round(sum(m["confidence"] for m in reliable[:2])/2, 3), "members": members}


def profile(problems, cutoff, target, rating_history=None, rating_basis="hybrid"):
    tags = KNOWN_TAGS | {t for p in problems for t in p["tags"]}
    raw = {tag: estimate([p for p in problems if tag in p["tags"]], cutoff) for tag in sorted(tags)}
    families = {key: estimate([p for p in problems if set(p["tags"]) & tags], cutoff)
                for key, (_, tags) in FAMILIES.items()}
    overall = estimate(problems, cutoff)
    overall["trainingRating"] = overall["rating"]
    overall["ratingSource"] = "practice-proxy"
    history = rating_history or []
    official = official_baseline(history, cutoff, rating_basis)
    momentum = training_momentum(problems, cutoff)
    overall["momentum"] = momentum
    anchor = None
    if official:
        last_evidence = max(momentum["lastAc"] or 0, official["updatedAt"])
        memory = 100*(1-math.exp(-max(0, cutoff-last_evidence)/(365*86400)))
        retained = max(0, official["peakRating"]-200-memory)
        reference = max(official["currentRating"], retained)
        uplift = .7*momentum["confidence"]*max(0, min(400, (momentum["trend"] or reference)-momentum["recentErrorPenalty"]-reference))
        anchor = official["peakRating"] if rating_basis == "peak" else round(reference+uplift)
        overall.update(officialRating=official["currentRating"], peakRating=official["peakRating"],
            cfHandle=official["handle"], ratingUpdatedAt=official["updatedAt"], officialContests=official["ratedContests"],
            retainedPeak=round(retained), trainingUplift=round(uplift),
            confidence=max(momentum["confidence"], round(official["confidence"]*.85, 3)),
            reliable=official["reliable"] or overall["reliable"], ratingSource="cf-training-hybrid")
    elif momentum["trend"] is not None:
        anchor = round(max(800, momentum["trend"]-momentum["recentErrorPenalty"]-100*(1-momentum["confidence"])))
        overall.update(ratingSource="recent-training", confidence=momentum["confidence"])
    if anchor is not None:
        # The training mix locates relative strengths, not the absolute CF scale.
        for value in list(raw.values())+list(families.values()):
            value["trainingRating"] = value["rating"]
            value["ratingSource"] = "training-anchored-tags"
            value["abilityBaseline"] = anchor
            if value["baseRating"] is not None and overall["baseRating"] is not None:
                delta = (value["baseRating"]-overall["baseRating"]
                    -(value["errorPenalty"]-overall["errorPenalty"])
                    -(value["memoryPenalty"]-overall["memoryPenalty"]))
                adjustment = round(max(-400, min(400, delta))*value["confidence"])
                value["relativeAdjustment"] = adjustment
                value["rating"] = max(0, min(4000, anchor+adjustment))
        overall.update(rating=anchor, baseRating=anchor,
            trainingErrorPenalty=overall["errorPenalty"], trainingMemoryPenalty=overall["memoryPenalty"],
            errorPenalty=0, memoryPenalty=0)
    return {"tags": raw, "families": families, "overall": overall, "official": official, "_ratingHistory": history}


def team_profiles(profiles, target):
    tags = sorted(set().union(*(p["tags"] for p in profiles)))
    return {"tags": [{"key": t, "label": t, **combine([p["tags"].get(t, estimate([], 0)) for p in profiles], target)} for t in tags],
        "families": [{"key": k, "label": label, **combine([p["families"][k] for p in profiles], target)} for k, (label, _) in FAMILIES.items()],
        "overall": combine([p["overall"] for p in profiles], target)}


def approved_owners(service, conn, remote):
    # Use the same stable identity and redirect rules as regional progress.
    ids = {r["uid"]: "user:"+r["local_id"] for r in conn.execute("SELECT * FROM cpc_ids WHERE kind='subject'")}
    claims = {}
    for c in remote.get("claims", []):
        key = c["subject"]
        if key not in claims or (c["updated"], c["id"]) > (claims[key]["updated"], claims[key]["id"]):
            claims[key] = c
    result = {}
    for subject, c in claims.items():
        if c["status"] != "approved" or subject not in ids:
            continue
        person, seen = c["person"], set()
        redirects = remote["roster"].get("redirects", {})
        while person in redirects and person not in seen:
            seen.add(person)
            person = redirects[person]
        if person in seen:
            continue
        result.setdefault(person, []).append(ids[subject])
    return {person: owners[0] for person, owners in result.items() if len(set(owners)) == 1}


def probability(ability, difficulty):
    return 1/(1+10**(max(-4000, min(4000, difficulty-ability))/400))


def timing_reference(records, profiles):
    observations = []
    for problems, p in zip(records, profiles):
        ability = p["overall"]["rating"]
        if ability is None:
            continue
        for problem in problems:
            minutes = problem.get("contestMinutes")
            if problem["rating"] is not None and minutes is not None:
                past = official_baseline(p.get("_ratingHistory", []), problem["firstAc"])
                sample_ability = past["rating"] if past else p["overall"].get("trainingRating", ability)
                if sample_ability is not None:
                    observations.append(minutes / 2**((problem["rating"]-sample_ability)/500))
    if len(observations) < 8:
        return {"scale": 45, "low": 20, "high": 100, "samples": len(observations), "source": "heuristic"}
    observations.sort()
    median = max(5, min(180, statistics.median(observations)))
    return {"scale": median, "low": max(3, min(median*.7, observations[int((len(observations)-1)*.1)])),
        "high": max(median*1.5, min(360, observations[int((len(observations)-1)*.9)])),
        "samples": len(observations), "source": "personal-contest-history"}


def predict(ability, confidence, difficulty, budget, timing, difficulty_range=None):
    """A solve/unsolved mixture with lognormal conditional elapsed times.

    Bounds are sensitivity ranges, not statistically calibrated confidence intervals.
    The censored expectation assigns the whole budget to an unsuccessful attempt.
    """
    uncertainty = 150 + 350*(1-confidence)
    if difficulty_range:
        uncertainty += max(abs(difficulty-difficulty_range[0]), abs(difficulty_range[1]-difficulty))
    sigma = .8
    normal = statistics.NormalDist()
    def phi(z):
        return .5*math.erfc(-z/math.sqrt(2))
    def cdf(median, horizon):
        return phi(math.log(horizon/median)/sigma)
    multiplier = 2**(max(-3000, min(3000, difficulty-ability))/500)
    median = timing["scale"]*multiplier
    f = max(1e-300, cdf(median, budget))
    chance = probability(ability, difficulty)*f
    # For low probability combine weaker ability and slower timing, and vice versa.
    low_median = timing["high"]*2**(max(-3000, min(3000, difficulty-ability+uncertainty))/500)
    high_median = timing["low"]*2**(max(-3000, min(3000, difficulty-ability-uncertainty))/500)
    low = probability(ability-uncertainty, difficulty)*cdf(low_median, budget)
    high = probability(ability+uncertainty, difficulty)*cdf(high_median, budget)
    mean = max(.1, min(budget, median*math.exp(sigma*sigma/2)*phi((math.log(budget/median)-sigma*sigma)/sigma)/f))
    interval = [max(.1, min(budget, median*math.exp(sigma*normal.inv_cdf(max(1e-300, min(1-1e-12, f*q)))))) for q in (.1, .9)]
    return {"probability": round(chance, 4), "probabilityRange": [round(low, 4), round(high, 4)],
        "conditionalMinutes": round(mean, 1), "timeRangeMinutes": [round(t, 1) for t in interval],
        "budgetedMinutes": round(chance*mean+(1-chance)*budget, 1), "timeSource": timing["source"],
        "timingSamples": timing["samples"]}


def onsite_times(body, contest):
    """Reuse audited first-AC evidence, never infer elapsed time from AC flags."""
    times = {}
    for run in body.get("accepted_runs", []):
        elapsed = run.get("elapsed_seconds")
        if type(elapsed) in {int, float} and math.isfinite(elapsed) and 0 <= elapsed <= 86400:
            label = run["problem"]
            times[label] = min(times.get(label, float("inf")), elapsed/60)
    if body.get("source_type") == "rankland":
        from cpc_sources import seconds
        for label, status in zip(body.get("problem_labels", []), body.get("source_statuses", [])):
            if status.get("result") in {"AC", "FB"}:
                try:
                    elapsed = seconds(status["time"])
                    if math.isfinite(elapsed) and 0 <= elapsed <= 86400:
                        times[label] = elapsed/60
                except (KeyError, ValueError, TypeError):
                    pass
    return {p["id"]: times[p["index"]] for p in contest["problems"] if p["index"] in times}


def forecast_contest(app, service, cid, profiles, records, meta, target, budget, release, rating_basis="hybrid"):
    team = team_profiles(profiles, target)
    overall = team["overall"]
    timing = timing_reference(records, profiles)
    scores = {t["key"]: t for t in team["tags"]}
    rows = []
    for p in service.contests[cid]["problems"]:
        m = meta.get(p["id"], {})
        tags = m.get("tags", [])
        abilities = [scores[t]["rating"] for t in tags if t in scores]
        tagged = bool(abilities) and len(abilities) == len(tags) and all(a is not None for a in abilities)
        ability = min(abilities) if tagged else overall["rating"]
        confidence = min(scores[t]["confidence"] for t in tags) if tagged else overall["confidence"]
        row = {"problemId": p["id"], "index": p["index"], "name": p["name"], "tags": tags,
            "rating": m.get("rating"), "tagged": tagged, "ratingSource": m.get("source"),
            "ability": ability,
            "ratingRange": release["problems"].get(p["id"], {}).get("range")}
        if ability is None or m.get("rating") is None:
            row.update(probability=None, reason="训练证据不足" if ability is None else "缺少兼容评级")
        else:
            row.update(predict(ability, confidence, m["rating"], budget, timing, row["ratingRange"]))
            if overall["rating"] is not None:
                row["baseline"] = predict(overall["rating"], overall["confidence"], m["rating"], budget, timing)["probability"]
        rows.append(row)
    rated = [r for r in rows if r["probability"] is not None]
    return {"contest": cid, "name": service.contests[cid]["name"], "budgetMinutes": budget, "ratingBasis": rating_basis,
        "problems": rows, "expectedSolves": round(sum(r["probability"] for r in rated), 1),
        "expectedSolvesRange": [round(sum(r["probabilityRange"][i] for r in rated), 1) for i in (0, 1)],
        "predictedProblems": len(rated), "timing": timing,
        "notes": ["推演使用当前三人训练，排除这场比赛的全部练习；历史回测则使用当年名单与赛前数据。",
                  "整体能力结合官方当前/历史峰值与 Recent 20 AC、近半年移动均值；tag 作相对调整。历史峰值推演是恢复峰值水平的参考情景，不等于当前官方 Rating。",
                  "时间指开赛至首次 AC，包含读题和排队，非纯编码时间；条件期望只针对限时内解出的情况。失败计满预算后的期望另列。",
                  "概率范围是能力与时间基准扰动的敏感性区间；时间范围是模型条件分布的 10%–90% 分位，尚非经验证的置信区间。",
                  "样本不足时使用 45 分钟经验时间基准；有至少 8 道个人正式/VP 首过时间时，以历史中位数调整。未使用目标场现场成绩拟合。",
                  "预计题数是逐题通过倾向之和，未模拟一台机器、读题顺序和队内分工，仅供备战参考。"]}


def metrics(samples, prediction="probability"):
    if not samples:
        return {"count": 0, "brier": None, "meanPrediction": None, "actualRate": None}
    return {"count": len(samples), "brier": round(sum((s[prediction]-s["accepted"])**2 for s in samples)/len(samples), 4),
        "meanPrediction": round(sum(s[prediction] for s in samples)/len(samples), 3),
        "actualRate": round(sum(s["accepted"] for s in samples)/len(samples), 3)}


def backtest(app, service, principal, keys, platform, target, meta, release, all_rows, handles, remote, checked, now, rating_histories=None):
    result = {"status": "unavailable", "message": "登录并选择本人后，可回测认证成员的历史真实队伍。", "contests": [],
        "skipped": [], "ratingReview": [], "tagMetrics": [], "metrics": metrics([]), "baselineMetrics": metrics([]),
        "probabilityCalibration": [], "ratingCohorts": [],
        "timeMetrics": {"count": 0, "maeMinutes": None, "intervalCoverage": None, "budgetedMaeMinutes": None},
        "notes": ["仅使用比赛日期零点之前的个人训练，排除被测比赛全部题目；按当年真实三人名单还原，现场 AC 只属于队伍。",
                  "未通过也可能来自时间分配或未尝试。通过倾向为启发式分数；Brier 越小表示与结果越接近。",
                  "CF Bot 评级来自同场正式榜单，可能包含被测队伍，是回顾性诊断，不能视为独立验证或据此自动改分。"]}
    self_key = f"{principal['type']}:{principal['id']}" if principal else None
    if not principal or principal["type"] != "user" or self_key not in keys:
        return result
    if checked + 86400 <= now:
        result["message"] = "认证名单尚未就绪或核验已过期，请到区域赛进度更新认证状态。"
        return result
    with service.db() as conn:
        person_owners = approved_owners(service, conn, remote)
        self_person = next((p for p, o in person_owners.items() if o == self_key), None)
        evidence = {r["participation"]: (r["contest"], json.loads(r["body"]))
                    for r in conn.execute("SELECT * FROM cpc_onsite WHERE active=1 ORDER BY id")}
    if not self_person:
        result["message"] = "本人尚未通过成员认证，认证后可使用历史区域赛成绩回测。"
        return result
    samples, seen, skipped = [], set(), result["skipped"]
    for participation in sorted(remote["roster"]["participations"], key=lambda p: p.get("date", "")):
        if self_person not in participation["members"]:
            continue
        common = {"name": participation.get("team", "历史队伍"), "date": participation.get("date", "")}
        if participation["id"] not in evidence:
            skipped.append({**common, "reason": "现场完整榜单尚未同步"}); continue
        cid, body = evidence[participation["id"]]
        common["name"] = service.contests.get(cid, {}).get("name", body.get("contest_name", cid))
        historic_keys = [person_owners.get(p) for p in participation["members"]]
        if len(historic_keys) != 3 or None in historic_keys or len(set(historic_keys)) != 3:
            skipped.append({**common, "reason": "当年三位队员尚未全部认证并关联 Wall 训练记录"}); continue
        if cid not in service.contests:
            skipped.append({**common, "reason": "比赛题目尚未映射到目录"}); continue
        try:
            cutoff = int(dt.datetime.combine(dt.date.fromisoformat(participation["date"]), dt.time.min, tzinfo=app.DISPLAY_TZ).timestamp())
        except (ValueError, KeyError):
            skipped.append({**common, "reason": "缺少准确比赛日期"}); continue
        if cutoff >= now:
            skipped.append({**common, "reason": "比赛尚未结束"}); continue
        # One canonical team/contest outcome, even if evidence was imported more than once.
        outcome_key = (cid, tuple(sorted(historic_keys)))
        if outcome_key in seen:
            continue
        seen.add(outcome_key)
        ps, training = [], []
        for key in historic_keys:
            records, _ = problem_records(app, service, all_rows.get(key, []), handles, meta, platform, cutoff, cid)
            training.append(records)
            ps.append(profile(records, cutoff, target, (rating_histories or {}).get(key, [])))
        team = team_profiles(ps, target)
        overall = team["overall"]["rating"]
        if overall is None:
            skipped.append({**common, "reason": "赛前可比训练样本不足"}); continue
        duration = release.get("contests", {}).get(cid, {}).get("duration_seconds", 18000) / 60
        config = body.get("source_config", {})
        if config.get("start_time") is not None and config.get("end_time") is not None:
            duration = (config["end_time"]-config["start_time"]) / (60000 if config["start_time"] > 100_000_000_000 else 60)
        elif body.get("source_contest", {}).get("duration"):
            from cpc_sources import seconds
            duration = seconds(body["source_contest"]["duration"]) / 60
        if not 0 < duration <= 1440:
            skipped.append({**common, "reason": "缺少有效比赛时长"}); continue
        forecast = forecast_contest(app, service, cid, ps, training, meta, target, duration, release)
        forecasts = {r["problemId"]: r for r in forecast["problems"]}
        actual_times = onsite_times(body, service.contests[cid])
        accepted = set(body["accepted"])
        current = []
        for p in service.contests[cid]["problems"]:
            m = meta.get(p["id"], {})
            rating = m.get("rating")
            if rating is None:
                continue
            prediction = forecasts[p["id"]]
            if prediction["probability"] is None:
                continue
            source_team = body.get("source_team", {})
            official = body.get("official") is True or ("official" in source_team.get("group", []) and "unofficial" not in source_team.get("group", [])) or source_team.get("official") is True
            sample = {**prediction, "accepted": int(p["id"] in accepted),
                "actualMinutes": actual_times.get(p["id"]) if p["id"] in accepted else None,
                "official": official, "contest": cid}
            current.append(sample)
        if not current:
            skipped.append({**common, "reason": "该场没有 CF Bot 可比评级"}); continue
        samples.extend(current)
        result["contests"].append({**common, "contest": cid, "cutoff": app.iso_from_ts(cutoff),
            "sameLineup": set(historic_keys) == set(keys), "predictedSolves": round(sum(s["probability"] for s in current), 1),
            "actualSolves": sum(s["accepted"] for s in current), "ratedProblems": len(current),
            "totalProblems": len(service.contests[cid]["problems"]), "taggedProblems": sum(s["tagged"] for s in current),
            "brier": metrics(current)["brier"], "durationMinutes": duration, "problems": current})
    tagged = [s for s in samples if s["tagged"]]
    result.update(status="ready" if samples else "insufficient", metrics=metrics(samples),
        tagMetricsSummary=metrics(tagged), baselineMetrics=metrics(tagged, "baseline"),
        message=f"已回测 {len(result['contests'])} 场真实队伍；{len(tagged)}/{len(samples)} 道评级题支持 tag 诊断。" if samples else "暂无满足三人关联、赛前训练和完整现场证据的历史场次。")
    for low in (0, .2, .4, .6, .8):
        ss = [s for s in samples if min(4, int(s["probability"]*5)) == round(low*5)]
        result["probabilityCalibration"].append({"range": [low, round(low+.2, 1)], **metrics(ss),
            "predictedRange": [round(sum(s["probabilityRange"][i] for s in ss)/len(ss), 3) for i in (0, 1)] if ss else None})
    timed = [s for s in samples if s["accepted"] and s["actualMinutes"] is not None]
    if timed:
        result["timeMetrics"] = {"count": len(timed),
            "maeMinutes": round(sum(abs(s["conditionalMinutes"]-s["actualMinutes"]) for s in timed)/len(timed), 1),
            "intervalCoverage": round(sum(s["timeRangeMinutes"][0] <= s["actualMinutes"] <= s["timeRangeMinutes"][1] for s in timed)/len(timed), 3),
            "budgetedMaeMinutes": None}
    horizons = {c["contest"]: c["durationMinutes"] for c in result["contests"]}
    censored = [s for s in samples if not s["accepted"] or s["actualMinutes"] is not None]
    if censored:
        result["timeMetrics"]["budgetedMaeMinutes"] = round(sum(abs(s["budgetedMinutes"]-(s["actualMinutes"] if s["accepted"] else horizons[s["contest"]])) for s in censored)/len(censored), 1)
    cohorts = {}
    for sample in samples:
        key = (int(sample["ability"]//400)*400, int(sample["rating"]//400)*400)
        cohorts.setdefault(key, []).append(sample)
    for (ability_band, difficulty_band), ss in sorted(cohorts.items()):
        times = [s["actualMinutes"] for s in ss if s["accepted"] and s["actualMinutes"] is not None]
        result["ratingCohorts"].append({"abilityRange": [ability_band, ability_band+399],
            "difficultyRange": [difficulty_band, difficulty_band+399], **metrics(ss),
            "timedSolves": len(times), "actualMeanMinutes": round(statistics.mean(times), 1) if times else None,
            "predictedMeanMinutes": round(statistics.mean(s["conditionalMinutes"] for s in ss), 1)})
    for t in sorted({t for s in tagged for t in s["tags"]}):
        ss = [s for s in tagged if t in s["tags"]]
        result["tagMetrics"].append({"tag": t, **metrics(ss), "baselineBrier": metrics(ss, "baseline")["brier"]})
    # Diagnostic residuals only; no tuning or write-back to the published ratings.
    for pid in sorted({s["problemId"] for s in samples}):
        ss = [s for s in samples if s["problemId"] == pid]
        stat = metrics(ss)
        residual = stat["actualRate"]-stat["meanPrediction"]
        enough = len(ss) >= 5 and all(s["official"] for s in ss)
        signal = "可能偏高" if residual > .25 else "可能偏低" if residual < -.25 else "未见明显偏差"
        result["ratingReview"].append({"problemId": pid, "rating": ss[0]["rating"], **stat,
            "residual": round(residual, 3), "signal": signal if enough else "样本不足", "reviewable": enough})
    result["ratingReview"].sort(key=lambda r: (-r["count"], -abs(r["residual"]), r["problemId"]))
    return result


def build_analysis(app, service, principal, keys, platform="codeforces", target=1900, contest_id=None, budget=300):
    if len(keys) != 3 or len(set(keys)) != 3:
        raise ValueError("请选择三位不同成员")
    if platform not in dict(PLATFORMS):
        raise ValueError("请选择 Codeforces 或全部可比数据")
    try:
        target = int(target)
    except (TypeError, ValueError):
        raise ValueError("目标评级应为 800–3500 的整数") from None
    if not 800 <= target <= 3500:
        raise ValueError("目标评级应为 800–3500 的整数")
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        raise ValueError("预测限时应为 30–600 分钟的整数") from None
    if not 30 <= budget <= 600:
        raise ValueError("预测限时应为 30–600 分钟的整数")
    contest_id = contest_id or next(iter(service.contests))
    if contest_id not in service.contests:
        raise ValueError("找不到这场区域赛")
    now = app.utcnow()
    release = load_release(app.ROOT)
    with service.db() as conn:
        remote, checked = service.remote(conn)
        linked = approved_owners(service, conn, remote)
    with app.connect_db() as conn:
        owners = app.visible_battle_owners(conn, principal)
        if any(k not in owners for k in keys):
            raise ValueError("找不到所选成员")
        groups = account_groups(conn)
        handles = personal_handles(conn, groups)
        selected_accounts = [(k, p, h.casefold()) for k, p, h in handles
                             if k in keys and (platform == "all" or platform == p)]
        seen_accounts = {}
        for key, p, h in selected_accounts:
            if (p, h) in seen_accounts and seen_accounts[p, h] != key:
                raise ValueError("所选成员有相同的个人 OJ 账号，请先核对绑定，避免重复计算战力")
            seen_accounts[p, h] = key
        relevant = set(keys)
        # Read only historical rosters involving the authenticated selected account.
        self_key = f"{principal['type']}:{principal['id']}" if principal else None
        if self_key in keys and principal["type"] == "user" and checked + 86400 > now:
            self_person = next((p for p, o in linked.items() if o == self_key), None)
            for participation in remote["roster"]["participations"]:
                if self_person and self_person in participation["members"]:
                    relevant.update(linked[p] for p in participation["members"] if p in linked and linked[p] in owners)
        rows = app.battle_union_rows(conn, "submissions", "*", [tuple(k.split(":", 1)) for k in sorted(relevant)],
                                    order_by="submitted_at, id")
        rating_rows = app.battle_union_rows(conn, "contests", "*", [tuple(k.split(":", 1)) for k in sorted(relevant)],
                                           order_by="participated_at, id")
    rating_histories = official_rating_histories(app, rating_rows, handles)
    meta = metadata(service, release, rows, app)
    by_owner = {key: [] for key in relevant}
    for row in rows:
        by_owner[f"{row['owner_type']}:{row['owner_id']}"].append(row)
    profiles, members = [], []
    for key in keys:
        records, coverage = problem_records(app, service, by_owner[key], handles, meta, platform, now+1)
        p = profile(records, now, target, rating_histories.get(key, []))
        profiles.append(p)
        members.append({"key": key, "displayName": owners[key]["displayName"], "teamName": owners[key]["teamName"],
                        "coverage": coverage, "overall": p["overall"]})
    forecast_records = [problem_records(app, service, by_owner[k], handles, meta, platform, now+1, contest_id)[0] for k in keys]
    forecast_profiles = [profile(r, now, target, rating_histories.get(k, [])) for k, r in zip(keys, forecast_records)]
    peak_profiles = [profile(r, now, target, rating_histories.get(k, []), "peak") for k, r in zip(keys, forecast_records)]
    from xcpc_reference import analysis_reference
    return {"modelVersion": MODEL_VERSION, "generatedAt": app.iso_from_ts(now), "target": target, "platform": platform,
        "members": members, **team_profiles(profiles, target),
        "teamAccounts": team_account_evidence(app, service, groups, rows, keys, owners, meta, now, platform),
        "onsiteReference": analysis_reference(service, principal, keys, remote, checked, linked, now),
        "forecast": forecast_contest(app, service, contest_id, forecast_profiles, forecast_records, meta, target, budget, release),
        "peakForecast": forecast_contest(app, service, contest_id, peak_profiles, forecast_records, meta, target, budget, release, "peak") if any(p["official"] for p in peak_profiles) else None,
        "backtest": backtest(app, service, principal, keys, platform, target, meta, release, by_owner, handles, remote, checked, now, rating_histories),
        "ratingRelease": {"method": release.get("method"), "revision": release.get("source_revision"), "problems": len(release["problems"])},
        "notes": ["评级为 CF 风格训练估计，不是官方 Rating；平台缺少兼容评级或 tags 的题不会补造数值。",
                  "个人整体结合官方当前/历史峰值、Recent 20 AC 和近半年移动均值；已过题难度分位数只用于 tag 相对强弱。多账号官方当前值取各自最新值中的最高值，综合估计不是官方 Rating。",
                  "只统计活跃个人绑定账号；已标记的团队账号及 CF 多人提交不计为个人训练。",
                  "多人共享的牛客 profile 按队伍账号单列；合并相同提交和题目，只计一份，不重复归到个人或形成双人覆盖。",
                  "无样本表示证据不足。训练目标参考线只影响覆盖与补强建议，不影响战力、概率或时间。"]}
