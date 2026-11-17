from dataclasses import dataclass

from binomial.archive.schema import ArchiveFormatError, ResultNotFound, content_digest
from binomial.cohort.validation import validate_merged_cohort


@dataclass(frozen=True)
class CohortRevision:
    cohort_id: str
    revision_id: str
    rows: tuple

    def to_value(self):
        return {"cohort_id": self.cohort_id, "revision_id": self.revision_id,
                "rows": [r.to_value() for r in self.rows]}


def merge_revision(cohort_id, previous, batch):
    merged = {} if previous is None else {r.row_id: r for r in previous.rows}
    merged.update({r.row_id: r for r in batch})
    rows = validate_merged_cohort(merged.values())
    identity = {"cohort_id": cohort_id, "rows": [r.to_value() for r in rows]}
    return CohortRevision(cohort_id, "revision-" + content_digest(identity), rows)


def save_revision(store, revision):
    store.put_record(revision.revision_id, "cohort_revision", revision.to_value())


def load_revision(store, cohort_id, revision_id=None):
    revision_id = revision_id or store.current_revision(cohort_id)
    if revision_id is None:
        raise ResultNotFound("cohort not found")
    value = store.get_record(revision_id, "cohort_revision")
    if value is None:
        raise ResultNotFound("revision not found")
    try:
        rows = validate_merged_cohort(value["rows"])
        result = merge_revision(cohort_id, None, rows)
        if result.to_value() != value or result.revision_id != revision_id:
            raise ValueError("revision binding mismatch")
        return result
    except (ValueError, TypeError, KeyError) as exc:
        raise ArchiveFormatError("invalid cohort revision") from exc
