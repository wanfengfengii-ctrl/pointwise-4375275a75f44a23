import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from binomial.archive.schema import content_digest, identifier
from binomial.design.compiler import FrozenDesign, validate_frozen_design
from binomial.design.contrasts import rational
from binomial.fitting.boundary import BoundaryFace
from binomial.fitting.finite import NumericalFitError, solve_positive_system
from binomial.fitting.likelihood import expit
from binomial.fitting.subspace import ExactRowSpace, independent_constraints, row_space, solve_exact

# Equation coefficients and right hand sides keep numerator and denominator
# within this bound after reduction, mirroring the frozen coordinate range.
RATIONAL_BOUND = 8


def bounded_rational(value):
    result = rational(value)
    if abs(result.numerator) > RATIONAL_BOUND or result.denominator > RATIONAL_BOUND:
        raise ValueError("rational magnitude outside the equation bound")
    return result


@dataclass(frozen=True)
class NullEquation:
    coefficients: tuple
    rhs: Fraction

    def to_value(self, column_ids):
        return {"coefficients": {c: v for c, v in zip(column_ids, self.coefficients) if v},
                "rhs": self.rhs}


def parse_equations(equations, column_ids):
    if not isinstance(equations, list) or len(equations) > 4:
        raise ValueError("equations must be a list of at most four items")
    result = []
    for item in equations:
        if not isinstance(item, dict) or set(item) != {"coefficients", "rhs"}:
            raise ValueError("equation fields")
        coefficients = item["coefficients"]
        if not isinstance(coefficients, Mapping):
            raise ValueError("coefficients must be a named mapping")
        if any(c not in column_ids for c in coefficients):
            raise ValueError("unknown equation column")
        parsed = tuple(bounded_rational(coefficients.get(c, 0)) for c in column_ids)
        result.append(NullEquation(parsed, bounded_rational(item["rhs"])))
    return tuple(result)


@dataclass(frozen=True)
class NullRequest:
    fit_id: str
    column_ids: tuple
    equations: tuple

    def to_value(self):
        return {"fit_id": self.fit_id,
                "equations": [eq.to_value(self.column_ids) for eq in self.equations]}


def validate_null_request(fit_id, column_ids, equations):
    identifier(fit_id)
    columns = tuple(column_ids)
    return NullRequest(fit_id, columns, parse_equations(equations, columns))


def null_request_fingerprint(request):
    return content_digest(request.to_value())


def independent_columns(rows, width):
    pivots = []
    for j in range(width):
        column = tuple(row[j] for row in rows)
        matrix = [tuple(row[i] for i in pivots) for row in rows]
        if solve_exact(matrix, column, len(pivots)) is None:
            pivots.append(j)
    return pivots


def affine_parametrization(equations, width):
    """Exact particular solution and null basis for A beta = b in original coordinates."""
    matrix = [eq.coefficients for eq in equations]
    rhs = [eq.rhs for eq in equations]
    if not matrix:
        identity = tuple(tuple(Fraction(1 if i == j else 0) for i in range(width))
                         for j in range(width))
        return (Fraction(),) * width, identity
    kept, values = independent_constraints(matrix, rhs)
    pivots = independent_columns(kept, width)
    if len(pivots) != len(kept):
        raise ValueError("constraint pivot mismatch")
    square = [tuple(row[i] for i in pivots) for row in kept]
    particular = solve_exact(square, values, len(pivots))
    if particular is None:
        raise ValueError("inconsistent constraints")
    beta0 = [Fraction()] * width
    for i, j in enumerate(pivots):
        beta0[j] = particular[i]
    basis = []
    for j in range(width):
        if j in pivots:
            continue
        column = tuple(-row[j] for row in kept)
        solution = solve_exact(square, column, len(pivots))
        direction = [Fraction()] * width
        for i, p in enumerate(pivots):
            direction[p] = solution[i]
        direction[j] = Fraction(1)
        basis.append(tuple(direction))
    return tuple(beta0), tuple(basis)


def identify_moment_face(x, n, k):
    """Moment-constraint face identification on an arbitrary exact design."""
    m = len(x)
    width = len(x[0]) if m else 0
    constraints = tuple(tuple(row[j] for row in x) for j in range(width))
    rhs = tuple(sum((row[i] * k[i] for i in range(m)), Fraction()) for row in constraints)
    equations, target = independent_constraints(constraints, rhs)
    rank = len(equations)
    if rank == 0:
        return BoundaryFace((None,) * m, tuple(range(m)), 0)
    variable = {i for i in range(m) if 0 < k[i] < n[i]}
    examined = 0
    for basic in itertools.combinations(range(m), rank):
        matrix = tuple(tuple(row[i] for i in basic) for row in equations)
        inverse_columns = [solve_exact(matrix, tuple(int(i == j) for i in range(rank)), rank)
                           for j in range(rank)]
        if any(col is None for col in inverse_columns):
            continue
        others = tuple(i for i in range(m) if i not in basic)
        for bits in itertools.product((0, 1), repeat=len(others)):
            q = [Fraction() for _ in range(m)]
            for i, bit in zip(others, bits):
                q[i] = Fraction(bit * n[i])
            b = tuple(target[j] - sum((equations[j][i] * q[i] for i in others), Fraction())
                      for j in range(rank))
            solution = tuple(sum((inverse_columns[j][i] * b[j] for j in range(rank)), Fraction())
                             for i in range(rank))
            if any(v < 0 or v > n[i] for i, v in zip(basic, solution)):
                continue
            for i, value in zip(basic, solution):
                q[i] = value
            examined += 1
            variable.update(i for i in range(m) if q[i] != k[i])
            if len(variable) == m:
                return BoundaryFace((None,) * m, tuple(range(m)), examined)
    fixed = tuple(None if i in variable else int(k[i] == n[i]) for i in range(m))
    internal = tuple(i for i in range(m) if fixed[i] is None)
    return BoundaryFace(fixed, internal, examined)


def softplus(value):
    if value > 0:
        return value + math.log1p(math.exp(-value))
    return math.log1p(math.exp(value))


def row_log_likelihood(trials, successes, eta):
    total = 0.0
    if successes:
        total -= successes * softplus(-eta)
    if trials != successes:
        total -= (trials - successes) * softplus(eta)
    return total


def offset_score_information(a, n, k, offsets, theta):
    dimension = len(theta)
    etas = tuple(o + math.fsum(float(x) * b for x, b in zip(row, theta))
                 for row, o in zip(a, offsets))
    probabilities = tuple(expit(eta) for eta in etas)
    score = tuple(math.fsum(float(row[j]) * (successes - trials * p)
                            for row, trials, successes, p in zip(a, n, k, probabilities))
                  for j in range(dimension))
    information = tuple(tuple(math.fsum(
        float(row[j]) * float(row[l]) * trials * p * (1 - p)
        for row, trials, p in zip(a, n, probabilities))
        for l in range(dimension)) for j in range(dimension))
    return etas, probabilities, score, information


@dataclass(frozen=True)
class OffsetFit:
    theta: tuple
    probabilities: tuple
    information: tuple
    iterations: int
    score_norm: float


def newton_offset(a, n, k, offsets, dimension, theta0, max_iterations=200):
    theta = tuple(theta0)
    for iteration in range(max_iterations + 1):
        etas, p, score, information = offset_score_information(a, n, k, offsets, theta)
        step = solve_positive_system(information, score)
        norm = max(map(abs, score), default=0.0)
        if max(map(abs, step), default=0.0) <= 2e-12:
            return OffsetFit(theta, p, information, iteration, norm), etas
        old_ll = math.fsum(row_log_likelihood(t, s, e) for t, s, e in zip(n, k, etas))
        scale = 1.0
        for _ in range(60):
            candidate = tuple(v + scale * s for v, s in zip(theta, step))
            new_etas, _, _, _ = offset_score_information(a, n, k, offsets, candidate)
            new_ll = math.fsum(row_log_likelihood(t, s, e) for t, s, e in zip(n, k, new_etas))
            if new_ll >= old_ll - 2e-13 * max(1.0, abs(old_ll)):
                theta = candidate
                break
            scale *= 0.5
        else:
            raise NumericalFitError("likelihood line search failed")
    raise NumericalFitError("constrained solve did not converge")


def continuation(a, n, k, offsets, dimension, lam_lo, theta_lo, lam_hi, depth=0):
    scaled = tuple(lam_hi * o for o in offsets)
    try:
        return newton_offset(a, n, k, scaled, dimension, theta_lo)
    except NumericalFitError:
        if depth >= 40:
            raise
        mid = (lam_lo + lam_hi) / 2
        fit_mid, _ = continuation(a, n, k, offsets, dimension, lam_lo, theta_lo, mid, depth + 1)
        return continuation(a, n, k, offsets, dimension, mid, fit_mid.theta, lam_hi, depth + 1)


def fit_offset(a, n, k, offsets, dimension):
    if (any(len(row) != dimension for row in a) or len(a) != len(n)
            or len(a) != len(k) or len(a) != len(offsets)):
        raise NumericalFitError("offset input dimension mismatch")
    if not any(offsets):
        return newton_offset(a, n, k, tuple(offsets), dimension, (0.0,) * dimension)
    zero = (0.0,) * len(offsets)
    initial, _ = newton_offset(a, n, k, zero, dimension, (0.0,) * dimension)
    return continuation(a, n, k, tuple(offsets), dimension, 0.0, initial.theta, 1.0)


@dataclass(frozen=True)
class NullArtifact:
    fit_id: str
    frozen: FrozenDesign
    equations: tuple
    offsets: tuple
    probabilities: tuple
    boundary: tuple
    internal_row_ids: tuple
    basis: tuple
    theta: tuple
    information: tuple
    log_likelihood: float
    diagnostics: tuple

    def to_value(self):
        return {"fit_id": self.fit_id,
                "equations": [eq.to_value(self.frozen.column_ids) for eq in self.equations],
                "frozen": self.frozen.to_value(),
                "offsets": list(self.offsets),
                "probabilities": list(self.probabilities),
                "boundary": list(self.boundary),
                "internal_row_ids": list(self.internal_row_ids),
                "basis": [list(row) for row in self.basis],
                "theta": list(self.theta),
                "information": [list(row) for row in self.information],
                "log_likelihood": self.log_likelihood,
                "diagnostics": dict(self.diagnostics)}

    @classmethod
    def from_value(cls, value):
        frozen = FrozenDesign.from_value(value["frozen"])
        equations = parse_equations(value["equations"], frozen.column_ids)
        result = cls(value["fit_id"], frozen, equations, tuple(value["offsets"]),
                     tuple(value["probabilities"]), tuple(value["boundary"]),
                     tuple(value["internal_row_ids"]),
                     tuple(tuple(row) for row in value["basis"]), tuple(value["theta"]),
                     tuple(tuple(row) for row in value["information"]),
                     value["log_likelihood"], tuple(sorted(value["diagnostics"].items())))
        if result.to_value() != value:
            raise ValueError("noncanonical null artifact")
        validate_null_artifact(result)
        return result


def constrained_arrays(frozen, equations):
    beta0, null_basis = affine_parametrization(equations, len(frozen.column_ids))
    offsets = tuple(sum((x * b for x, b in zip(row, beta0)), Fraction()) for row in frozen.x)
    a_rows = tuple(tuple(sum((x * f for x, f in zip(row, direction)), Fraction())
                         for direction in null_basis) for row in frozen.x)
    return offsets, a_rows, len(null_basis)


def fit_constrained(frozen, request):
    validate_frozen_design(frozen)
    if request.column_ids != frozen.column_ids:
        raise ValueError("null request column binding mismatch")
    offsets, a_rows, dimension = constrained_arrays(frozen, request.equations)
    face = identify_moment_face(a_rows, frozen.n, frozen.k)
    indices = face.internal_indices
    space = row_space([a_rows[i] for i in indices], dimension)
    a_hat = tuple(space.coordinates(a_rows[i]) for i in indices)
    n_internal = tuple(frozen.n[i] for i in indices)
    k_internal = tuple(frozen.k[i] for i in indices)
    o_internal = tuple(float(offsets[i]) for i in indices)
    finite, etas = fit_offset(a_hat, n_internal, k_internal, o_internal, len(space.basis))
    probabilities = list(face.fixed)
    for i, p in zip(indices, finite.probabilities):
        probabilities[i] = p
    log_likelihood = math.fsum(row_log_likelihood(t, s, e)
                               for t, s, e in zip(n_internal, k_internal, etas))
    status = "finite" if len(indices) == len(frozen.x) else ("complete" if not indices else "quasi")
    diagnostics = {"status": status, "design_rank": len(row_space(frozen.x).basis),
                   "finite_rank": len(space.basis),
                   "constraint_rank": len(frozen.column_ids) - dimension,
                   "iterations": finite.iterations, "score_norm": finite.score_norm,
                   "log_likelihood": log_likelihood, "vertices_examined": face.vertices_examined}
    result = NullArtifact(request.fit_id, frozen, request.equations, offsets,
                          tuple(probabilities), face.fixed,
                          tuple(frozen.row_ids[i] for i in indices), space.basis,
                          finite.theta, finite.information, log_likelihood,
                          tuple(sorted(diagnostics.items())))
    validate_null_artifact(result)
    return result


def validate_null_artifact(artifact):
    design = validate_frozen_design(artifact.frozen)
    identifier(artifact.fit_id)
    width = len(design.column_ids)
    equations = tuple(artifact.equations)
    if len(equations) > 4 or any(type(eq) is not NullEquation for eq in equations):
        raise ValueError("invalid null equations")
    if any(len(eq.coefficients) != width or any(type(v) is not Fraction for v in eq.coefficients)
           or type(eq.rhs) is not Fraction for eq in equations):
        raise ValueError("invalid null equation encoding")
    offsets, a_rows, dimension = constrained_arrays(design, equations)
    if tuple(offsets) != tuple(artifact.offsets) or any(type(v) is not Fraction for v in offsets):
        raise ValueError("null offset mismatch")
    face = identify_moment_face(a_rows, design.n, design.k)
    indices = face.internal_indices
    if (artifact.boundary != face.fixed
            or artifact.internal_row_ids != tuple(design.row_ids[i] for i in indices)):
        raise ValueError("null face identity mismatch")
    space = row_space([a_rows[i] for i in indices], dimension)
    if artifact.basis != space.basis or any(type(v) is not Fraction for row in artifact.basis for v in row):
        raise ValueError("invalid exact constrained space")
    d = len(space.basis)
    if len(artifact.theta) != d or any(not math.isfinite(v) for v in artifact.theta):
        raise NumericalFitError("invalid constrained coordinates")
    a_hat = tuple(space.coordinates(a_rows[i]) for i in indices)
    n_internal = tuple(design.n[i] for i in indices)
    k_internal = tuple(design.k[i] for i in indices)
    o_internal = tuple(float(offsets[i]) for i in indices)
    etas, p, score, information = offset_score_information(
        a_hat, n_internal, k_internal, o_internal, artifact.theta)
    if len(artifact.probabilities) != len(design.x) or len(artifact.information) != d:
        raise ValueError("null dimension mismatch")
    for i, flag in enumerate(face.fixed):
        actual = artifact.probabilities[i]
        if type(actual) not in (float, int) or not math.isfinite(actual):
            raise ValueError("invalid null probability")
        if flag is not None and actual != flag:
            raise ValueError("fixed null probability mismatch")
        if flag is None and not 0 <= actual <= 1:
            raise ValueError("internal null probability mismatch")
    if any(abs(artifact.probabilities[i] - expected) > 2e-12 for i, expected in zip(indices, p)):
        raise ValueError("null probability coordinate mismatch")
    if any(len(row) != d for row in artifact.information):
        raise ValueError("null information dimension mismatch")
    for row, expected in zip(artifact.information, information):
        if any(not math.isfinite(v) or abs(v - e) > 2e-12 * max(1, abs(e))
               for v, e in zip(row, expected)):
            raise ValueError("null information source mismatch")
    if d:
        correction = solve_positive_system(artifact.information, score)
        if max(map(abs, correction), default=0) > 2e-9:
            raise NumericalFitError("unconverged constrained coordinates")
    expected_ll = math.fsum(row_log_likelihood(t, s, e)
                            for t, s, e in zip(n_internal, k_internal, etas))
    if not math.isfinite(artifact.log_likelihood) or abs(artifact.log_likelihood - expected_ll) > 1e-10:
        raise ValueError("null likelihood mismatch")
    diag = dict(artifact.diagnostics)
    status = "finite" if len(indices) == len(design.x) else ("complete" if not indices else "quasi")
    if (diag.get("status") != status or diag.get("finite_rank") != d
            or diag.get("design_rank") != len(row_space(design.x).basis)
            or diag.get("constraint_rank") != width - dimension
            or type(diag.get("iterations")) is not int or diag["iterations"] < 0
            or diag.get("vertices_examined") != face.vertices_examined
            or abs(diag.get("score_norm", math.inf) - max(map(abs, score), default=0)) > 1e-10
            or abs(diag.get("log_likelihood", math.inf) - artifact.log_likelihood) > 1e-10):
        raise ValueError("invalid null diagnostics")
    return artifact
