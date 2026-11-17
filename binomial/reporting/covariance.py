import math
from binomial.fitting.finite import NumericalFitError, solve_positive_system

InformationError = NumericalFitError


def validate_information(information, dimension):
    if len(information) != dimension or any(len(row) != dimension for row in information):
        raise InformationError("information dimensions")
    solve_positive_system(information, (0.0,) * dimension)
    return information


def effect_variance(information, coordinates):
    validate_information(information, len(coordinates))
    if not any(coordinates):
        return 0.0
    solution = solve_positive_system(information, coordinates)
    value = math.fsum(float(w) * v for w, v in zip(coordinates, solution))
    if not math.isfinite(value) or value < 0:
        raise InformationError("invalid effect variance")
    return value
