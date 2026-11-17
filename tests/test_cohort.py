from binomial.archive.schema import RequestConflict
from binomial.cohort.batches import apply_cohort
from binomial.cohort.revisions import load_revision
from tests.support import MemoryCase, observation


class TestCohortBatches(MemoryCase):
    def baseline(self):
        return apply_cohort(self.store, "c", "initial", [observation("a", {"x": 1}, 4, 2)])

    def state(self):
        return (self.store.current_revision("c"), self.count("records"), self.count("receipts"))

    def test_invalid_count_atomicity(self):
        self.baseline()
        before, revision = self.state(), load_revision(self.store, "c")
        with self.assertRaises(ValueError):
            apply_cohort(self.store, "c", "bad", [observation("a", {"x": 1}, 4, 3),
                                                 observation("b", {"x": 1}, 2, 3)])
        self.assertEqual(self.state(), before)
        self.assertEqual(load_revision(self.store, "c"), revision)
        self.assertIsNone(self.store.get_receipt("cohort:c", "bad"))

    def test_batch_replay(self):
        rows = [observation("a", {"x": 1}, 4, 2), observation("b", {"x": 1}, 4, 2)]
        original = apply_cohort(self.store, "c", "request", rows)
        before = self.state()
        self.assertEqual(apply_cohort(self.store, "c", "request", reversed(rows)), original)
        self.assertEqual(self.state(), before)
        newer = apply_cohort(self.store, "c", "new", [observation("a", {"x": 1}, 4, 3)])
        after = self.state()
        self.assertEqual(apply_cohort(self.store, "c", "request", rows), original)
        self.assertEqual(self.state(), after)
        self.assertEqual(load_revision(self.store, "c").revision_id, newer.revision_id)
        with self.assertRaises(RequestConflict):
            apply_cohort(self.store, "c", "request", [observation("a", {"x": 1}, 4, 1)])
        self.assertEqual(self.state(), after)
        same = apply_cohort(self.store, "c", "unchanged", [observation("a", {"x": 1}, 4, 3)])
        self.assertEqual(same.revision_id, newer.revision_id)

    def test_identity_validation(self):
        self.baseline()
        before = self.state()
        invalid = [
            [observation("a", {"x": 1}, True, 0)],
            [observation("a", {"x": 1}, 4, False)],
            [observation("a", {"x": 1}, 0, 0)],
            [observation("a", {"x": 1}, 21, 2)],
            [observation("a", {"x": 1}, 4.0, 2)],
            [observation("a", {"x": 9}, 4, 2)],
            [observation("a", {"x": True}, 4, 2)],
            [observation("a", {"x": 1}, 4, 2)] * 2,
            [observation("r" + str(i), {"x": 1}, 4, 2) for i in range(12)],
        ]
        for index, rows in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                apply_cohort(self.store, "c", "bad-" + str(index), rows)
            self.assertEqual(self.state(), before)
        receipt = apply_cohort(self.store, "c", "duplicates",
                              [observation("b", {"x": 1}, 4, 2)])
        self.assertEqual(len(load_revision(self.store, "c", receipt.revision_id).rows), 2)

    def test_cohort_write_failure(self):
        self.baseline()
        before = self.state()
        self.store.arm_failure(write_number=2)
        with self.assertRaises(Exception) as error:
            apply_cohort(self.store, "c", "retry", [observation("a", {"x": 1}, 4, 3)])
        import sqlite3
        self.assertIsInstance(error.exception, sqlite3.OperationalError)
        self.assertEqual(self.state(), before)
        apply_cohort(self.store, "c", "retry", [observation("a", {"x": 1}, 4, 3)])
