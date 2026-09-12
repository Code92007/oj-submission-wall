import datetime as dt
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

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
                (4, "dave", "Dave"),
                (5, "erin", "Erin"),
                (6, "frank", "Frank"),
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
                "sameTeamContests": 0,
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

    def test_same_nowcoder_team_is_excluded_from_timeline_and_duels(self):
        first_start = self.now - 2 * 86400
        second_start = self.now - 86400
        for owner_id, rank, team_id in [(1, 100, "alice-team"), (2, 300, "bob-team")]:
            self.add_contest(
                owner_id,
                "nowcoder",
                "team-warmup",
                first_start,
                {
                    "contestId": "team-warmup",
                    "rank": rank,
                    "canShowRank": True,
                    "userCount": 1000,
                    "teamId": team_id,
                    "startTime": first_start * 1000,
                    "endTime": (first_start + 7200) * 1000,
                },
            )
        for owner_id in [1, 2]:
            self.add_contest(
                owner_id,
                "nowcoder",
                "shared-team",
                second_start,
                {
                    "contestId": "shared-team",
                    "rank": 900,
                    "canShowRank": True,
                    "userCount": 1000,
                    "teamId": "same-multischool-team",
                    "startTime": second_start * 1000,
                    "endTime": (second_start + 7200) * 1000,
                },
            )

        result = app.build_battle(None, "user:1", "user:2", "30")

        self.assertEqual(result["headToHead"]["rankedContests"], 1)
        self.assertEqual(result["headToHead"]["sameTeamContests"], 1)
        self.assertEqual(result["headToHead"]["ties"], 0)
        self.assertEqual([point["winner"] for point in result["timeline"]["points"]], ["left"])
        self.assertNotIn("shared-team", {point["remoteId"] for point in result["timeline"]["points"]})
        match = next(item for item in result["sharedContests"] if item["remoteId"] == "shared-team")
        self.assertTrue(match["sameTeam"])
        self.assertEqual(match["speed"]["problems"], 0)

    def test_two_poor_ranks_can_both_lose_rating(self):
        start = self.now - 86400
        for owner_id, rank, team_id in [(1, 900, "alice-team"), (2, 950, "bob-team")]:
            self.add_contest(
                owner_id,
                "nowcoder",
                "poor-round",
                start,
                {
                    "contestId": "poor-round",
                    "rank": rank,
                    "canShowRank": True,
                    "userCount": 1000,
                    "teamId": team_id,
                    "startTime": start * 1000,
                    "endTime": (start + 7200) * 1000,
                },
            )

        result = app.build_battle(None, "user:1", "user:2", "30")

        point = result["timeline"]["points"][0]
        self.assertEqual(point["winner"], "left")
        self.assertLess(point["leftAbsoluteChange"], 0)
        self.assertLess(point["rightAbsoluteChange"], 0)
        self.assertLess(point["leftChange"], 0)
        self.assertLess(point["rightChange"], 0)
        self.assertLess(result["timeline"]["leftRating"], result["timeline"]["initialRating"])
        self.assertLess(result["timeline"]["rightRating"], result["timeline"]["initialRating"])

    def test_official_rating_drop_overrides_positive_rank_percentile(self):
        start = self.now - 86400
        for owner_id, rank, rating_delta, team_id in [
            (1, 320, -54, "alice-team"),
            (2, 377, -93, "bob-team"),
        ]:
            self.add_contest(
                owner_id,
                "nowcoder",
                "rated-drop",
                start,
                {
                    "contestId": "rated-drop",
                    "rank": rank,
                    "canShowRank": True,
                    "userCount": 1447,
                    "teamId": team_id,
                    "rating": 1800 + rating_delta,
                    "changeValue": rating_delta,
                    "ratingStatus": "YES",
                    "startTime": start * 1000,
                    "endTime": (start + 7200) * 1000,
                },
            )

        result = app.build_battle(None, "user:1", "user:2", "30")

        point = result["timeline"]["points"][0]
        self.assertEqual(point["leftAbsoluteSource"], "official-rating")
        self.assertEqual(point["rightAbsoluteSource"], "official-rating")
        self.assertLess(point["leftChange"], 0)
        self.assertLess(point["rightChange"], 0)

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

    def test_codeforces_virtual_rank_counts_as_a_contest_result(self):
        start = self.now - 4 * 86400
        contest = {
            "id": 4000,
            "name": "Codeforces Virtual Match",
            "phase": "FINISHED",
            "type": "CF",
            "startTimeSeconds": start,
            "durationSeconds": 7200,
        }
        self.add_contest(
            1,
            "codeforces",
            "4000",
            start,
            {
                "contest": contest,
                "ratingChange": {"contestId": 4000, "rank": 910, "oldRating": 1560, "newRating": 1631},
            },
        )
        self.add_contest(
            2,
            "codeforces",
            "4000",
            start,
            {
                "contest": contest,
                "virtualResult": {
                    "rank": 350,
                    "score": 3061,
                    "solved": 4,
                    "participants": 8620,
                    "participantType": "OUT_OF_COMPETITION",
                    "rankKind": "virtual-equivalent",
                    "startTimeSeconds": start,
                },
            },
        )

        result = app.build_battle(None, "user:1", "user:2", "30")

        self.assertEqual(result["headToHead"]["rankedContests"], 1)
        self.assertEqual(result["headToHead"]["rightWins"], 1)
        match = result["sharedContests"][0]
        self.assertEqual(match["winner"], "right")
        self.assertEqual(match["rightResult"]["rank"], 350)
        self.assertEqual(match["rightResult"]["rankKind"], "virtual-equivalent")
        self.assertEqual(match["rightResult"]["participantType"], "OUT_OF_COMPETITION")
        self.assertFalse(match["rightResult"]["rated"])
        self.assertEqual([player["stats"]["ratedContests"] for player in result["players"]], [1, 0])

    def test_codeforces_virtual_result_uses_contest_scoring(self):
        start = self.now - 86400
        summary = {
            "contest": {"type": "CF", "startTimeSeconds": start, "durationSeconds": 7200},
            "problems": [{"index": "A", "points": 500}, {"index": "B", "points": 1000}],
            "rows": [[1500, 0], [1350, 0], [1000, 0]],
            "icpcPenaltyMinutes": 20,
        }

        def submission(problem, verdict, seconds, participant_type="VIRTUAL"):
            return {
                "submitted_at": start + seconds,
                "raw": {
                    "creationTimeSeconds": start + seconds,
                    "relativeTimeSeconds": seconds,
                    "verdict": verdict,
                    "problem": {"index": problem},
                    "author": {
                        "participantType": participant_type,
                        "startTimeSeconds": start,
                    },
                },
            }

        submissions = [
            submission("A", "OK", 600),
            submission("B", "WRONG_ANSWER", 1200),
            submission("B", "OK", 1800),
            submission("B", "OK", 9000, "PRACTICE"),
        ]

        virtual = app.codeforces_unofficial_result(summary, submissions)
        self.assertEqual(virtual["rank"], 3)
        self.assertEqual(virtual["score"], 1310)
        self.assertEqual(virtual["solved"], 2)
        self.assertEqual(virtual["participantType"], "VIRTUAL")

        for item in submissions[:3]:
            item["raw"]["author"]["participantType"] = "OUT_OF_COMPETITION"
        unofficial = app.codeforces_unofficial_result(summary, submissions)
        self.assertEqual(unofficial["rank"], 2)
        self.assertEqual(unofficial["score"], 1360)

    def test_codeforces_adapter_attaches_virtual_result(self):
        start = self.now - 86400
        contest = {
            "id": 5000,
            "name": "Codeforces VP Round",
            "phase": "FINISHED",
            "type": "CF",
            "startTimeSeconds": start,
            "durationSeconds": 7200,
        }
        summary = {
            "contest": contest,
            "problems": [{"index": "A", "points": 500}],
            "rows": [[500, 0], [400, 0]],
            "icpcPenaltyMinutes": 20,
        }
        submission = {
            "remote_id": "vp-1",
            "submitted_at": start + 600,
            "raw": {
                "contestId": 5000,
                "creationTimeSeconds": start + 600,
                "relativeTimeSeconds": 600,
                "verdict": "OK",
                "problem": {"contestId": 5000, "index": "A"},
                "author": {"participantType": "VIRTUAL", "startTimeSeconds": start},
            },
        }
        with (
            mock.patch.object(app, "codeforces_contest_lookup", return_value={5000: contest}),
            mock.patch.object(app, "http_get_json", return_value={"status": "OK", "result": []}),
            mock.patch.object(app, "read_codeforces_standings_summary", return_value=summary),
            mock.patch.object(app, "codeforces_standings_summary", return_value=summary),
        ):
            contests = app.CodeforcesAdapter().fetch_contests(
                "alice_codeforces",
                start,
                [submission],
            )

        self.assertEqual(len(contests), 1)
        virtual_result = contests[0]["raw"]["virtualResult"]
        self.assertEqual(virtual_result["rank"], 2)
        self.assertEqual(virtual_result["score"], 480)
        self.assertEqual(virtual_result["participantType"], "VIRTUAL")

    def test_build_battle_rejects_same_or_unknown_member(self):
        with self.assertRaisesRegex(ValueError, "不同"):
            app.build_battle(None, "user:1", "user:1", "all")
        with self.assertRaisesRegex(ValueError, "不可见"):
            app.build_battle(None, "user:1", "guest:missing", "all")
        with self.assertRaisesRegex(ValueError, "时间范围"):
            app.build_battle(None, "user:1", "user:2", "week")

    def test_individual_competition_ranks_round_robin_results(self):
        start = self.now - 86400
        for owner_id, rank in [(1, 10), (2, 20), (3, 30)]:
            self.add_contest(
                owner_id,
                "nowcoder",
                "ranking-round",
                start,
                {
                    "contestId": "ranking-round",
                    "rank": rank,
                    "canShowRank": True,
                    "userCount": 100,
                    "teamId": f"individual-{owner_id}",
                    "startTime": start * 1000,
                    "endTime": (start + 7200) * 1000,
                },
            )

        result = app.build_competition(
            None,
            "individual",
            range_key="30",
            member_keys=["user:1", "user:2", "user:3"],
        )

        self.assertEqual([item["displayName"] for item in result["rankings"]], ["Alice", "Bob", "Carol"])
        self.assertEqual([item["rank"] for item in result["rankings"]], [1, 2, 3])
        self.assertEqual([item["stats"]["points"] for item in result["rankings"]], [6, 3, 0])
        self.assertEqual([item["stats"]["contestWins"] for item in result["rankings"]], [2, 1, 0])
        self.assertEqual(len(result["comparisons"]), 3)

    def test_team_competition_aggregates_all_nine_cross_team_pairs(self):
        start = self.now - 86400
        for owner_id, rank in enumerate([10, 20, 30, 40, 50, 60], start=1):
            self.add_contest(
                owner_id,
                "nowcoder",
                "team-round",
                start,
                {
                    "contestId": "team-round",
                    "rank": rank,
                    "canShowRank": True,
                    "userCount": 100,
                    "teamId": f"team-entry-{owner_id}",
                    "startTime": start * 1000,
                    "endTime": (start + 7200) * 1000,
                },
            )

        result = app.build_competition(
            None,
            "team",
            range_key="30",
            left_keys=["user:1", "user:2", "user:3"],
            right_keys=["user:4", "user:5", "user:6"],
        )

        left, right = result["teams"]
        self.assertEqual(len(result["comparisons"]), 9)
        self.assertEqual(left["stats"]["pairWins"], 9)
        self.assertEqual(left["stats"]["contestWins"], 9)
        self.assertEqual(left["stats"]["points"], 27)
        self.assertEqual(right["stats"]["pairLosses"], 9)
        self.assertEqual(right["stats"]["contestWins"], 0)
        self.assertEqual([member["displayName"] for member in left["members"]], ["Alice", "Bob", "Carol"])
        self.assertEqual([member["stats"]["points"] for member in left["members"]], [9, 9, 9])

    def test_competition_rejects_invalid_rosters(self):
        with self.assertRaisesRegex(ValueError, "2 至 5"):
            app.build_competition(None, "individual", member_keys=["user:1"])
        with self.assertRaisesRegex(ValueError, "每队选择 3"):
            app.build_competition(
                None,
                "team",
                left_keys=["user:1", "user:2"],
                right_keys=["user:4", "user:5", "user:6"],
            )
        with self.assertRaisesRegex(ValueError, "不能重复"):
            app.build_competition(
                None,
                "team",
                left_keys=["user:1", "user:2", "user:3"],
                right_keys=["user:3", "user:4", "user:5"],
            )

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
