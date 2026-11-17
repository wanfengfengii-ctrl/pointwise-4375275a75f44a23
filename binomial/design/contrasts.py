from dataclasses import dataclass
from fractions import Fraction
from collections.abc import Mapping
from binomial.archive.schema import identifier


def rational(value):
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    if isinstance(value, str):
        return Fraction(value)
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(type(x) is int for x in value):
        return Fraction(*value)
    raise ValueError("coefficient must be an exact rational")


def canonical_coefficients(coefficients, column_ids):
    if not isinstance(coefficients, Mapping):
        raise ValueError("coefficients must be a named mapping")
    if any(c not in column_ids for c in coefficients):
        raise ValueError("unknown effect column")
    return tuple(rational(coefficients.get(c, 0)) for c in column_ids)


@dataclass(frozen=True)
class NamedContrast:
    name: str
    coefficients: tuple

    def to_value(self, column_ids):
        return {"name": self.name, "coefficients": {
            c: v for c, v in zip(column_ids, self.coefficients) if v}}


def parse_contrast(name, coefficients, column_ids):
    return NamedContrast(identifier(name), canonical_coefficients(coefficients, column_ids))


def transport_contrast(coefficients, transform):
    c = tuple(rational(v) for v in coefficients)
    t = tuple(tuple(rational(v) for v in row) for row in transform)
    if len(t) != len(c) or any(len(row) != len(c) for row in t):
        raise ValueError("square column transform required")
    from binomial.fitting.subspace import row_space
    if len(row_space(t, len(c)).basis) != len(c):
        raise ValueError("column transform must be invertible")
    return tuple(sum((t[i][j] * c[i] for i in range(len(c))), Fraction())
                 for j in range(len(c)))
