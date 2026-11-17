import itertools
import math
from dataclasses import dataclass
from fractions import Fraction
from binomial.design.compiler import FrozenDesign, validate_frozen_design
from binomial.fitting.subspace import ExactRowSpace, independent_constraints, row_space, solve_exact
from binomial.fitting.finite import fit_finite, NumericalFitError, solve_positive_system
from binomial.fitting.likelihood import binomial_log_likelihood, score_and_information


@dataclass(frozen=True)
class BoundaryFace:
    fixed: tuple
    internal_indices: tuple
    vertices_examined: int


def identify_face(design):
    validate_frozen_design(design)
    m = len(design.x)
    constraints = tuple(tuple(row[j] for row in design.x) for j in range(len(design.column_ids)))
    rhs = tuple(sum(row[i] * design.k[i] for i in range(m)) for row in constraints)
    equations, target = independent_constraints(constraints, rhs)
    rank = len(equations)
    if rank == 0:
        return BoundaryFace((None,) * m, tuple(range(m)), 0)
    variable = {i for i in range(m) if 0 < design.k[i] < design.n[i]}
    examined = 0
    for basic in itertools.combinations(range(m), rank):
        matrix = tuple(tuple(row[i] for i in basic) for row in equations)
        inverse_columns = [solve_exact(matrix, tuple(int(i == j) for i in range(rank)), rank)
                           for j in range(rank)]
        if any(col is None for col in inverse_columns):
            continue
        # A singular square system can have consistent unit right hand sides
        # only if it is invertible; all unit vectors were checked above.
        others = tuple(i for i in range(m) if i not in basic)
        for bits in itertools.product((0, 1), repeat=len(others)):
            q = [Fraction() for _ in range(m)]
            for i, bit in zip(others, bits):
                q[i] = Fraction(bit * design.n[i])
            b = tuple(target[j] - sum((equations[j][i] * q[i] for i in others), Fraction())
                      for j in range(rank))
            solution = tuple(sum((inverse_columns[j][i] * b[j] for j in range(rank)), Fraction())
                             for i in range(rank))
            if any(v < 0 or v > design.n[i] for i, v in zip(basic, solution)):
                continue
            for i, value in zip(basic, solution):
                q[i] = value
            examined += 1
            variable.update(i for i in range(m) if q[i] != design.k[i])
            if len(variable) == m:
                return BoundaryFace((None,) * m, tuple(range(m)), examined)
    fixed = tuple(None if i in variable else int(design.k[i] == design.n[i]) for i in range(m))
    internal = tuple(i for i in range(m) if fixed[i] is None)
    return BoundaryFace(fixed, internal, examined)


@dataclass(frozen=True)
class FitArtifact:
    frozen: FrozenDesign
    probabilities: tuple
    boundary: tuple
    internal_row_ids: tuple
    basis: tuple
    theta: tuple
    information: tuple
    diagnostics: tuple

    def to_value(self):
        return {"frozen": self.frozen.to_value(), "probabilities": list(self.probabilities),
                "boundary": list(self.boundary), "internal_row_ids": list(self.internal_row_ids),
                "basis": [list(row) for row in self.basis], "theta": list(self.theta),
                "information": [list(row) for row in self.information],
                "diagnostics": dict(self.diagnostics)}

    @classmethod
    def from_value(cls, value):
        result = cls(FrozenDesign.from_value(value["frozen"]), tuple(value["probabilities"]),
                     tuple(value["boundary"]), tuple(value["internal_row_ids"]),
                     tuple(tuple(row) for row in value["basis"]), tuple(value["theta"]),
                     tuple(tuple(row) for row in value["information"]),
                     tuple(sorted(value["diagnostics"].items())))
        validate_fit_artifact(result)
        return result


def fit_extended(design, finite_solver=fit_finite):
    face = identify_face(design)
    indices = face.internal_indices
    space = row_space([design.x[i] for i in indices], len(design.column_ids))
    a = tuple(space.coordinates(design.x[i]) for i in indices)
    n, k = tuple(design.n[i] for i in indices), tuple(design.k[i] for i in indices)
    finite = finite_solver(a, n, k, len(space.basis))
    probabilities = list(face.fixed)
    for i, p in zip(indices, finite.probabilities):
        probabilities[i] = p
    status = "finite" if len(indices) == len(design.x) else ("complete" if not indices else "quasi")
    diagnostics = {"status": status, "design_rank": len(row_space(design.x).basis),
                   "finite_rank": len(space.basis), "iterations": finite.iterations,
                   "score_norm": finite.score_norm,
                   "log_likelihood": binomial_log_likelihood(design.n, design.k, probabilities),
                   "vertices_examined": face.vertices_examined}
    result = FitArtifact(design, tuple(probabilities), face.fixed,
                         tuple(design.row_ids[i] for i in indices), space.basis,
                         finite.theta, finite.information, tuple(sorted(diagnostics.items())))
    validate_fit_artifact(result)
    return result


def validate_fit_artifact(fit):
    design = validate_frozen_design(fit.frozen)
    face = identify_face(design)
    indices = face.internal_indices
    if fit.boundary != face.fixed or fit.internal_row_ids != tuple(design.row_ids[i] for i in indices):
        raise ValueError("fit face identity mismatch")
    space = row_space([design.x[i] for i in indices], len(design.column_ids))
    if fit.basis != space.basis or any(type(v) is not Fraction for row in fit.basis for v in row):
        raise ValueError("invalid exact finite space")
    d = len(space.basis)
    if len(fit.theta) != d or any(not math.isfinite(v) for v in fit.theta):
        raise NumericalFitError("invalid finite coordinates")
    a = tuple(space.coordinates(design.x[i]) for i in indices)
    p, score, information = score_and_information(
        a, tuple(design.n[i] for i in indices), tuple(design.k[i] for i in indices), fit.theta)
    if len(fit.probabilities) != len(design.x) or len(fit.information) != d:
        raise ValueError("fit dimension mismatch")
    for i, flag in enumerate(face.fixed):
        actual = fit.probabilities[i]
        if type(actual) not in (float, int) or not math.isfinite(actual):
            raise ValueError("invalid probability")
        if flag is not None and actual != flag:
            raise ValueError("fixed probability mismatch")
        if flag is None and not 0 < actual < 1:
            raise ValueError("internal probability mismatch")
    if any(abs(fit.probabilities[i] - expected) > 2e-12 for i, expected in zip(indices, p)):
        raise ValueError("probability coordinate mismatch")
    if any(len(row) != d for row in fit.information):
        raise ValueError("information dimension mismatch")
    for row, expected in zip(fit.information, information):
        if any(not math.isfinite(v) or abs(v - e) > 2e-12 * max(1, abs(e))
               for v, e in zip(row, expected)):
            raise ValueError("information source mismatch")
    correction = solve_positive_system(fit.information, score)
    if max(map(abs, correction), default=0) > 2e-9:
        raise NumericalFitError("unconverged finite coordinates")
    diag = dict(fit.diagnostics)
    status = "finite" if len(indices) == len(design.x) else ("complete" if not indices else "quasi")
    if (diag.get("status") != status or diag.get("finite_rank") != d
            or diag.get("design_rank") != len(row_space(design.x).basis)
            or type(diag.get("iterations")) is not int or diag["iterations"] < 0
            or diag.get("vertices_examined") != face.vertices_examined
            or abs(diag.get("score_norm", math.inf) - max(map(abs, score), default=0)) > 1e-10
            or abs(diag.get("log_likelihood", math.inf) -
                   binomial_log_likelihood(design.n, design.k, fit.probabilities)) > 1e-10):
        raise ValueError("invalid fit diagnostics")
    return fit
