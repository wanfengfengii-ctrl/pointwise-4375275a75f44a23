from dataclasses import dataclass
from binomial.archive.schema import content_digest
from binomial.design.contrasts import parse_contrast

ReportRequestError = ValueError


@dataclass(frozen=True)
class EffectRequest:
    name: str
    coefficients: tuple


@dataclass(frozen=True)
class ReportRequest:
    fit_id: str
    column_ids: tuple
    effects: tuple

    def to_value(self):
        return {"fit_id": self.fit_id, "column_ids": list(self.column_ids),
                "effects": [{"name": e.name, "coefficients": {
                    c: v for c, v in zip(self.column_ids, e.coefficients) if v}}
                            for e in self.effects]}


def validate_report_request(fit_id, column_ids, ordered_effects):
    from binomial.archive.schema import identifier
    identifier(fit_id)
    result = []
    for value in ordered_effects:
        if not isinstance(value, dict) or set(value) != {"name", "coefficients"}:
            raise ReportRequestError("effect fields")
        contrast = parse_contrast(value["name"], value["coefficients"], column_ids)
        result.append(EffectRequest(contrast.name, contrast.coefficients))
    if len({e.name for e in result}) != len(result):
        raise ReportRequestError("duplicate effect name")
    return ReportRequest(fit_id, tuple(column_ids), tuple(result))


def report_request_fingerprint(request):
    return content_digest(request.to_value())
