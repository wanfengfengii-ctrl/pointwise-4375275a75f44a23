from binomial.archive.schema import ArchiveFormatError, ResultNotFound, content_digest
from binomial.cohort.revisions import load_revision, merge_revision
from binomial.cohort.validation import validate_merged_cohort


def validate_cohort_snapshot(value):
    try:
        rows = validate_merged_cohort(value["rows"])
        revision = merge_revision(value["cohort_id"], None, rows)
        if revision.to_value() != value:
            raise ValueError("snapshot identity mismatch")
        return revision
    except (KeyError, ValueError, TypeError) as exc:
        raise ArchiveFormatError("invalid cohort snapshot") from exc


def freeze_cohort(store, revision):
    value = revision.to_value()
    validate_cohort_snapshot(value)
    original = load_revision(store, revision.cohort_id, revision.revision_id)
    if original != revision:
        raise ArchiveFormatError("cohort source mismatch")
    snapshot_id = "cohort-snapshot-" + content_digest(value)
    store.put_record(snapshot_id, "cohort_snapshot", value)
    return snapshot_id


def load_cohort_snapshot(store, snapshot_id):
    value = store.get_record(snapshot_id, "cohort_snapshot")
    if value is None:
        raise ResultNotFound("cohort snapshot not found")
    if snapshot_id != "cohort-snapshot-" + content_digest(value):
        raise ArchiveFormatError("cohort snapshot digest mismatch")
    revision = validate_cohort_snapshot(value)
    if load_revision(store, revision.cohort_id, revision.revision_id) != revision:
        raise ArchiveFormatError("cohort revision binding mismatch")
    return revision
