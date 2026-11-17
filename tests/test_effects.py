from fractions import Fraction
from binomial.archive.schema import RequestConflict
from binomial.archive.fit_records import load_fit
from binomial.design.contrasts import transport_contrast
from binomial.reporting.service import report
from tests.support import MemoryCase, observation, effect


class TestEffectCoordinates(MemoryCase):
    def test_rank_and_column_transport(self):
        _, original = self.analyze([observation("a", {"u": 1, "v": 1}, 4, 2)], ["u", "v"])
        items = self.results(original, [effect("half", u="1/2", v=[1, 2]), effect("u", u=1)])
        self.assertEqual(items[0]["estimate"], 0)
        self.assertAlmostEqual(items[0]["variance"], 0.25, delta=1e-8)
        self.assertEqual(items[1]["status"], "not_estimable")
        t = ((1, 2), (0, 1))
        coefficients = transport_contrast((Fraction(1, 2), Fraction(1, 2)), t)
        self.assertEqual(coefficients, (Fraction(1, 2), Fraction(3, 2)))
        _, transformed = self.analyze([observation("a", {"s": 1, "t": 3}, 4, 2)],
                                      ["s", "t"], cohort="changed", design="changed", request="changed")
        result = self.results(transformed, [effect("half", s=coefficients[0], t=coefficients[1]),
                                            effect("u", s=1, t=2)], request="changed")
        self.assertEqual([i["status"] for i in result], ["estimable", "not_estimable"])
        self.assertEqual(result[0]["estimate"], items[0]["estimate"])
        self.assertAlmostEqual(result[0]["variance"], items[0]["variance"], delta=1e-8)

    def test_boundary_column_transport(self):
        rows = [observation("a", {"u": 1, "v": 0}, 1, 1),
                observation("b", {"u": 0, "v": 1}, 2, 1),
                observation("c", {"u": 0, "v": -1}, 2, 1)]
        _, original = self.analyze(rows, ["u", "v"])
        _, changed = self.analyze([
            observation("a", {"s": 1, "t": 2}, 1, 1),
            observation("b", {"s": 0, "t": 1}, 2, 1),
            observation("c", {"s": 0, "t": -1}, 2, 1)],
            ["s", "t"], cohort="mixed", design="mixed", request="mixed")
        self.assertEqual(load_fit(self.store, original).probabilities,
                         load_fit(self.store, changed).probabilities)
        one = self.results(original, [effect("u", u=1), effect("v", v=1)])
        two = self.results(changed, [effect("u", s=1, t=2), effect("v", t=1)], request="mixed")
        self.assertEqual([(i["status"], i["estimate"], i["variance"]) for i in one],
                         [(i["status"], i["estimate"], i["variance"]) for i in two])

    def test_variance_weights(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 4, 1),
                                  observation("b", {"x": 1}, 4, 3)], ["x"])
        one, half, zero = self.results(fit_id, [effect("one", x=1), effect("half", x="1/2"), effect("zero")])
        self.assertEqual(one["variance"], 0.5)
        self.assertEqual(half["variance"], 0.125)
        self.assertEqual((zero["estimate"], zero["variance"]), (0, 0))

    def test_equivalent_rational_replay(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 4, 2)], ["x"])
        first = report(self.store, "same", fit_id, [effect("half", x=[1, 2])])
        self.assertEqual(first, report(self.store, "same", fit_id, [effect("half", x="2/4")]))
        with self.assertRaises(RequestConflict):
            report(self.store, "same", fit_id, [effect("renamed", x="1/2")])


class TestEffectRequests(MemoryCase):
    def test_unknown_column(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 4, 2)], ["x"])
        before = (self.count("records"), self.count("receipts"))
        with self.assertRaises(ValueError):
            report(self.store, "bad", fit_id, [effect("ok", x=1), effect("bad", missing=1), effect("zero")])
        self.assertEqual((self.count("records"), self.count("receipts")), before)
        self.assertIsNone(self.store.get_receipt("report", "bad"))

    def test_atomic_validation(self):
        _, fit_id = self.analyze([observation("a", {"x": 1}, 4, 2)], ["x"])
        before = (self.count("records"), self.count("receipts"))
        for effects in [[effect("zero_denominator", x=[1, 0])],
                        [effect("duplicate", x=1), effect("duplicate")],
                        [effect("approximation", x=0.5)]]:
            with self.assertRaises((ValueError, ZeroDivisionError)):
                report(self.store, "bad", fit_id, effects)
            self.assertIsNone(self.store.get_receipt("report", "bad"))
            self.assertEqual((self.count("records"), self.count("receipts")), before)
