import math
from dataclasses import dataclass
from binomial.fitting.likelihood import binomial_log_likelihood, score_and_information


class NumericalFitError(ArithmeticError):
    pass


@dataclass(frozen=True)
class FiniteFit:
    theta: tuple
    probabilities: tuple
    information: tuple
    iterations: int
    score_norm: float


def solve_positive_system(matrix, rhs):
    d = len(rhs)
    if len(matrix) != d or any(len(r) != d for r in matrix):
        raise NumericalFitError("information dimension mismatch")
    lower = [[0.0] * d for _ in range(d)]
    diagonal = [0.0] * d
    for i in range(d):
        lower[i][i] = 1.0
        for j in range(i + 1):
            if not math.isfinite(matrix[i][j]) or abs(matrix[i][j] - matrix[j][i]) > 1e-10 * max(1, abs(matrix[i][j])):
                raise NumericalFitError("invalid symmetric information")
            value = matrix[i][j] - math.fsum(lower[i][l] * diagonal[l] * lower[j][l] for l in range(j))
            if i == j:
                if value <= 0 or not math.isfinite(value):
                    raise NumericalFitError("information is not positive definite")
                diagonal[i] = value
            else:
                lower[i][j] = value / diagonal[j]
    y = []
    for i in range(d):
        y.append(float(rhs[i]) - math.fsum(lower[i][j] * y[j] for j in range(i)))
    result = [0.0] * d
    for i in reversed(range(d)):
        result[i] = y[i] / diagonal[i] - math.fsum(lower[j][i] * result[j] for j in range(i + 1, d))
    if any(not math.isfinite(v) for v in result):
        raise NumericalFitError("nonfinite solution")
    return tuple(result)


def fit_finite(a, n, k, dimension, max_iterations=200):
    if any(len(row) != dimension for row in a) or len(a) != len(n) or len(a) != len(k):
        raise NumericalFitError("finite input dimension mismatch")
    theta = (0.0,) * dimension
    for iteration in range(max_iterations + 1):
        p, score, information = score_and_information(a, n, k, theta)
        step = solve_positive_system(information, score)
        norm = max(map(abs, score), default=0.0)
        if max(map(abs, step), default=0.0) <= 2e-12:
            if any(not 0 < v < 1 for v in p):
                raise NumericalFitError("finite solver reached boundary")
            return FiniteFit(theta, p, information, iteration, norm)
        old_ll = binomial_log_likelihood(n, k, p)
        scale = 1.0
        for _ in range(60):
            candidate = tuple(v + scale * s for v, s in zip(theta, step))
            new_p, _, _ = score_and_information(a, n, k, candidate)
            new_ll = binomial_log_likelihood(n, k, new_p)
            if new_ll >= old_ll - 2e-13 * max(1.0, abs(old_ll)):
                theta = candidate
                break
            scale *= 0.5
        else:
            raise NumericalFitError("likelihood line search failed")
    raise NumericalFitError("finite solve did not converge")
