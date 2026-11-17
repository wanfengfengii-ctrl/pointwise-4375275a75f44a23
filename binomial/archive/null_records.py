from binomial.archive.schema import ArchiveFormatError, ResultNotFound
from binomial.fitting.constrained import NullArtifact, validate_null_artifact
from binomial.reporting.comparison import NullComparison, evaluate_comparison


def validate_null_binding(store, artifact):
    from binomial.archive.fit_records import load_fit
    if load_fit(store, artifact.fit_id).frozen != artifact.frozen:
        raise ArchiveFormatError("null fit binding mismatch")
    return artifact


def publish_null(store, null_id, request_id, fingerprint, artifact):
    validate_null_artifact(artifact)
    with store.transaction():
        old = store.get_receipt("null_fit", request_id, fingerprint)
        if old is not None:
            if old["result_id"] != null_id:
                raise ArchiveFormatError("null receipt mismatch")
            load_null(store, null_id)
            return
        validate_null_binding(store, artifact)
        store.put_record(null_id, "null_fit", {
            "published": True, "fit_id": artifact.fit_id, "artifact": artifact.to_value()})
        store.put_receipt("null_fit", request_id, fingerprint, {"result_id": null_id})


def load_null(store, null_id):
    value = store.get_record(null_id, "null_fit")
    if value is None:
        raise ResultNotFound("null fit not found")
    try:
        if (set(value) != {"published", "fit_id", "artifact"}
                or value["published"] is not True
                or value["fit_id"] != value["artifact"]["fit_id"]):
            raise ValueError("null fit is not completely published")
        artifact = NullArtifact.from_value(value["artifact"])
        validate_null_binding(store, artifact)
        return artifact
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ArchiveFormatError("invalid null artifact") from exc


def validate_comparison(store, comparison):
    from binomial.archive.fit_records import load_fit
    artifact = load_null(store, comparison.null_id)
    if artifact.fit_id != comparison.fit_id:
        raise ArchiveFormatError("comparison null binding mismatch")
    expected = evaluate_comparison(comparison.null_id, artifact, load_fit(store, artifact.fit_id))
    if expected != comparison:
        raise ArchiveFormatError("comparison differs from published null")
    return comparison


def publish_comparison(store, comparison_id, request_id, fingerprint, comparison):
    validate_comparison(store, comparison)
    with store.transaction():
        old = store.get_receipt("null_comparison", request_id, fingerprint)
        if old is not None:
            if old["result_id"] != comparison_id:
                raise ArchiveFormatError("comparison receipt mismatch")
            load_comparison(store, comparison_id)
            return
        validate_comparison(store, comparison)
        store.put_record(comparison_id, "null_comparison",
                         {"published": True, "comparison": comparison.to_value()})
        store.put_receipt("null_comparison", request_id, fingerprint,
                          {"result_id": comparison_id})


def load_comparison(store, comparison_id):
    value = store.get_record(comparison_id, "null_comparison")
    if value is None:
        raise ResultNotFound("null comparison not found")
    try:
        if set(value) != {"published", "comparison"} or value["published"] is not True:
            raise ValueError("comparison is not completely published")
        comparison = NullComparison.from_value(value["comparison"])
        validate_comparison(store, comparison)
        return comparison
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ArchiveFormatError("invalid comparison artifact") from exc
