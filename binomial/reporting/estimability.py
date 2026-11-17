from dataclasses import dataclass
from binomial.fitting.subspace import ExactRowSpace


@dataclass(frozen=True)
class EstimabilityResult:
    estimable: bool
    coordinates: tuple | None


def classify_effect(fit, coefficients):
    space = ExactRowSpace(fit.basis, len(fit.frozen.column_ids))
    coordinates = space.coordinates(coefficients)
    return EstimabilityResult(coordinates is not None, coordinates)
