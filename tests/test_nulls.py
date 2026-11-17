import math
import sqlite3
import tempfile
import unittest
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from binomial.archive.fit_records import load_fit, read_result
from binomial.archive.schema import (
    ArchiveFormatError, RequestConflict, ResultNotFound, content_digest, encode_value,
)
from binomial.archive.store import ArchiveStore
from binomial.cohort.batches import apply_cohort
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design
from binomial.fitting.constrained import null_request_fingerprint, validate_null_request
from binomial.fitting.service import fit, fit_null
from binomial.reporting.service import compare_null, comparison_request_fingerprint, report
from null_examples import cases, prepare_original
from tests.support import MemoryCase, observation, effect

UV_ROWS = [observation("a", {"u": 1, "v": 0}, 1, 1),
           observation("b", {"u": 0, "v": 1}, 2, 1),
           observation("c", {"u": 0, "v": -1}, 2, 1)]


def to_decimal(value):
    return Decimal(value.numerator) / Decimal(value.denominator)


def decimal_offset_reference(a, o, n, k):
    """Independent high-precision one-dimensional constrained solve.

    Bisects the exact score equation with Decimal arithmetic; shares no code
    with the production solvers.
    """
    with localcontext() as context:
        context.prec = 70
        aa = [to_decimal(Fraction(row)) for row in a]
        oo = [to_decimal(Fraction(v)) for v in o]

        def score(theta):
            total = Decimal(0)
            for ai, oi, ni, ki in zip(aa, oo, n, k):
                eta = oi + ai * theta
                p = 1 / (1 + (-eta).exp())
                total += ai * (Decimal(ki) - ni * p)
            return total

        low, high = Decimal(-300), Decimal(300)
        for _ in range(300):
            mid = (low + high) / 2
            if score(mid) > 0:
                low = mid
            else:
                high = mid
        theta = (low + high) / 2
        probabilities = []
        likelihood = Decimal(0)
        for ai, oi, ni, ki in zip(aa, oo, n, k):
            eta = oi + ai * theta
            p = 1 / (1 + (-eta).exp())
            probabilities.append(float(p))
            if ki:
                likelihood += ki * p.ln()
            if ni != ki:
                likelihood += (ni - ki) * (1 - p).ln()
        return probabilities, float(likelihood)


class TestNullExamples(MemoryCase):
    def test_fixed_examples(self):
        for case in cases():
            with self.subTest(case=case["name"]):
                fit_id = prepare_original(self.store, case, case["name"])
                null_id = fit_null(self.store, "null-" + case["name"], fit_id, case["equations"])
                value = read_result(self.store, null_id)
                self.assertEqual(value["kind"], "null_fit")
                self.assertEqual(value["fit_id"], fit_id)
                self.assertEqual(value["frozen"], read_result(self.store, fit_id)["frozen"])
                self.assertEqual(value["boundary"], case["null_boundary"])
                self.assertEqual(len(value["probabilities"]), len(case["null_probabilities"]))
                for actual, expected in zip(value["probabilities"], case["null_probabilities"]):
                    self.assertAlmostEqual(actual, expected, delta=1e-8)
                self.assertAlmostEqual(value["log_likelihood"], case["null_log_likelihood"], delta=1e-8)
                expected_equations = [
                    {"coefficients": {c: Fraction(v) for c, v in eq["coefficients"].items()},
                     "rhs": Fraction(eq["rhs"])} for eq in case["equations"]]
                self.assertEqual(value["equations"], expected_equations)
                comparison_id = compare_null(self.store, "cmp-" + case["name"], null_id)
                comparison = read_result(self.store, comparison_id)
                self.assertEqual(comparison["kind"], "null_comparison")
                self.assertEqual(comparison["fit_id"], fit_id)
                self.assertEqual(comparison["null_id"], null_id)
                original = read_result(self.store, fit_id)
                self.assertEqual(comparison["original_log_likelihood"],
                                 original["diagnostics"]["log_likelihood"])
                self.assertEqual(comparison["null_log_likelihood"], value["log_likelihood"])
                self.assertAlmostEqual(comparison["statistic"], case["statistic"], delta=1e-8)
                self.assertEqual(comparison["statistic"], 2 * (
                    comparison["original_log_likelihood"] - comparison["null_log_likelihood"]))
                self.assertNotIn("p_value", comparison)
                self.assertNotIn("pvalue", comparison)

    def test_independent_decimal_audit(self):
        """Decimal reference solves against production outputs (no shared solver)."""
        references = {
            "restore_boundary": ([0, 1, -1], [0, 0, 0]),
            "nonzero_rhs": ([0, 1, -1], [1, 0, 0]),
            "coupled": ([-1, 1, -1], [1, 0, 0]),
        }
        for case in cases():
            if case["name"] not in references:
                continue
            with self.subTest(case=case["name"]):
                a, o = references[case["name"]]
                rows = sorted(case["rows"], key=lambda row: row["row_id"])
                n = [row["n"] for row in rows]
                k = [row["k"] for row in rows]
                probabilities, likelihood = decimal_offset_reference(a, o, n, k)
                fit_id = prepare_original(self.store, case, "audit-" + case["name"])
                null_id = fit_null(self.store, "audit-null-" + case["name"], fit_id,
                                   case["equations"])
                value = read_result(self.store, null_id)
                for actual, expected in zip(value["probabilities"], probabilities):
                    self.assertAlmostEqual(actual, expected, delta=1e-8)
                self.assertAlmostEqual(value["log_likelihood"], likelihood, delta=1e-8)

    def test_unidentified_difference_decimal_audit(self):
        case = next(c for c in cases() if c["name"] == "unidentified_difference")
        probabilities, likelihood = decimal_offset_reference([2], [1], [4], [3])
        self.assertAlmostEqual(probabilities[0], 0.75, delta=1e-8)
        fit_id = prepare_original(self.store, case, "audit-diff")
        null_id = fit_null(self.store, "audit-diff-null", fit_id, case["equations"])
        value = read_result(self.store, null_id)
        self.assertAlmostEqual(value["probabilities"][0], probabilities[0], delta=1e-8)
        self.assertAlmostEqual(value["log_likelihood"], likelihood, delta=1e-8)


class TestNullValidation(MemoryCase):
    def uv_fit(self):
        return self.analyze(UV_ROWS, ["u", "v"])[1]

    def test_contradiction_atomic(self):
        fit_id = self.uv_fit()
        before = (self.count("records"), self.count("receipts"))
        with self.assertRaises(ValueError):
            fit_null(self.store, "bad", fit_id, [{"coefficients": {"u": 1}, "rhs": 0},
                                                 {"coefficients": {"u": 1}, "rhs": 1}])
        self.assertEqual((self.count("records"), self.count("receipts")), before)
        self.assertIsNone(self.store.get_receipt("null_fit", "bad"))
        with self.assertRaises(ResultNotFound):
            read_result(self.store, "null-" + "0" * 64)

    def test_zero_row_contradiction(self):
        fit_id = self.uv_fit()
        with self.assertRaises(ValueError):
            fit_null(self.store, "bad-zero-row", fit_id, [{"coefficients": {}, "rhs": 1}])
        self.assertIsNone(self.store.get_receipt("null_fit", "bad-zero-row"))
        null_id = fit_null(self.store, "ok-zero-row", fit_id, [{"coefficients": {}, "rhs": 0}])
        self.assertEqual(read_result(self.store, null_id)["probabilities"], [1, 0.5, 0.5])

    def test_invalid_equations(self):
        fit_id = self.uv_fit()
        before = (self.count("records"), self.count("receipts"))
        invalid = [
            [{"coefficients": {"missing": 0}, "rhs": 0}],
            [{"coefficients": {"u": 0.5}, "rhs": 0}],
            [{"coefficients": {"u": True}, "rhs": 0}],
            [{"coefficients": {"u": False}, "rhs": 0}],
            [{"coefficients": {"u": "9/1"}, "rhs": 0}],
            [{"coefficients": {"u": "1/9"}, "rhs": 0}],
            [{"coefficients": {"u": 1}, "rhs": "1/16"}],
            [{"coefficients": {"u": 1}, "rhs": -9}],
            [{"coefficients": {"u": 1}}],
            [{"coefficients": {"u": 1}, "rhs": 0, "extra": 1}],
            ["not-a-dict"],
            [{"coefficients": ["u"], "rhs": 0}],
            [{"coefficients": {"u": [1, 2, 3]}, "rhs": 0}],
        ]
        for index, equations in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                fit_null(self.store, "bad-" + str(index), fit_id, equations)
        with self.assertRaises(ZeroDivisionError):
            fit_null(self.store, "bad-denominator", fit_id,
                     [{"coefficients": {"u": [1, 0]}, "rhs": 0}])
        with self.assertRaises(ZeroDivisionError):
            fit_null(self.store, "bad-denominator-2", fit_id,
                     [{"coefficients": {"u": 1}, "rhs": [1, 0]}])
        with self.assertRaises(ValueError):
            fit_null(self.store, "bad-tuple", fit_id, ({"coefficients": {"u": 1}, "rhs": 0},))
        with self.assertRaises(ValueError):
            fit_null(self.store, "bad-many", fit_id, [{"coefficients": {"u": 1}, "rhs": 0}] * 5)
        self.assertEqual((self.count("records"), self.count("receipts")), before)

    def test_reference_kinds(self):
        fit_id = self.uv_fit()
        report_id = report(self.store, "effects", fit_id, [effect("v", v=1)])
        with self.assertRaises(ArchiveFormatError):
            fit_null(self.store, "wrong-kind", report_id, [])
        with self.assertRaises(ResultNotFound):
            fit_null(self.store, "missing", "fit-missing", [])
        null_id = fit_null(self.store, "null", fit_id, [])
        with self.assertRaises(ArchiveFormatError):
            fit_null(self.store, "null-as-fit", null_id, [])
        with self.assertRaises(ArchiveFormatError):
            compare_null(self.store, "wrong", fit_id)
        with self.assertRaises(ArchiveFormatError):
            compare_null(self.store, "wrong-2", report_id)
        with self.assertRaises(ResultNotFound):
            compare_null(self.store, "wrong-3", "null-missing")
        with self.assertRaises(ResultNotFound):
            compare_null(self.store, "wrong-4", null_id + "-suffix")

    def test_fully_constrained(self):
        fit_id = self.uv_fit()
        null_id = fit_null(self.store, "full", fit_id,
                           [{"coefficients": {"u": 1}, "rhs": 0},
                            {"coefficients": {"v": 1}, "rhs": 0}])
        value = read_result(self.store, null_id)
        self.assertEqual(value["probabilities"], [0.5, 0.5, 0.5])
        self.assertEqual(value["boundary"], [None, None, None])
        self.assertAlmostEqual(value["log_likelihood"], -5 * math.log(2), delta=1e-8)
        comparison = read_result(self.store, compare_null(self.store, "full-cmp", null_id))
        self.assertAlmostEqual(comparison["statistic"], 2 * math.log(2), delta=1e-8)

    def test_compatible_redundancy(self):
        fit_id = self.uv_fit()
        redundant = fit_null(self.store, "redundant", fit_id,
                             [{"coefficients": {"u": 1}, "rhs": 0},
                              {"coefficients": {"u": 2}, "rhs": 0},
                              {"coefficients": {"u": "1/2"}, "rhs": 0}])
        value = read_result(self.store, redundant)
        self.assertEqual(len(value["equations"]), 3)
        self.assertEqual(value["probabilities"], [0.5, 0.5, 0.5])
        single = fit_null(self.store, "single", fit_id, [{"coefficients": {"u": 1}, "rhs": 0}])
        self.assertEqual(value["probabilities"], read_result(self.store, single)["probabilities"])
        self.assertEqual(value["log_likelihood"], read_result(self.store, single)["log_likelihood"])

    def test_rank_deficient_design(self):
        _, fit_id = self.analyze([observation("a", {"u": 1, "v": 1}, 4, 2)], ["u", "v"])
        null_id = fit_null(self.store, "rank-def", fit_id,
                           [{"coefficients": {"u": 1, "v": 1}, "rhs": 0}])
        value = read_result(self.store, null_id)
        self.assertEqual(value["probabilities"], [0.5])
        comparison = read_result(self.store, compare_null(self.store, "rank-def-cmp", null_id))
        self.assertEqual(comparison["statistic"], 0)

    def test_zero_design(self):
        receipt = apply_cohort(self.store, "z", "input", [observation("a", {"u": 1}, 4, 2)])
        register_design(self.store, "z", ["c"], [ColumnDefinition("c", constant=0)])
        fit_id = fit(self.store, "z", ("z", receipt.revision_id), "z")
        null_id = fit_null(self.store, "z-null", fit_id, [{"coefficients": {"c": 1}, "rhs": 3}])
        value = read_result(self.store, null_id)
        self.assertEqual(value["probabilities"], [0.5])
        self.assertEqual(value["boundary"], [None])
        self.assertAlmostEqual(value["log_likelihood"], -4 * math.log(2), delta=1e-8)
        comparison = read_result(self.store, compare_null(self.store, "z-cmp", null_id))
        self.assertEqual(comparison["statistic"], 0)

    def test_empty_equations_match_original(self):
        fit_id = self.uv_fit()
        original = read_result(self.store, fit_id)
        null_id = fit_null(self.store, "empty", fit_id, [])
        value = read_result(self.store, null_id)
        self.assertEqual(value["probabilities"], original["probabilities"])
        self.assertEqual(value["boundary"], original["boundary"])
        self.assertEqual(value["internal_row_ids"], original["internal_row_ids"])
        self.assertAlmostEqual(value["log_likelihood"],
                               original["diagnostics"]["log_likelihood"], delta=1e-8)
        comparison = read_result(self.store, compare_null(self.store, "empty-cmp", null_id))
        self.assertAlmostEqual(comparison["statistic"], 0, delta=1e-8)

    def test_equivalent_rational_encoding_replays(self):
        fit_id = self.uv_fit()
        first = fit_null(self.store, "same", fit_id, [{"coefficients": {"u": "2/4"}, "rhs": "0/1"}])
        second = fit_null(self.store, "same", fit_id, [{"coefficients": {"u": [1, 2]}, "rhs": 0}])
        self.assertEqual(first, second)
        with self.assertRaises(RequestConflict):
            fit_null(self.store, "same", fit_id, [{"coefficients": {"u": "1/3"}, "rhs": 0}])

    def test_scopes_independent(self):
        receipt, fit_id = self.analyze(UV_ROWS, ["u", "v"])
        null_id = fit_null(self.store, "shared", fit_id, [])
        comparison_id = compare_null(self.store, "shared", null_id)
        other_fit = fit(self.store, "shared", ("study", receipt.revision_id), "design")
        report_id = report(self.store, "shared", fit_id, [])
        self.assertNotEqual(other_fit, fit_id)
        self.assertEqual(read_result(self.store, null_id)["kind"], "null_fit")
        self.assertEqual(read_result(self.store, comparison_id)["kind"], "null_comparison")
        self.assertEqual(read_result(self.store, other_fit)["kind"], "fit")
        self.assertEqual(read_result(self.store, report_id)["kind"], "report")


class TestNullRequests(MemoryCase):
    def test_replay_and_conflict(self):
        _, fit_id = self.analyze(UV_ROWS, ["u", "v"])
        equations = [{"coefficients": {"u": 1}, "rhs": 0}]
        null_id = fit_null(self.store, "replay", fit_id, equations)
        before = (self.count("records"), self.count("receipts"))
        self.assertEqual(fit_null(self.store, "replay", fit_id,
                                  [{"coefficients": {"u": "2/2"}, "rhs": 0}]), null_id)
        self.assertEqual((self.count("records"), self.count("receipts")), before)
        with self.assertRaises(RequestConflict):
            fit_null(self.store, "replay", fit_id, [{"coefficients": {"u": 1}, "rhs": 1}])
        with self.assertRaises(RequestConflict):
            fit_null(self.store, "replay", fit_id,
                     [{"coefficients": {"u": 1}, "rhs": 0},
                      {"coefficients": {"u": 1}, "rhs": 0}])
        comparison_id = compare_null(self.store, "replay-cmp", null_id)
        other_null = fit_null(self.store, "other", fit_id, [])
        before = (self.count("records"), self.count("receipts"))
        self.assertEqual(compare_null(self.store, "replay-cmp", null_id), comparison_id)
        with self.assertRaises(RequestConflict):
            compare_null(self.store, "replay-cmp", other_null)
        self.assertEqual((self.count("records"), self.count("receipts")), before)

    def test_input_and_return_isolation(self):
        _, fit_id = self.analyze(UV_ROWS, ["u", "v"])
        equations = [{"coefficients": {"u": 1}, "rhs": 0}]
        null_id = fit_null(self.store, "iso", fit_id, equations)
        equations[0]["coefficients"]["u"] = 8
        equations[0]["rhs"] = 3
        expected = read_result(self.store, null_id)
        forged = read_result(self.store, null_id)
        forged["probabilities"][0] = 0
        forged["boundary"][0] = 1
        forged["equations"][0]["rhs"] = Fraction(9)
        forged["log_likelihood"] = 0
        forged["frozen"]["row_ids"][0] = "forged"
        self.assertEqual(read_result(self.store, null_id), expected)
        comparison_id = compare_null(self.store, "iso-cmp", null_id)
        expected_comparison = read_result(self.store, comparison_id)
        forged_comparison = read_result(self.store, comparison_id)
        forged_comparison["statistic"] = 99
        forged_comparison["null_log_likelihood"] = 0
        self.assertEqual(read_result(self.store, comparison_id), expected_comparison)
        replayed = fit_null(self.store, "iso", fit_id, [{"coefficients": {"u": 1}, "rhs": 0}])
        self.assertEqual(replayed, null_id)


class TestNullPersistence(unittest.TestCase):
    def build(self, store):
        receipt = apply_cohort(store, "study", "input", UV_ROWS)
        register_design(store, "design", ["u", "v"],
                        [ColumnDefinition("u", source="u"), ColumnDefinition("v", source="v")])
        return receipt, fit(store, "fit-input", ("study", receipt.revision_id), "design")

    def test_correction_reopen_and_late_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "null.sqlite"
            store = ArchiveStore(path)
            _, fit_id = self.build(store)
            null_id = fit_null(store, "null", fit_id, [{"coefficients": {"u": 1}, "rhs": 0}])
            comparison_id = compare_null(store, "cmp", null_id)
            before = (read_result(store, null_id), read_result(store, comparison_id))
            apply_cohort(store, "study", "correction",
                         [observation("a", {"u": 1, "v": 0}, 4, 2)])
            store.close()
            with ArchiveStore(path) as reopened:
                self.assertEqual((read_result(reopened, null_id),
                                  read_result(reopened, comparison_id)), before)
                fresh = compare_null(reopened, "cmp-after-correction", null_id)
                value = read_result(reopened, fresh)
                self.assertEqual(value["original_log_likelihood"],
                                 before[1]["original_log_likelihood"])
                self.assertEqual(value["null_log_likelihood"], before[1]["null_log_likelihood"])
                self.assertEqual(value["statistic"], before[1]["statistic"])
                self.assertEqual(read_result(reopened, null_id)["frozen"]["revision_id"],
                                 before[0]["frozen"]["revision_id"])

    def test_null_publish_failure_windows(self):
        equations = [{"coefficients": {"v": 1}, "rhs": 0}]
        for failure in (1, 2, "commit"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "null.sqlite"
                store = ArchiveStore(path)
                _, fit_id = self.build(store)
                old_null = fit_null(store, "old-null", fit_id,
                                    [{"coefficients": {"u": 1}, "rhs": 0}])
                old = read_result(store, old_null)
                before = store.connection.execute("SELECT count(*) FROM records").fetchone()[0]
                request = validate_null_request(fit_id, load_fit(store, fit_id).frozen.column_ids,
                                                equations)
                fingerprint = null_request_fingerprint(request)
                candidate_id = "null-" + content_digest(
                    {"request_id": "retry", "fingerprint": fingerprint})
                if failure == "commit":
                    store.arm_failure(before_commit=True)
                else:
                    store.arm_failure(write_number=failure)
                with self.assertRaises(sqlite3.OperationalError):
                    fit_null(store, "retry", fit_id, equations)
                with self.assertRaises(ResultNotFound):
                    read_result(store, candidate_id)
                self.assertIsNone(store.get_receipt("null_fit", "retry"))
                self.assertEqual(
                    store.connection.execute("SELECT count(*) FROM records").fetchone()[0], before)
                self.assertEqual(read_result(store, old_null), old)
                store.close()
                with ArchiveStore(path) as reopened:
                    with self.assertRaises(ResultNotFound):
                        read_result(reopened, candidate_id)
                    self.assertIsNone(reopened.get_receipt("null_fit", "retry"))
                    new_null = fit_null(reopened, "retry", fit_id, equations)
                    self.assertEqual(new_null, candidate_id)
                    self.assertEqual(fit_null(reopened, "retry", fit_id, equations), new_null)
                    self.assertEqual(read_result(reopened, old_null), old)

    def test_comparison_publish_failure_windows(self):
        for failure in (1, 2, "commit"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "cmp.sqlite"
                store = ArchiveStore(path)
                _, fit_id = self.build(store)
                null_id = fit_null(store, "null", fit_id, [{"coefficients": {"u": 1}, "rhs": 0}])
                old_comparison = compare_null(store, "old-cmp", null_id)
                old = read_result(store, old_comparison)
                before = store.connection.execute("SELECT count(*) FROM records").fetchone()[0]
                fingerprint = comparison_request_fingerprint(null_id)
                candidate_id = "comparison-" + content_digest(
                    {"request_id": "retry", "fingerprint": fingerprint})
                if failure == "commit":
                    store.arm_failure(before_commit=True)
                else:
                    store.arm_failure(write_number=failure)
                with self.assertRaises(sqlite3.OperationalError):
                    compare_null(store, "retry", null_id)
                with self.assertRaises(ResultNotFound):
                    read_result(store, candidate_id)
                self.assertIsNone(store.get_receipt("null_comparison", "retry"))
                self.assertEqual(
                    store.connection.execute("SELECT count(*) FROM records").fetchone()[0], before)
                self.assertEqual(read_result(store, old_comparison), old)
                store.close()
                with ArchiveStore(path) as reopened:
                    with self.assertRaises(ResultNotFound):
                        read_result(reopened, candidate_id)
                    self.assertIsNone(reopened.get_receipt("null_comparison", "retry"))
                    new_comparison = compare_null(reopened, "retry", null_id)
                    self.assertEqual(new_comparison, candidate_id)
                    self.assertEqual(compare_null(reopened, "retry", null_id), new_comparison)
                    retried = read_result(reopened, new_comparison)
                    for key in ("fit_id", "null_id", "original_log_likelihood",
                                "null_log_likelihood", "statistic"):
                        self.assertEqual(retried[key], old[key])
                    self.assertEqual(read_result(reopened, old_comparison), old)

    def test_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupt.sqlite"
            store = ArchiveStore(path)
            _, fit_id = self.build(store)
            null_id = fit_null(store, "null", fit_id, [{"coefficients": {"u": 1}, "rhs": 0}])
            comparison_id = compare_null(store, "cmp", null_id)

            def forge(record_id, kind, mutate):
                payload = store.get_record(record_id, kind)
                mutate(payload)
                envelope = {"version": 1, "id": record_id, "kind": kind,
                            "payload": payload, "digest": content_digest(payload)}
                store.connection.execute("UPDATE records SET body=? WHERE id=?",
                                         (encode_value(envelope), record_id))

            forge(null_id, "null_fit",
                  lambda p: p["artifact"].update({"boundary": [1, None, None]}))
            with self.assertRaises(ArchiveFormatError):
                read_result(store, null_id)
            store.close()
            with ArchiveStore(path) as reopened:
                with self.assertRaises(ArchiveFormatError):
                    read_result(reopened, null_id)
                # A comparison consuming the corrupted null is rejected as well.
                with self.assertRaises(ArchiveFormatError):
                    read_result(reopened, comparison_id)
            store = ArchiveStore(path)
            forge(null_id, "null_fit",
                  lambda p: p["artifact"].update({"log_likelihood": -1.0}))
            with self.assertRaises(ArchiveFormatError):
                read_result(store, null_id)
            forge(comparison_id, "null_comparison",
                  lambda p: p["comparison"].update({"statistic": 0.5}))
            with self.assertRaises(ArchiveFormatError):
                read_result(store, comparison_id)
            forge(comparison_id, "null_comparison",
                  lambda p: p["comparison"].update({"fit_id": "fit-other"}))
            with self.assertRaises(ArchiveFormatError):
                read_result(store, comparison_id)
            store.close()


class TestNullEdgeCases(MemoryCase):
    def test_extreme_offset_stable_likelihood(self):
        # rhs 8 with coefficient 1/8 pins beta_x = 64; with x = 8 the offset is
        # 512, an extreme but finite prediction that must stay auditable.
        receipt = apply_cohort(self.store, "ex", "input",
                               [observation("a", {"x": 8}, 4, 2)])
        register_design(self.store, "ex", ["x"], [ColumnDefinition("x", source="x")])
        fit_id = fit(self.store, "ex", ("ex", receipt.revision_id), "ex")
        null_id = fit_null(self.store, "ex-null", fit_id,
                           [{"coefficients": {"x": [1, 8]}, "rhs": 8}])
        value = read_result(self.store, null_id)
        self.assertEqual(value["boundary"], [None])
        self.assertEqual(value["probabilities"], [1.0])
        log_p = -math.log1p(math.exp(-512))
        log_one_minus_p = -(512 + math.log1p(math.exp(-512)))
        expected = 2 * log_p + 2 * log_one_minus_p
        self.assertAlmostEqual(value["log_likelihood"], expected, delta=1e-8)
        comparison = read_result(self.store, compare_null(self.store, "ex-cmp", null_id))
        original = read_result(self.store, fit_id)["diagnostics"]["log_likelihood"]
        self.assertAlmostEqual(comparison["null_log_likelihood"], expected, delta=1e-8)
        self.assertAlmostEqual(comparison["statistic"], 2 * (original - expected), delta=1e-8)

    def test_offset_with_free_direction(self):
        # beta_v = 1 pins an offset while beta_u stays free: the solver must
        # travel to eta = 0 on the coupled row rather than truncate.
        _, fit_id = self.analyze([observation("a", {"u": 1, "v": 1}, 4, 2),
                                  observation("b", {"u": 0, "v": 1}, 2, 1)], ["u", "v"])
        null_id = fit_null(self.store, "offset-free", fit_id,
                           [{"coefficients": {"v": 1}, "rhs": 1}])
        value = read_result(self.store, null_id)
        probabilities, likelihood = decimal_offset_reference([1, 0], [1, 1], [4, 2], [2, 1])
        for actual, expected in zip(value["probabilities"], probabilities):
            self.assertAlmostEqual(actual, expected, delta=1e-8)
        self.assertAlmostEqual(value["log_likelihood"], likelihood, delta=1e-8)

    def test_still_separated_after_constraint(self):
        _, fit_id = self.analyze(UV_ROWS, ["u", "v"])
        null_id = fit_null(self.store, "sep", fit_id, [{"coefficients": {"v": 1}, "rhs": 1}])
        value = read_result(self.store, null_id)
        self.assertEqual(value["boundary"], [1, None, None])
        self.assertEqual(value["probabilities"][0], 1)
        sigmoid_one = 1 / (1 + math.exp(-1))
        self.assertAlmostEqual(value["probabilities"][1], sigmoid_one, delta=1e-8)
        self.assertAlmostEqual(value["probabilities"][2], 1 - sigmoid_one, delta=1e-8)

    def test_constraint_keeps_and_blocks_separation(self):
        rows = [observation("a", {"u": 1, "v": 0}, 2, 0),
                observation("b", {"u": 0, "v": 1}, 2, 2)]
        _, fit_id = self.analyze(rows, ["u", "v"])
        # The separating direction (t, -t) lies in the null space of u+v=0.
        kept = fit_null(self.store, "kept", fit_id, [{"coefficients": {"u": 1, "v": 1}, "rhs": 0}])
        value = read_result(self.store, kept)
        self.assertEqual(value["probabilities"], [0, 1])
        self.assertEqual(value["boundary"], [0, 1])
        self.assertEqual(value["diagnostics"]["status"], "complete")
        self.assertEqual(value["log_likelihood"], 0)
        comparison = read_result(self.store, compare_null(self.store, "kept-cmp", kept))
        self.assertEqual(comparison["statistic"], 0)
        # The constraint u-v=0 blocks the separating direction entirely.
        blocked = fit_null(self.store, "blocked", fit_id,
                           [{"coefficients": {"u": 1, "v": -1}, "rhs": 0}])
        blocked_value = read_result(self.store, blocked)
        self.assertEqual(blocked_value["probabilities"], [0.5, 0.5])
        self.assertEqual(blocked_value["boundary"], [None, None])
        blocked_comparison = read_result(
            self.store, compare_null(self.store, "blocked-cmp", blocked))
        self.assertAlmostEqual(blocked_comparison["statistic"], 8 * math.log(2), delta=1e-8)

    def test_large_offset_with_free_direction(self):
        # v/8 = 8 pins beta_v = 64; the row (8, 8) then carries offset 512 and
        # the free beta_u must travel to theta = -64.  The homotopy keeps the
        # solve stable through the saturated region.
        receipt = apply_cohort(self.store, "hom", "input",
                               [observation("a", {"u": 8, "v": 8}, 4, 2)])
        register_design(self.store, "hom", ["u", "v"],
                        [ColumnDefinition("u", source="u"), ColumnDefinition("v", source="v")])
        fit_id = fit(self.store, "hom", ("hom", receipt.revision_id), "hom")
        null_id = fit_null(self.store, "hom-null", fit_id,
                           [{"coefficients": {"v": [1, 8]}, "rhs": 8}])
        value = read_result(self.store, null_id)
        self.assertEqual(value["boundary"], [None])
        self.assertAlmostEqual(value["probabilities"][0], 0.5, delta=1e-8)
        self.assertAlmostEqual(value["log_likelihood"], -4 * math.log(2), delta=1e-8)

    def test_four_equation_limit(self):
        _, fit_id = self.analyze(UV_ROWS, ["u", "v"])
        equations = [{"coefficients": {"u": 1}, "rhs": 0},
                     {"coefficients": {"v": 1}, "rhs": 0},
                     {"coefficients": {"u": 1, "v": 1}, "rhs": 0},
                     {"coefficients": {"u": 2, "v": "1/2"}, "rhs": 0}]
        null_id = fit_null(self.store, "four", fit_id, equations)
        value = read_result(self.store, null_id)
        self.assertEqual(len(value["equations"]), 4)
        self.assertEqual(value["probabilities"], [0.5, 0.5, 0.5])
