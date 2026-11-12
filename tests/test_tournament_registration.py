import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import tournament_extension as tournament


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, payment_method="moncash"):
        self.payment_method = payment_method
        self.insert_query = None
        self.insert_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if "SELECT * FROM gomoku_tournaments" in query:
            return FakeResult({
                "tournament_id": "tourn_test_123",
                "status": "registration",
                "payment_method": self.payment_method,
                "entry_fee": Decimal("10.00"),
                "max_participants": 100,
            })
        if "SELECT COUNT(*) AS n" in query:
            return FakeResult({"n": 0})
        if "INSERT INTO gomoku_tournament_entries" in query:
            self.insert_query = query
            self.insert_params = params
            return FakeResult()
        raise AssertionError(f"Unexpected SQL in test: {query}")


class TournamentRegistrationTermsTests(unittest.TestCase):
    def test_terms_must_be_accepted_even_for_online_checkout(self):
        with patch.object(tournament, "_db", side_effect=AssertionError("DB must not be touched")):
            with self.assertRaisesRegex(tournament.TournamentError, "aksepte kondisyon"):
                tournament.register_entry(
                    "tourn_test_123", "player_1",
                    terms_accepted=False, online_checkout=True,
                )

    def test_manual_payment_requires_proof_after_terms_acceptance(self):
        fake_db = FakeConnection("moncash")
        with patch.object(tournament, "_db", return_value=fake_db):
            with self.assertRaisesRegex(tournament.TournamentError, "proof reference"):
                tournament.register_entry(
                    "tourn_test_123", "player_1", terms_accepted=True,
                )
        self.assertIsNone(fake_db.insert_query)

    def test_accepted_terms_are_persisted_with_entry(self):
        fake_db = FakeConnection("moncash")
        with patch.object(tournament, "_db", return_value=fake_db):
            result = tournament.register_entry(
                "tourn_test_123", "player_1",
                proof_data="private/proofs/test.png",
                terms_accepted=True,
            )
        self.assertTrue(result["ok"])
        self.assertIn("terms_accepted_at", fake_db.insert_query)
        self.assertIn("terms_snapshot", fake_db.insert_query)
        snapshot = json.loads(fake_db.insert_params[-1])
        self.assertEqual(snapshot["version"], "gomoku-tournament-terms-v1")
        self.assertTrue(snapshot["accepted"])


if __name__ == "__main__":
    unittest.main()
