import datetime as dt
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app


class InsightsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_path = app.DB_PATH
        app.DB_PATH = Path(self.temp_dir.name) / "insights.sqlite3"
        app.clear_overview_memory_cache()
        app.init_db()
        self.now = int(time.time())
        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO users(id, username, email, display_name, real_name, password_hash, verified, team_name, created_at)
                VALUES(1, 'alice', 'alice@local.invalid', 'Alice', '', 'test', 1, '校队', ?)
                """,
                (self.now,),
            )
            conn.execute(
                """
                INSERT INTO handles(id, owner_type, owner_id, platform, handle, active, created_at)
                VALUES(1, 'user', '1', 'codeforces', 'alice_cf', 1, ?)
                """,
                (self.now,),
            )
            conn.execute(
                """
                INSERT INTO handles(id, owner_type, owner_id, platform, handle, active, created_at, stats_json)
                VALUES(2, 'user', '1', 'leetcode', 'alice_lc', 1, ?, ?)
                """,
                (
                    self.now,
                    json.dumps(
                        {
                            "allTimeAccepted": 100,
                            "difficultyCounts": {"Easy": 60, "Medium": 35, "Hard": 5},
                        }
                    ),
                ),
            )

    def tearDown(self):
        app.clear_overview_memory_cache()
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def add_submission(self, platform, handle, remote_id, problem_id, submitted_at, raw, verdict="AC"):
        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO submissions(
                    owner_type, owner_id, platform, handle, remote_id, problem_id,
                    problem_name, verdict, language, submitted_at, url, raw_json, created_at
                )
                VALUES('user', '1', ?, ?, ?, ?, ?, ?, 'C++', ?, '', ?, ?)
                """,
                (
                    platform,
                    handle,
                    remote_id,
                    problem_id,
                    problem_id,
                    verdict,
                    submitted_at,
                    json.dumps(raw),
                    self.now,
                ),
            )

    def test_metrics_keep_calendar_activity_separate_from_verified_ac(self):
        day_one = self.now - 2 * 86400
        day_two = self.now - 86400
        self.add_submission(
            "codeforces",
            "alice_cf",
            "cf-1",
            "100A",
            day_one,
            {"contestId": 100, "problem": {"contestId": 100, "index": "A", "rating": 800}},
        )
        self.add_submission(
            "codeforces",
            "alice_cf",
            "cf-2",
            "100A",
            day_one + 60,
            {"contestId": 100, "problem": {"contestId": 100, "index": "A", "rating": 800}},
        )
        self.add_submission(
            "codeforces",
            "alice_cf",
            "cf-3",
            "100B",
            day_two,
            {"contestId": 100, "problem": {"contestId": 100, "index": "B", "rating": 1200}},
        )
        for index in range(2):
            self.add_submission(
                "leetcode",
                "alice_lc",
                f"activity-{index}",
                f"leetcode-activity-{index}",
                day_two + index,
                {"syntheticFromCalendar": True},
                verdict="ACTIVITY",
            )
        self.add_submission(
            "leetcode",
            "alice_lc",
            "recent-1",
            "two-sum",
            day_two + 120,
            {"titleSlug": "two-sum", "calendarCovered": True, "difficulty": "Easy"},
        )

        with app.connect_db() as conn:
            conn.execute(
                """
                INSERT INTO contests(
                    owner_type, owner_id, platform, handle, remote_id, contest_name,
                    category, participated_at, url, raw_json, created_at
                )
                VALUES('user', '1', 'codeforces', 'alice_cf', '100', 'Codeforces Round',
                       'codeforces.div2', ?, 'https://codeforces.com/contest/100', ?, ?)
                """,
                (
                    day_two,
                    json.dumps(
                        {
                            "ratingChange": {"rank": 10, "oldRating": 1400, "newRating": 1450},
                            "contest": {"startTimeSeconds": day_two, "durationSeconds": 7200},
                        }
                    ),
                    self.now,
                ),
            )

        result = app.build_insights(None, "user:1")
        first_date = app.utc_date_from_ts(day_one)
        second_date = app.utc_date_from_ts(day_two)
        daily = result["daily"]["all"]

        self.assertEqual(daily[first_date]["firstAc"], 1)
        self.assertEqual(daily[first_date]["uniqueAc"], 1)
        self.assertEqual(daily[first_date]["acceptedSubmissions"], 2)
        self.assertEqual(daily[first_date]["activity"], 2)
        self.assertEqual(daily[second_date]["firstAc"], 2)
        self.assertEqual(daily[second_date]["activity"], 3)
        self.assertEqual(result["summaries"]["all"]["careerSolved"], 102)

        difficulty = {item["platform"]: item for item in result["difficulty"]}
        self.assertEqual(
            difficulty["codeforces"]["buckets"],
            [{"label": "800", "count": 1}, {"label": "1200", "count": 1}],
        )
        self.assertEqual(difficulty["leetcode"]["total"], 100)
        self.assertEqual(result["ratings"][0]["points"][0]["newRating"], 1450)

    def test_leetcode_adapter_parses_public_profile_without_cookie(self):
        current_year = dt.datetime.now(dt.timezone.utc).year
        calendar = json.dumps({str(self.now - 86400): 2})

        def fake_post(url, payload, headers=None):
            operation = payload.get("operationName")
            if operation == "userProfileCalendar":
                return {
                    "data": {
                        "matchedUser": {
                            "username": "alice",
                            "submitStatsGlobal": {
                                "acSubmissionNum": [
                                    {"difficulty": "All", "count": 7},
                                    {"difficulty": "Easy", "count": 4},
                                    {"difficulty": "Medium", "count": 2},
                                    {"difficulty": "Hard", "count": 1},
                                ]
                            },
                            "userCalendar": {
                                "activeYears": [current_year],
                                "submissionCalendar": calendar,
                            },
                        },
                        "recentAcSubmissionList": [
                            {"id": "9", "title": "Two Sum", "titleSlug": "two-sum", "timestamp": str(self.now)}
                        ],
                    }
                }
            if operation == "userContestRankingHistory":
                return {"data": {"userContestRankingHistory": []}}
            raise AssertionError(operation)

        adapter = app.LeetCodeAdapter()
        with mock.patch.object(app, "http_post_json", side_effect=fake_post):
            rows = adapter.fetch_submissions("alice", self.now - 2 * 86400)
            stats = adapter.fetch_profile_stats("alice", rows)

        self.assertEqual(len([row for row in rows if row["raw"].get("syntheticFromCalendar")]), 2)
        self.assertEqual(len([row for row in rows if row["raw"].get("calendarCovered")]), 1)
        self.assertEqual(stats["allTimeAccepted"], 7)
        self.assertEqual(stats["difficultyCounts"], {"Easy": 4, "Medium": 2, "Hard": 1})

    def test_supported_platforms_replace_qoj_with_leetcode(self):
        platforms = [item["key"] for item in app.platform_meta()]
        self.assertIn("leetcode", platforms)
        self.assertNotIn("qoj", platforms)


if __name__ == "__main__":
    unittest.main()
