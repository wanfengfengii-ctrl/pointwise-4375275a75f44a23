import math
from binomial.archive.schema import RequestConflict, ResultNotFound
from binomial.archive.fit_records import read_result, load_fit
from binomial.cohort.batches import apply_cohort
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design, load_design
from binomial.fitting.service import fit
from binomial.fitting.finite import NumericalFitError
from tests.support import MemoryCase, observation, effect


class TestFiniteFit(MemoryCase):
    def test_intercept_only(self):
        _, fit_id = self.analyze([observation("r", {"a": 1}, 4, 2)], ["a"])
        self.assertEqual(read_result(self.store, fit_id)["probabilities"], [0.5])
        item = self.results(fit_id, [effect("mean", a=1)])[0]
        self.assertAlmostEqual(item["estimate"], 0, delta=1e-8)
        self.assertAlmostEqual(item["variance"], 1, delta=1e-8)

    def test_finite_weighted(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 4, 1),
                                  observation("b", {"x": 1}, 4, 3)], ["x"])
        artifact = load_fit(self.store, fit_id)
        self.assertEqual(artifact.probabilities, (0.5, 0.5))
        self.assertEqual(artifact.information, ((2.0,),))
        self.assertAlmostEqual(self.results(fit_id, [effect("x", x=1)])[0]["variance"], 0.5, delta=1e-8)

    def test_design_identity(self):
        rows = [observation("r_b", {"b": 1, "a": 0}, 4, 3),
                observation("r_a", {"b": 0, "a": 1}, 4, 1)]
        receipt, first = self.analyze(rows, ["a", "b"])
        register_design(self.store, "reversed", ["b", "a"],
                        [ColumnDefinition("a", source="a"), ColumnDefinition("b", source="b")])
        second = fit(self.store, "second", ("study", receipt.revision_id), "reversed")
        for fit_id, columns, matrix in [(first, ["a", "b"], [[1, 0], [0, 1]]),
                                        (second, ["b", "a"], [[0, 1], [1, 0]])]:
            value = read_result(self.store, fit_id)
            self.assertEqual(value["frozen"]["row_ids"], ["r_a", "r_b"])
            self.assertEqual(value["frozen"]["column_ids"], columns)
            self.assertEqual(value["frozen"]["x"], matrix)
            for actual, expected in zip(value["probabilities"], [0.25, 0.75]):
                self.assertAlmostEqual(actual, expected, delta=1e-8)

    def test_design_rejection(self):
        rules = [ColumnDefinition("a", source="a")]
        for ids, definitions in [(["unknown"], rules), (["a", "a"], rules),
                                  (["a"], [ColumnDefinition("a", constant=9)]),
                                  (["a"], [ColumnDefinition("a", constant=True)])]:
            with self.assertRaises(ValueError):
                register_design(self.store, "bad", ids, definitions)
            with self.assertRaises(ResultNotFound):
                load_design(self.store, "bad")
        receipt = apply_cohort(self.store, "study", "rows", [observation("r", {"b": 1}, 4, 2)])
        register_design(self.store, "d", ["a"], rules)
        before = self.count("records")
        with self.assertRaises(ValueError):
            fit(self.store, "missing", ("study", receipt.revision_id), "d")
        self.assertEqual(self.count("records"), before)
        with self.assertRaises(RequestConflict):
            register_design(self.store, "d", ["a"], [ColumnDefinition("a", constant=1)])

    def test_request_replay(self):
        receipt, fit_id = self.analyze([observation("r", {"a": 1}, 4, 2)], ["a"])
        before = self.count("records")
        self.assertEqual(fit(self.store, "fit-input", ("study", receipt.revision_id), "design"), fit_id)
        self.assertEqual(self.count("records"), before)
        newer = apply_cohort(self.store, "study", "correction", [observation("r", {"a": 1}, 4, 3)])
        with self.assertRaises(RequestConflict):
            fit(self.store, "fit-input", ("study", newer.revision_id), "design")

    def test_numeric_failure(self):
        receipt = apply_cohort(self.store, "study", "rows", [observation("r", {"a": 1}, 4, 3)])
        register_design(self.store, "d", ["a"], [ColumnDefinition("a", source="a")])
        before = self.count("records")
        def unavailable_solver(*args):
            raise NumericalFitError("solver budget exhausted")
        with self.assertRaises(NumericalFitError):
            fit(self.store, "try", ("study", receipt.revision_id), "d", finite_solver=unavailable_solver)
        self.assertIsNone(self.store.get_receipt("fit", "try"))
        self.assertEqual(self.count("records"), before)
        fit_id = fit(self.store, "try", ("study", receipt.revision_id), "d")
        self.assertAlmostEqual(load_fit(self.store, fit_id).theta[0], math.log(3), delta=1e-8)
