from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
from binomial.archive.fit_records import load_fit
from binomial.fitting.subspace import solve_exact, row_space
from tests.support import MemoryCase, observation, effect


def decimal_reference(xs, ns, ks):
    with localcontext() as context:
        context.prec = 70
        low, high = Decimal(-100), Decimal(100)
        for _ in range(260):
            beta = (low + high) / 2
            probabilities = [1 / (1 + (-Decimal(x) * beta).exp()) for x in xs]
            score = sum(Decimal(x) * (k - n * p) for x, n, k, p in zip(xs, ns, ks, probabilities))
            if score > 0:
                low = beta
            else:
                high = beta
        beta = (low + high) / 2
        probabilities = [1 / (1 + (-Decimal(x) * beta).exp()) for x in xs]
        information = sum(Decimal(x * x * n) * p * (1 - p) for x, n, p in zip(xs, ns, probabilities))
        return float(beta), [float(p) for p in probabilities], float(1 / information)


class TestIndependentNumerics(MemoryCase):
    def test_decimal_unsaturated(self):
        xs, ns, ks = [-2, 1, 3], [5, 4, 6], [1, 2, 5]
        expected_beta, expected_p, expected_variance = decimal_reference(xs, ns, ks)
        _, fit_id = self.analyze([observation(str(i), {"x": x}, n, k)
                                  for i, (x, n, k) in enumerate(zip(xs, ns, ks))], ["x"])
        artifact = load_fit(self.store, fit_id)
        for actual, expected in zip(artifact.probabilities, expected_p):
            self.assertAlmostEqual(actual, expected, delta=1e-8)
        result = self.results(fit_id, [effect("slope", x=1)])[0]
        self.assertAlmostEqual(result["estimate"], expected_beta, delta=1e-8)
        self.assertAlmostEqual(result["variance"], expected_variance, delta=1e-8)

    def test_all_small_intercept_counts(self):
        for first, second in product(range(3), repeat=2):
            name = str(first) + str(second)
            _, fit_id = self.analyze([observation("a", {"x": 1}, 2, first),
                                      observation("b", {"x": 1}, 2, second)],
                                     ["x"], cohort=name, design=name, request=name)
            expected = (first + second) / 4
            for p in load_fit(self.store, fit_id).probabilities:
                self.assertAlmostEqual(p, expected, delta=1e-8)
            item = self.results(fit_id, [effect("x", x=1)], request=name)[0]
            if expected in (0, 1):
                self.assertEqual(item["status"], "not_estimable")
            else:
                self.assertAlmostEqual(item["variance"], 1 / (4 * expected * (1 - expected)), delta=1e-8)

    def test_exact_rank_zero_and_inconsistency(self):
        self.assertEqual(row_space([(0, 0)], 2).basis, ())
        self.assertIsNone(solve_exact([(1, 1), (2, 2)], [1, 3]))
        space = row_space([(1, 1), (2, 2)], 2)
        self.assertEqual(space.coordinates((Fraction(1, 2), Fraction(1, 2))), (Fraction(1, 2),))
        self.assertIsNone(space.coordinates((1, 0)))
