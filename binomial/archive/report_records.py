from binomial.archive.schema import ArchiveFormatError, ResultNotFound
from binomial.reporting.effects import EffectReport, validate_effect_report


def validate_report_binding(store, report):
    # Import after module initialization: archive loading is acyclic at runtime.
    from binomial.archive.fit_records import load_fit
    artifact = load_fit(store, report.fit_id)
    validate_effect_report(report, artifact)
    return report


def publish_report(store, report_id, request_id, fingerprint, report):
    validate_report_binding(store, report)
    with store.transaction():
        old = store.get_receipt("report", request_id, fingerprint)
        if old is not None:
            if old["result_id"] != report_id:
                raise ArchiveFormatError("report receipt mismatch")
            load_report(store, report_id)
            return
        validate_report_binding(store, report)
        store.put_record(report_id, "report", {"published": True, "report": report.to_value()})
        store.put_receipt("report", request_id, fingerprint, {"result_id": report_id})


def load_report(store, report_id):
    value = store.get_record(report_id, "report")
    if value is None:
        raise ResultNotFound("report not found")
    try:
        if set(value) != {"published", "report"} or value["published"] is not True:
            raise ValueError("report is not completely published")
        report = EffectReport.from_value(value["report"])
        validate_report_binding(store, report)
        return report
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ArchiveFormatError("invalid report artifact") from exc
