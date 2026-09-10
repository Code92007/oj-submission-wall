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
            for handle_id, owner_id, platform, handle in [
                (1, "1", "codeforces", "alice_cf"),
                (2, "1", "atcoder", "alice_at"),
                (3, "2", "vjudge", "bob_vj"),
                (4, "2", "codeforces", "bob_cf"),
            ]:
                conn.execute(
                    """
                    INSERT INTO handles(id, owner_type, owner_id, platform, handle, active, created_at)
                    VALUES(?, 'user', ?, ?, ?, 1, ?)
                    """,
                    (handle_id, owner_id, platform, handle, self.now),
                )

    def tearDown(self):
        app.clear_overview_memory_cache()
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def add_submission(
        self,
        owner_id,
        platform,
        handle,
        remote_id,
        problem_id,
        days_ago,
        verdict="AC",
        raw=None,
    ):
        submitted_at = self.now - days_ago * 86400
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
                    handle,
                    remote_id,
                    problem_id,
                    f"Problem {problem_id}",
                    verdict,
                    submitted_at,
                    f"https://example.test/{remote_id}",
                    json.dumps(raw or {}),
                    self.now,
                ),
            )

    def add_contest(self, owner_id, platform, handle, remote_id, days_ago):
        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO contests(
                    owner_type, owner_id, platform, handle, remote_id, contest_name,
                    category, participated_at, url, raw_json, created_at
                )
                VALUES('user', ?, ?, ?, ?, ?, 'other', ?, ?, '{}', ?)
                """,
                (
                    str(owner_id),
                    platform,
                    handle,
                    remote_id,
                    f"Contest {remote_id}",
                    self.now - days_ago * 86400,
                    f"https://example.test/contest/{remote_id}",
                    self.now,
                ),
            )

    def test_build_battle_uses_first_ac_and_deduplicates_contests(self):
        self.add_submission(1, "codeforces", "alice_cf", "a1", "100A", 12)
        self.add_submission(1, "codeforces", "alice_cf", "a1-later", "100A", 2)
        self.add_submission(2, "vjudge", "bob_vj", "b1", "CF-100A", 10, raw={"oj": "CF", "probNum": "100A"})

        self.add_submission(1, "codeforces", "alice_cf", "a2", "200A", 5)
        self.add_submission(2, "codeforces", "bob_cf", "b2", "200A", 7)
        self.add_submission(1, "atcoder", "alice_at", "a3", "abc100_a", 4)
        self.add_submission(2, "vjudge", "bob_vj", "b3", "AT-abc100_a", 4, raw={"oj": "AtCoder", "probNum": "abc100_a"})
        self.add_submission(1, "codeforces", "alice_cf", "only-a", "300A", 3)
        self.add_submission(2, "codeforces", "bob_cf", "only-b", "400A", 3)
        self.add_submission(1, "codeforces", "alice_cf", "wa", "500A", 1, verdict="WA")

        self.add_contest(1, "codeforces", "alice_cf", "1000", 8)
        self.add_contest(1, "codeforces", "alice_alt", "1000", 8)
        self.add_contest(2, "codeforces", "bob_cf", "1000", 8)
        self.add_contest(1, "atcoder", "alice_at", "abc100", 20)

        result = app.build_battle(None, "user:1", "user:2", "30")

        self.assertEqual(result["headToHead"], {
            "leftWins": 1,
            "rightWins": 1,
            "ties": 1,
            "commonSolved": 3,
            "knownCommonSolved": 3,
            "unrankedCommonSolved": 0,
            "leftOnly": 1,
            "rightOnly": 1,
            "sharedContests": 1,
        })
        self.assertEqual([player["stats"]["solved"] for player in result["players"]], [4, 4])
        self.assertEqual(len(result["sharedContests"]), 1)
        winners = {item["key"]: item["winner"] for item in result["commonProblems"]}
        self.assertEqual(winners["codeforces:100A"], "left")
        self.assertEqual(winners["codeforces:200A"], "right")
        self.assertEqual(winners["atcoder:abc100_a"], "tie")

    def test_all_time_totals_include_profile_problem_sets_without_scoring_them(self):
        self.add_submission(1, "codeforces", "alice_cf", "a1", "100A", 12)
        self.add_submission(2, "codeforces", "bob_cf", "b1", "100A", 10)
        alice_stats = {
            "allTimeAccepted": 1,
            "solvedProblems": [{"canonicalKey": "luogu:P9000"}],
        }
        bob_stats = {
            "allTimeAccepted": 2,
            "solvedProblems": [
                {"canonicalKey": "luogu:P9000"},
                {"canonicalKey": "luogu:P9001"},
            ],
        }
        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO handles(owner_type, owner_id, platform, handle, active, created_at, stats_json)
                VALUES('user', '1', 'luogu', 'alice_lg', 1, ?, ?)
                """,
                (self.now, json.dumps(alice_stats)),
            )
            conn.execute(
                """
                INSERT INTO handles(owner_type, owner_id, platform, handle, active, created_at, stats_json)
                VALUES('user', '2', 'luogu', 'bob_lg', 1, ?, ?)
                """,
                (self.now, json.dumps(bob_stats)),
            )

        all_time = app.build_battle(None, "user:1", "user:2", "all")
        recent = app.build_battle(None, "user:1", "user:2", "30")

        self.assertEqual([player["stats"]["solved"] for player in all_time["players"]], [2, 3])
        self.assertEqual([player["stats"]["profileOnlySolved"] for player in all_time["players"]], [1, 2])
        self.assertEqual(all_time["headToHead"]["commonSolved"], 1)
        self.assertEqual(all_time["headToHead"]["knownCommonSolved"], 2)
        self.assertEqual(all_time["headToHead"]["unrankedCommonSolved"], 1)
        self.assertEqual([player["stats"]["solved"] for player in recent["players"]], [1, 1])
        self.assertEqual([player["stats"]["profileOnlySolved"] for player in recent["players"]], [0, 0])

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
