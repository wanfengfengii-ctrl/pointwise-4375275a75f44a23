from binomial.archive.schema import RequestConflict, content_digest, identifier
from binomial.cohort.records import BatchReceipt
from binomial.cohort.validation import validate_batch
from binomial.cohort.revisions import load_revision, merge_revision, save_revision

CohortRequestConflict = RequestConflict


def batch_fingerprint(batch):
    return content_digest([r.to_value() for r in validate_batch(batch)])


def apply_cohort(store, cohort_id, request_id, observations):
    identifier(cohort_id)
    identifier(request_id)
    batch = validate_batch(observations)
    fingerprint = batch_fingerprint(batch)
    scope = "cohort:" + cohort_id
    with store.transaction():
        old = store.get_receipt(scope, request_id, fingerprint)
        if old is not None:
            load_revision(store, cohort_id, old["revision_id"])
            return BatchReceipt(**old)
        current = store.current_revision(cohort_id)
        previous = None if current is None else load_revision(store, cohort_id, current)
        revision = merge_revision(cohort_id, previous, batch)
        save_revision(store, revision)
        store.set_current(cohort_id, revision.revision_id)
        receipt = BatchReceipt(cohort_id, request_id, revision.revision_id)
        store.put_receipt(scope, request_id, fingerprint, receipt.to_value())
    return receipt
