from fractions import Fraction
from binomial.archive.fit_records import load_fit, read_result
from binomial.reporting.service import report
from binomial.fitting.service import fit
from tests.support import MemoryCase, observation, effect


class TestBoundaryReport(MemoryCase):
    def quasi(self):
        return self.analyze([observation("a", {"u": 1, "v": 0}, 1, 1),
                             observation("b", {"u": 0, "v": 1}, 2, 1),
                             observation("c", {"u": 0, "v": -1}, 2, 1)], ["u", "v"])[1]

    def test_quasi_separation(self):
        fit_id = self.quasi()
        self.assertEqual(load_fit(self.store, fit_id).probabilities, (1, 0.5, 0.5))
        first, second = self.results(fit_id, [effect("u", u=1), effect("v", v=1)])
        self.assertEqual((first["status"], first["estimate"], first["variance"]),
                         ("not_estimable", None, None))
        self.assertEqual(second["status"], "estimable")
        self.assertAlmostEqual(second["estimate"], 0, delta=1e-8)
        self.assertAlmostEqual(second["variance"], 1, delta=1e-8)

    def test_face_certificate(self):
        artifact = load_fit(self.store, self.quasi())
        self.assertEqual(artifact.boundary, (1, None, None))
        self.assertEqual(artifact.internal_row_ids, ("b", "c"))
        self.assertEqual(artifact.basis, ((Fraction(0), Fraction(1)),))
        self.assertEqual(artifact.information, ((1.0,),))
        self.assertEqual(dict(artifact.diagnostics)["status"], "quasi")

    def test_request_order(self):
        fit_id = self.quasi()
        requests = [effect("second", v=1), effect("first", u=1), effect("zero"),
                    effect("second_again", v="2/2")]
        first_id = report(self.store, "ordered", fit_id, requests)
        self.assertEqual(report(self.store, "ordered", fit_id, requests), first_id)
        items = read_result(self.store, first_id)["items"]
        self.assertEqual([i["name"] for i in items], ["second", "first", "zero", "second_again"])
        self.assertEqual([i["ordinal"] for i in items], list(range(4)))
        self.assertEqual([i["status"] for i in items],
                         ["estimable", "not_estimable", "estimable", "estimable"])
        self.assertEqual([i["variance"] for i in items], [1.0, None, 0.0, 1.0])
        artifact = read_result(self.store, fit_id)
        empty = report(self.store, "empty", fit_id, [])
        self.assertEqual(read_result(self.store, empty)["items"], [])
        self.assertEqual(read_result(self.store, fit_id), artifact)

    def test_complete_separation(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 2, 2),
                                  observation("b", {"x": -1}, 3, 0)], ["x"])
        artifact = load_fit(self.store, fit_id)
        self.assertEqual(artifact.probabilities, (1, 0))
        self.assertEqual((artifact.basis, artifact.theta, artifact.information), ((), (), ()))
        self.assertEqual(dict(artifact.diagnostics)["status"], "complete")
        items = self.results(fit_id, [effect("x", x=1), effect("zero")])
        self.assertEqual(items[0]["status"], "not_estimable")
        self.assertEqual((items[1]["estimate"], items[1]["variance"]), (0, 0))

    def test_zero_space(self):
        _, fit_id = self.analyze([observation("a", {"x": 0}, 2, 2),
                                  observation("b", {"x": 0}, 3, 0)], ["x"])
        artifact = load_fit(self.store, fit_id)
        self.assertEqual(artifact.probabilities, (0.5, 0.5))
        self.assertEqual(artifact.boundary, (None, None))
        self.assertEqual(artifact.internal_row_ids, ("a", "b"))
        self.assertEqual(artifact.basis, ())

    def test_duplicate_boundary_rows(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 2, 2),
                                  observation("b", {"x": 1}, 2, 2),
                                  observation("c", {"x": -1}, 2, 0)], ["x"])
        self.assertEqual(load_fit(self.store, fit_id).probabilities, (1, 1, 0))

    def test_pure_rows_can_have_finite_solution(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 2, 2),
                                  observation("b", {"x": 1}, 2, 0)], ["x"])
        self.assertEqual(load_fit(self.store, fit_id).probabilities, (0.5, 0.5))
        self.assertEqual(self.results(fit_id, [effect("x", x=1)])[0]["variance"], 1.0)
