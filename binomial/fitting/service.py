from binomial.archive.schema import RequestConflict, content_digest, identifier
from binomial.cohort.revisions import load_revision
from binomial.design.specification import load_design
from binomial.design.compiler import compile_design
from binomial.fitting.boundary import fit_extended
from binomial.fitting.constrained import (
    fit_constrained, null_request_fingerprint, validate_null_request,
)
from binomial.fitting.finite import fit_finite
from binomial.archive.fit_records import load_fit, publish_fit
from binomial.archive.null_records import load_null, publish_null

FitRequestConflict = RequestConflict
NullRequestConflict = RequestConflict


def fit_request_fingerprint(revision, specification):
    return content_digest({"cohort_id": revision.cohort_id, "revision_id": revision.revision_id,
                           "design_id": specification.design_id, "design_digest": specification.digest})


def fit(store, request_id, cohort_revision, design_id, *, finite_solver=fit_finite):
    identifier(request_id)
    if not isinstance(cohort_revision, (tuple, list)) or len(cohort_revision) != 2:
        raise ValueError("cohort_revision must be (cohort_id, revision_id)")
    cohort_id, revision_id = cohort_revision
    identifier(revision_id)
    revision = load_revision(store, cohort_id, revision_id)
    specification = load_design(store, design_id)
    fingerprint = fit_request_fingerprint(revision, specification)
    old = store.get_receipt("fit", request_id, fingerprint)
    if old is not None:
        load_fit(store, old["result_id"])
        return old["result_id"]
    frozen = compile_design(revision, specification)
    candidate = fit_extended(frozen, finite_solver)
    result_id = "fit-" + content_digest({"request_id": request_id, "fingerprint": fingerprint})
    publish_fit(store, result_id, request_id, fingerprint, revision, specification, candidate)
    return result_id


def fit_null(store, request_id, fit_id, equations):
    identifier(request_id)
    artifact = load_fit(store, fit_id)
    request = validate_null_request(fit_id, artifact.frozen.column_ids, equations)
    fingerprint = null_request_fingerprint(request)
    old = store.get_receipt("null_fit", request_id, fingerprint)
    if old is not None:
        load_null(store, old["result_id"])
        return old["result_id"]
    candidate = fit_constrained(artifact.frozen, request)
    result_id = "null-" + content_digest({"request_id": request_id, "fingerprint": fingerprint})
    publish_null(store, result_id, request_id, fingerprint, candidate)
    return result_id
