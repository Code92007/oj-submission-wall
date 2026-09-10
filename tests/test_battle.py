import datetime as dt
import json
import tempfile
import time
import unittest
from pathlib import Path

import app


class BattleOverviewTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app.DB_PATH
        app.DB_PATH = Path(self.temp_dir.name) / "battle.sqlite3"
        app.clear_overview_memory_cache()
        app.init_db()
        self.now = int(time.time())
        with app.connect_db() as conn:
            for user_id, username, display_name in [
                (1, "alice", "Alice"),
                (2, "bob", "Bob"),
                (3, "carol", "Carol"),
            ]:
                conn.execute(
                    """
                    INSERT INTO users(id, username, email, display_name, real_name, password_hash, verified, team_name, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, 1, '校队', ?)
                    """,
                    (user_id, username, f"{username}@local.invalid", display_name, display_name, "test", self.now),
                )
            handles = []
            handle_id = 1
            for owner_id, prefix in [("1", "alice"), ("2", "bob")]:
                for platform in ["codeforces", "atcoder", "nowcoder", "vjudge"]:
                    handles.append((handle_id, owner_id, platform, f"{prefix}_{platform}"))
                    handle_id += 1
            conn.executemany(
                """
                INSERT INTO handles(id, owner_type, owner_id, platform, handle, active, created_at)
                VALUES(?, 'user', ?, ?, ?, 1, ?)
                """,
                [(handle_id, owner_id, platform, handle, self.now) for handle_id, owner_id, platform, handle in handles],
            )

    def tearDown(self):
        app.clear_overview_memory_cache()
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def handle(self, owner_id, platform):
        return f"{'alice' if str(owner_id) == '1' else 'bob'}_{platform}"

    def add_submission(self, owner_id, platform, remote_id, problem_id, submitted_at, raw, verdict="AC"):
        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO submissions(
                    owner_type, owner_id, platform, handle, remote_id, problem_id,
                    problem_name, verdict, language, submitted_at, url, raw_json, created_at
                )
                VALUES('user', ?, ?, ?, ?, ?, ?, ?, 'C++', ?, ?, ?, ?)
                """,
                (
                    str(owner_id),
                    platform,
                    self.handle(owner_id, platform),
                    remote_id,
                    problem_id,
                    f"Problem {problem_id}",
                    verdict,
                    submitted_at,
                    f"https://example.test/submission/{remote_id}",
                    json.dumps(raw),
                    self.now,
                ),
            )

    def add_contest(self, owner_id, platform, remote_id, participated_at, raw):
        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO contests(
                    owner_type, owner_id, platform, handle, remote_id, contest_name,
                    category, participated_at, url, raw_json, created_at
                )
                VALUES('user', ?, ?, ?, ?, ?, 'other', ?, ?, ?, ?)
                """,
                (
                    str(owner_id),
                    platform,
                    self.handle(owner_id, platform),
                    remote_id,
                    f"Contest {remote_id}",
                    participated_at,
                    f"https://example.test/contest/{remote_id}",
                    json.dumps(raw),
                    self.now,
                ),
            )

    def add_codeforces_match(self, start):
        contest = {"id": 1000, "startTimeSeconds": start, "durationSeconds": 7200, "type": "CF"}
        for owner_id, rank, old_rating, new_rating in [(1, 120, 1500, 1530), (2, 300, 1600, 1580)]:
            self.add_contest(
                owner_id,
                "codeforces",
                "1000",
                start,
                {
                    "contest": contest,
                    "ratingChange": {
                        "contestId": 1000,
                        "rank": rank,
                        "oldRating": old_rating,
                        "newRating": new_rating,
                    },
                },
            )

        def cf_raw(owner_id, participant_type="CONTESTANT"):
            return {
                "contestId": 1000,
                "problem": {"contestId": 1000},
                "author": {
                    "participantType": participant_type,
                    "startTimeSeconds": start,
                    "members": [{"handle": self.handle(owner_id, "codeforces")}],
                },
            }

        self.add_submission(1, "codeforces", "cf-a1", "1000A", start + 600, cf_raw(1))
        self.add_submission(1, "codeforces", "cf-b1", "1000B", start + 1800, cf_raw(1))
        self.add_submission(2, "codeforces", "cf-a2", "1000A", start + 900, cf_raw(2))
        self.add_submission(2, "codeforces", "cf-c2", "1000C", start + 1200, cf_raw(2))
        self.add_submission(2, "codeforces", "cf-b-practice", "1000B", start + 500, cf_raw(2, "PRACTICE"))

    def add_atcoder_match(self, start):
        end = start + 7200
        end_time = dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat()
        metadata = {"start_epoch_second": start, "duration_second": 7200}
        for owner_id, rank, old_rating, new_rating in [(1, 100, 1800, 1810), (2, 50, 1750, 1780)]:
            self.add_contest(
                owner_id,
                "atcoder",
                "abc999",
                end,
                {
                    "id": "abc999",
                    "Place": rank,
                    "OldRating": old_rating,
                    "NewRating": new_rating,
                    "Performance": new_rating + 100,
                    "IsRated": True,
                    "EndTime": end_time,
                    "contest": metadata,
                },
            )
        self.add_submission(1, "atcoder", "at-a1", "abc999_a", start + 600, {"contest_id": "abc999"})
        self.add_submission(2, "atcoder", "at-a2", "abc999_a", start + 300, {"contest_id": "abc999"})
        self.add_submission(1, "atcoder", "at-upsolve", "abc999_b", end + 3600, {"contest_id": "abc999"})

    def add_nowcoder_match(self, start):
        for owner_id, rank, solved in [(1, 13, 6), (2, 13, 5)]:
            self.add_contest(
                owner_id,
                "nowcoder",
                "2000",
                start,
                {
                    "contestId": 2000,
                    "rank": rank,
                    "canShowRank": True,
                    "acceptedCount": solved,
                    "totalScore": 100 * solved,
                    "userCount": 500,
                    "startTime": start * 1000,
                    "endTime": (start + 7200) * 1000,
                    "contestDuration": 7200 * 1000,
                    "ratingStatus": "NO",
                },
            )

    def test_battle_uses_official_contest_ranks_and_in_contest_speed_only(self):
        self.add_codeforces_match(self.now - 10 * 86400)
        self.add_atcoder_match(self.now - 6 * 86400)
        self.add_nowcoder_match(self.now - 3 * 86400)
        for owner_id in [1, 2]:
            self.add_contest(owner_id, "vjudge", "3000", self.now - 86400, {"contestId": 3000})

        result = app.build_battle(None, "user:1", "user:2", "30")

        self.assertEqual(
            result["headToHead"],
            {
                "leftWins": 1,
                "rightWins": 1,
                "ties": 1,
                "rankedContests": 3,
                "unrankedContests": 1,
                "sharedContests": 4,
                "leftSpeedWins": 2,
                "rightSpeedWins": 2,
                "speedTies": 0,
                "speedProblems": 4,
            },
        )
        self.assertNotIn("commonProblems", result)
        self.assertEqual([player["stats"]["ratedContests"] for player in result["players"]], [2, 2])
        self.assertEqual(len(result["timeline"]["points"]), 3)
        self.assertEqual([point["winner"] for point in result["timeline"]["points"]], ["left", "right", "tie"])

        contests = {(item["platform"], item["remoteId"]): item for item in result["sharedContests"]}
        codeforces = contests[("codeforces", "1000")]
        self.assertEqual(codeforces["leftResult"]["rank"], 120)
        self.assertEqual(codeforces["rightResult"]["rank"], 300)
        self.assertEqual(codeforces["speed"], {"leftWins": 2, "rightWins": 1, "ties": 0, "problems": 3})
        self.assertEqual({item["problemId"] for item in codeforces["problemDuels"]}, {"1000A", "1000B", "1000C"})

        atcoder = contests[("atcoder", "abc999")]
        self.assertEqual(atcoder["winner"], "right")
        self.assertEqual(atcoder["speed"], {"leftWins": 0, "rightWins": 1, "ties": 0, "problems": 1})
        self.assertNotIn("abc999_b", {item["problemId"] for item in atcoder["problemDuels"]})

        nowcoder = contests[("nowcoder", "2000")]
        self.assertEqual(nowcoder["winner"], "tie")
        self.assertEqual(nowcoder["leftResult"]["solved"], 6)
        self.assertEqual(nowcoder["speed"]["problems"], 0)
        self.assertIsNone(contests[("vjudge", "3000")]["winner"])

    def test_range_filters_contests_instead_of_daily_problem_activity(self):
        self.add_codeforces_match(self.now - 60 * 86400)
        self.add_submission(
            1,
            "codeforces",
            "daily-ac",
            "9999A",
            self.now - 2 * 86400,
            {"contestId": 9999, "author": {"participantType": "PRACTICE"}},
        )
        result = app.build_battle(None, "user:1", "user:2", "30")
        self.assertEqual(result["headToHead"]["sharedContests"], 0)
        self.assertEqual(result["headToHead"]["speedProblems"], 0)
        self.assertEqual([player["stats"]["contests"] for player in result["players"]], [0, 0])

    def test_build_battle_rejects_same_or_unknown_member(self):
        with self.assertRaisesRegex(ValueError, "不同"):
            app.build_battle(None, "user:1", "user:1", "all")
        with self.assertRaisesRegex(ValueError, "不可见"):
            app.build_battle(None, "user:1", "guest:missing", "all")
        with self.assertRaisesRegex(ValueError, "时间范围"):
            app.build_battle(None, "user:1", "user:2", "week")

    def test_battle_cache_prunes_oldest_entries_at_the_limit(self):
        original_limit = app.BATTLE_MEMORY_CACHE_LIMIT
        try:
            app.BATTLE_MEMORY_CACHE_LIMIT = 8
            app.BATTLE_MEMORY_CACHE.clear()
            for index in range(12):
                app.BATTLE_MEMORY_CACHE[(str(index),)] = (self.now - index, {"index": index})

            app.prune_battle_memory_cache(self.now)

            self.assertEqual(len(app.BATTLE_MEMORY_CACHE), 8)
            self.assertEqual({value[1]["index"] for value in app.BATTLE_MEMORY_CACHE.values()}, set(range(8)))
        finally:
            app.BATTLE_MEMORY_CACHE_LIMIT = original_limit
            app.BATTLE_MEMORY_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
