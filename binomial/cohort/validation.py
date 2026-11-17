from collections.abc import Mapping

from binomial.archive.schema import identifier
from binomial.cohort.records import Observation


class CohortValidationError(ValueError):
    pass


def validate_observation(value):
    try:
        if isinstance(value, Observation):
            value = value.to_value()
        if not isinstance(value, Mapping) or set(value) != {"row_id", "values", "n", "k"}:
            raise ValueError("observation fields")
        row_id = identifier(value["row_id"])
        n, k = value["n"], value["k"]
        if type(n) is not int or type(k) is not int or not 1 <= n <= 20 or not 0 <= k <= n:
            raise ValueError("invalid binomial counts")
        values = value["values"]
        if not isinstance(values, Mapping) or not 1 <= len(values) <= 4:
            raise ValueError("one to four named inputs required")
        for name, coordinate in values.items():
            identifier(name)
            if type(coordinate) is not int or abs(coordinate) > 8:
                raise ValueError("invalid integer coordinate")
        return Observation(row_id, tuple(sorted(values.items())), n, k)
    except (ValueError, TypeError, KeyError) as exc:
        raise CohortValidationError(str(exc)) from exc


def validate_batch(values):
    if isinstance(values, (str, bytes, Mapping)):
        raise CohortValidationError("batch must be an iterable of observations")
    rows = tuple(validate_observation(v) for v in values)
    if not rows or len(rows) > 12 or len({v.row_id for v in rows}) != len(rows):
        raise CohortValidationError("empty, oversized, or duplicate-identity batch")
    return tuple(sorted(rows, key=lambda row: row.row_id))


def validate_merged_cohort(rows):
    rows = tuple(validate_observation(v) for v in rows)
    if not 1 <= len(rows) <= 12 or len({r.row_id for r in rows}) != len(rows):
        raise CohortValidationError("invalid merged cohort")
    return tuple(sorted(rows, key=lambda row: row.row_id))
