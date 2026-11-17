import math
from dataclasses import dataclass
from fractions import Fraction
from binomial.fitting.boundary import validate_fit_artifact
from binomial.reporting.estimability import classify_effect
from binomial.reporting.covariance import effect_variance


@dataclass(frozen=True)
class EffectResult:
    name: str
    ordinal: int
    coefficients: tuple
    status: str
    estimate: float | None
    variance: float | None

    def to_value(self, column_ids):
        return {"name": self.name, "ordinal": self.ordinal,
                "coefficients": {c: v for c, v in zip(column_ids, self.coefficients) if v},
                "status": self.status, "estimate": self.estimate, "variance": self.variance}


@dataclass(frozen=True)
class EffectReport:
    fit_id: str
    frozen_digest: str
    revision_id: str
    design_digest: str
    column_ids: tuple
    items: tuple

    def to_value(self):
        return {"fit_id": self.fit_id, "frozen_digest": self.frozen_digest,
                "revision_id": self.revision_id, "design_digest": self.design_digest,
                "column_ids": list(self.column_ids),
                "items": [item.to_value(self.column_ids) for item in self.items]}

    @classmethod
    def from_value(cls, value):
        columns = tuple(value["column_ids"])
        items = tuple(EffectResult(
            item["name"], item["ordinal"], tuple(item["coefficients"].get(c, Fraction()) for c in columns),
            item["status"], item["estimate"], item["variance"]) for item in value["items"])
        result = cls(value["fit_id"], value["frozen_digest"], value["revision_id"],
                     value["design_digest"], columns, items)
        if result.to_value() != value:
            raise ValueError("noncanonical report")
        return result


def evaluate_effects(fit, request):
    validate_fit_artifact(fit)
    if request.column_ids != fit.frozen.column_ids:
        raise ValueError("effect column binding mismatch")
    items = []
    for index, item in enumerate(request.effects):
        classification = classify_effect(fit, item.coefficients)
        if not classification.estimable:
            result = EffectResult(item.name, index, item.coefficients, "not_estimable", None, None)
        else:
            coordinates = classification.coordinates
            estimate = math.fsum(float(w) * theta for w, theta in zip(coordinates, fit.theta))
            variance = effect_variance(fit.information, coordinates)
            if not math.isfinite(estimate):
                raise ArithmeticError("nonfinite effect estimate")
            result = EffectResult(item.name, index, item.coefficients, "estimable", estimate, variance)
        items.append(result)
    return EffectReport(request.fit_id, fit.frozen.digest, fit.frozen.revision_id,
                        fit.frozen.design_digest, fit.frozen.column_ids, tuple(items))


def validate_effect_report(report, fit):
    from binomial.reporting.requests import validate_report_request
    request = validate_report_request(report.fit_id, report.column_ids,
        [{"name": item.name, "coefficients": item.to_value(report.column_ids)["coefficients"]}
         for item in report.items])
    expected = evaluate_effects(fit, request)
    if expected.to_value() != report.to_value():
        raise ValueError("report differs from frozen fit")
    return report
