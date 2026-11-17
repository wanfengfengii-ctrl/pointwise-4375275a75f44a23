from binomial.archive.schema import RequestConflict, content_digest, identifier
from binomial.reporting.requests import validate_report_request, report_request_fingerprint
from binomial.reporting.effects import evaluate_effects
from binomial.archive.fit_records import load_fit
from binomial.archive.report_records import load_report, publish_report

ReportRequestConflict = RequestConflict


def report(store, request_id, fit_id, ordered_effects):
    identifier(request_id)
    artifact = load_fit(store, fit_id)
    request = validate_report_request(fit_id, artifact.frozen.column_ids, ordered_effects)
    fingerprint = report_request_fingerprint(request)
    old = store.get_receipt("report", request_id, fingerprint)
    if old is not None:
        load_report(store, old["result_id"])
        return old["result_id"]
    candidate = evaluate_effects(artifact, request)
    result_id = "report-" + content_digest({"request_id": request_id, "fingerprint": fingerprint})
    publish_report(store, result_id, request_id, fingerprint, candidate)
    return result_id
