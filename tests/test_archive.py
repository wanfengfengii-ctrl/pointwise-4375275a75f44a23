import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from binomial.archive.store import ArchiveStore
from binomial.archive.schema import ArchiveFormatError, RequestConflict, ResultNotFound, content_digest, encode_value
from binomial.archive.fit_records import read_result
from binomial.cohort.batches import apply_cohort
from binomial.cohort.revisions import load_revision
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design
from binomial.fitting.service import fit, fit_request_fingerprint
from binomial.design.specification import load_design
from binomial.reporting.requests import validate_report_request, report_request_fingerprint
from binomial.archive.fit_records import load_fit
from binomial.reporting.service import report
from tests.support import MemoryCase, setup_analysis, observation, effect


class TestFrozenResults(unittest.TestCase):
    def test_correction_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.sqlite"
            store = ArchiveStore(path)
            rows = [observation("r", {"x": 1}, 4, 2)]
            receipt = apply_cohort(store, "c", "initial", rows)
            rules = [ColumnDefinition("x", source="x")]
            order = ["x"]
            spec = register_design(store, "d", order, rules)
            rows[0]["values"]["x"] = 8
            order[0] = "changed"
            rules.clear()
            old_fit = fit(store, "old", ("c", receipt.revision_id), "d")
            old_report = report(store, "old", old_fit, [effect("x", x=1)])
            old_values = read_result(store, old_fit), read_result(store, old_report)
            newer = apply_cohort(store, "c", "correct", [observation("r", {"x": 1}, 4, 3)])
            new_fit = fit(store, "new", ("c", newer.revision_id), "d")
            new_report = report(store, "new", new_fit, [effect("x", x=1)])
            store.close()
            with ArchiveStore(path) as reopened:
                self.assertEqual((read_result(reopened, old_fit), read_result(reopened, old_report)), old_values)
                new_value = read_result(reopened, new_fit)
                item = read_result(reopened, new_report)["items"][0]
                self.assertAlmostEqual(new_value["probabilities"][0], 0.75, delta=1e-8)
                self.assertAlmostEqual(item["estimate"], math.log(3), delta=1e-8)
                self.assertAlmostEqual(item["variance"], 4 / 3, delta=1e-8)
                old_item = old_values[1]["items"][0]
                self.assertEqual((old_item["estimate"], old_item["variance"]), (0, 1))
                self.assertEqual(read_result(reopened, old_report)["fit_id"], old_fit)
                self.assertEqual(read_result(reopened, new_report)["fit_id"], new_fit)
                self.assertEqual(new_value["frozen"]["design_digest"], spec.digest)
                self.assertNotEqual(new_value["frozen"]["revision_id"], receipt.revision_id)
                self.assertEqual(read_result(reopened, old_report)["revision_id"], receipt.revision_id)

    def test_return_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.sqlite"
            store = ArchiveStore(path)
            _, fit_id = setup_analysis(store, [observation("r", {"x": 1}, 4, 2)], ["x"])
            report_id = report(store, "effect", fit_id, [effect("x", x=1)])
            expected_fit, expected_report = read_result(store, fit_id), read_result(store, report_id)
            first_fit, first_report = read_result(store, fit_id), read_result(store, report_id)
            first_fit["probabilities"][0] = 0
            first_fit["frozen"]["row_ids"][0] = "forged"
            first_fit["diagnostics"]["status"] = "forged"
            first_report["items"][0]["coefficients"]["x"] = 8
            self.assertEqual(read_result(store, fit_id), expected_fit)
            self.assertEqual(read_result(store, report_id), expected_report)
            fresh = report(store, "fresh", fit_id, [effect("x", x=1)])
            self.assertEqual(read_result(store, fresh)["items"], expected_report["items"])
            store.close()
            with ArchiveStore(path) as reopened:
                self.assertEqual(read_result(reopened, fit_id), expected_fit)
                self.assertEqual(read_result(reopened, report_id), expected_report)

    def test_reopen_binding_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.sqlite"
            store = ArchiveStore(path)
            _, fit_id = setup_analysis(store, [observation("r", {"x": 1}, 4, 2)], ["x"])
            report_id = report(store, "effect", fit_id, [effect("x", x=1)])
            payload = store.get_record(report_id, "report")
            payload["report"]["revision_id"] = "wrong-revision"
            envelope = {"version": 1, "id": report_id, "kind": "report",
                        "payload": payload, "digest": content_digest(payload)}
            store.connection.execute("UPDATE records SET body=? WHERE id=?", (encode_value(envelope), report_id))
            store.close()
            with ArchiveStore(path) as reopened:
                with self.assertRaises(ArchiveFormatError):
                    read_result(reopened, report_id)
                self.assertEqual(read_result(reopened, fit_id)["probabilities"], [0.5])
                reopened.connection.execute("PRAGMA user_version=9")
            with self.assertRaises(ArchiveFormatError):
                ArchiveStore(path)


class TestPublication(unittest.TestCase):
    def test_fit_and_report_commit_failure(self):
        for failure in (1, 2, 3, 4, "commit"):
            with self.subTest(fit_failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fit.sqlite"
                store = ArchiveStore(path)
                receipt, old_fit = setup_analysis(store, [observation("r", {"x": 1}, 4, 2)], ["x"])
                old = read_result(store, old_fit)
                newer = apply_cohort(store, "study", "correct", [observation("r", {"x": 1}, 4, 3)])
                before = store.connection.execute("SELECT count(*) FROM records").fetchone()[0]
                fingerprint = fit_request_fingerprint(
                    load_revision(store, "study", newer.revision_id), load_design(store, "design"))
                candidate_id = "fit-" + content_digest({"request_id": "retry", "fingerprint": fingerprint})
                if failure == "commit":
                    store.arm_failure(before_commit=True)
                else:
                    store.arm_failure(write_number=failure)
                with self.assertRaises(sqlite3.OperationalError):
                    fit(store, "retry", ("study", newer.revision_id), "design")
                with self.assertRaises(ResultNotFound):
                    read_result(store, candidate_id)
                self.assertIsNone(store.get_receipt("fit", "retry"))
                self.assertEqual(store.connection.execute("SELECT count(*) FROM records").fetchone()[0], before)
                self.assertEqual(read_result(store, old_fit), old)
                store.close()
                with ArchiveStore(path) as reopened:
                    with self.assertRaises(ResultNotFound):
                        read_result(reopened, candidate_id)
                    self.assertIsNone(reopened.get_receipt("fit", "retry"))
                    new_fit = fit(reopened, "retry", ("study", newer.revision_id), "design")
                    self.assertEqual(fit(reopened, "retry", ("study", newer.revision_id), "design"), new_fit)
                    self.assertEqual(read_result(reopened, old_fit), old)
                    self.assertAlmostEqual(read_result(reopened, new_fit)["probabilities"][0], 0.75, delta=1e-8)
        for failure in (1, 2, "commit"):
            with self.subTest(report_failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "report.sqlite"
                store = ArchiveStore(path)
                _, fit_id = setup_analysis(store, [
                    observation("a", {"u": 1, "v": 0}, 1, 1),
                    observation("b", {"u": 0, "v": 1}, 2, 1),
                    observation("c", {"u": 0, "v": -1}, 2, 1)], ["u", "v"])
                effects = [effect("u", u=1), effect("v", v=1), effect("zero")]
                old_report = report(store, "old", fit_id, effects)
                old = read_result(store, old_report)
                before = store.connection.execute("SELECT count(*) FROM records").fetchone()[0]
                request = validate_report_request(fit_id, load_fit(store, fit_id).frozen.column_ids, effects)
                fingerprint = report_request_fingerprint(request)
                candidate_id = "report-" + content_digest({"request_id": "retry", "fingerprint": fingerprint})
                if failure == "commit":
                    store.arm_failure(before_commit=True)
                else:
                    store.arm_failure(write_number=failure)
                with self.assertRaises(sqlite3.OperationalError):
                    report(store, "retry", fit_id, effects)
                with self.assertRaises(ResultNotFound):
                    read_result(store, candidate_id)
                self.assertIsNone(store.get_receipt("report", "retry"))
                self.assertEqual(store.connection.execute("SELECT count(*) FROM records").fetchone()[0], before)
                store.close()
                with ArchiveStore(path) as reopened:
                    with self.assertRaises(ResultNotFound):
                        read_result(reopened, candidate_id)
                    self.assertIsNone(reopened.get_receipt("report", "retry"))
                    self.assertEqual(read_result(reopened, old_report), old)
                    new_report = report(reopened, "retry", fit_id, effects)
                    self.assertEqual(report(reopened, "retry", fit_id, effects), new_report)
                    self.assertEqual(read_result(reopened, new_report)["items"], old["items"])
                    with self.assertRaises(ResultNotFound):
                        read_result(reopened, "report-unpublished")

    def test_request_conflict(self):
        with ArchiveStore() as store:
            receipt, first_fit = setup_analysis(store, [observation("a", {"x": 1}, 4, 2)], ["x"])
            other = apply_cohort(store, "study", "correct", [observation("a", {"x": 1}, 4, 3)])
            second_fit = fit(store, "second", ("study", other.revision_id), "design")
            with self.assertRaises(RequestConflict):
                fit(store, "fit-input", ("study", other.revision_id), "design")
            first = report(store, "report", first_fit, [effect("x", x=1), effect("zero")])
            expected = read_result(store, first)
            for fit_id, effects in [(second_fit, [effect("x", x=1), effect("zero")]),
                                    (first_fit, [effect("zero"), effect("x", x=1)])]:
                with self.assertRaises(RequestConflict):
                    report(store, "report", fit_id, effects)
            self.assertEqual(read_result(store, first), expected)


class TestMemoryArchive(MemoryCase):
    def test_envelope_and_kind(self):
        _, fit_id = self.analyze([observation("r", {"x": 1}, 4, 2)], ["x"])
        body = self.store.connection.execute("SELECT body FROM records WHERE id=?", (fit_id,)).fetchone()[0]
        with self.assertRaises(ArchiveFormatError):
            self.store.get_record(fit_id, "report")
        for broken in [body.replace('"version":1', '"version":2'), body.replace('"published":true', '"published":false')]:
            self.store.connection.execute("UPDATE records SET body=? WHERE id=?", (broken, fit_id))
            with self.assertRaises(ArchiveFormatError):
                read_result(self.store, fit_id)
        self.store.connection.execute("UPDATE records SET body=? WHERE id=?", (body, fit_id))
        self.assertEqual(read_result(self.store, fit_id)["probabilities"], [0.5])
