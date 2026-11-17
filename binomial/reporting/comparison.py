import math
from dataclasses import dataclass

from binomial.archive.schema import identifier
from binomial.fitting.finite import NumericalFitError


@dataclass(frozen=True)
class NullComparison:
    null_id: str
    fit_id: str
    original_log_likelihood: float
    null_log_likelihood: float
    statistic: float

    def to_value(self):
        return {"null_id": self.null_id, "fit_id": self.fit_id,
                "original_log_likelihood": self.original_log_likelihood,
                "null_log_likelihood": self.null_log_likelihood,
                "statistic": self.statistic}

    @classmethod
    def from_value(cls, value):
        if set(value) != {"null_id", "fit_id", "original_log_likelihood",
                          "null_log_likelihood", "statistic"}:
            raise ValueError("comparison fields")
        result = cls(identifier(value["null_id"]), identifier(value["fit_id"]),
                     value["original_log_likelihood"], value["null_log_likelihood"],
                     value["statistic"])
        for field in (result.original_log_likelihood, result.null_log_likelihood, result.statistic):
            if type(field) not in (float, int) or not math.isfinite(field):
                raise ValueError("nonfinite comparison value")
        if result.statistic != 2 * (result.original_log_likelihood - result.null_log_likelihood):
            raise ValueError("comparison statistic mismatch")
        if result.to_value() != value:
            raise ValueError("noncanonical comparison")
        return result


def evaluate_comparison(null_id, null_artifact, fit_artifact):
    original = dict(fit_artifact.diagnostics)["log_likelihood"]
    null = null_artifact.log_likelihood
    statistic = 2 * (original - null)
    # The constrained supremum can never exceed the original one; a negative
    # statistic beyond numerical noise signals a solver defect and is reported,
    # never absoluted or truncated into place.
    if statistic < -1e-6:
        raise NumericalFitError("null likelihood exceeds original likelihood")
    return NullComparison(null_id, null_artifact.fit_id, original, null, statistic)
