from binomial.archive.schema import ArchiveFormatError, ResultNotFound
from binomial.fitting.boundary import FitArtifact, validate_fit_artifact
from binomial.archive.cohort_snapshots import freeze_cohort
from binomial.archive.design_snapshots import freeze_design, load_design_snapshot


def publish_fit(store, fit_id, request_id, fingerprint, revision, specification, artifact):
    validate_fit_artifact(artifact)
    with store.transaction():
        old = store.get_receipt("fit", request_id, fingerprint)
        if old is not None:
            if old["result_id"] != fit_id:
                raise ArchiveFormatError("fit receipt mismatch")
            load_fit(store, fit_id)
            return
        cohort_snapshot = freeze_cohort(store, revision)
        design_snapshot = freeze_design(store, artifact.frozen, specification, cohort_snapshot)
        store.put_record(fit_id, "fit", {
            "published": True, "cohort_snapshot_id": cohort_snapshot,
            "design_snapshot_id": design_snapshot, "artifact": artifact.to_value()})
        store.put_receipt("fit", request_id, fingerprint, {"result_id": fit_id})


def load_fit(store, fit_id):
    value = store.get_record(fit_id, "fit")
    if value is None:
        raise ResultNotFound("fit not found")
    try:
        if (set(value) != {"published", "cohort_snapshot_id", "design_snapshot_id", "artifact"}
                or value["published"] is not True):
            raise ValueError("fit is not completely published")
        frozen, cohort_id = load_design_snapshot(store, value["design_snapshot_id"])
        if cohort_id != value["cohort_snapshot_id"]:
            raise ValueError("fit cohort snapshot mismatch")
        artifact = FitArtifact.from_value(value["artifact"])
        if artifact.frozen != frozen:
            raise ValueError("fit frozen input mismatch")
        return artifact
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ArchiveFormatError("invalid fit artifact") from exc


def read_result(store, result_id):
    row = store.connection.execute("SELECT kind FROM records WHERE id=?", (result_id,)).fetchone()
    if row is None or row[0] not in ("fit", "report"):
        raise ResultNotFound("published result not found")
    if row[0] == "fit":
        value = load_fit(store, result_id).to_value()
    else:
        from binomial.archive.report_records import load_report
        value = load_report(store, result_id).to_value()
    return {"result_id": result_id, "kind": row[0], **value}
