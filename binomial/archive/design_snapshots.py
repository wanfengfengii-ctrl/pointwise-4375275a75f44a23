from binomial.archive.schema import ArchiveFormatError, ResultNotFound, content_digest
from binomial.design.compiler import FrozenDesign, compile_design
from binomial.design.specification import DesignSpecification, load_design
from binomial.design.columns import validate_columns
from binomial.archive.cohort_snapshots import load_cohort_snapshot


def validate_design_binding(frozen, revision, specification):
    if compile_design(revision, specification) != frozen:
        raise ArchiveFormatError("frozen design binding mismatch")
    return frozen


def freeze_design(store, frozen, specification, cohort_snapshot_id):
    revision = load_cohort_snapshot(store, cohort_snapshot_id)
    validate_design_binding(frozen, revision, specification)
    if load_design(store, specification.design_id) != specification:
        raise ArchiveFormatError("design source mismatch")
    value = {"cohort_snapshot_id": cohort_snapshot_id, "specification": specification.to_value(),
             "frozen": frozen.to_value()}
    snapshot_id = "design-snapshot-" + content_digest(value)
    store.put_record(snapshot_id, "design_snapshot", value)
    return snapshot_id


def load_design_snapshot(store, snapshot_id):
    value = store.get_record(snapshot_id, "design_snapshot")
    if value is None:
        raise ResultNotFound("design snapshot not found")
    try:
        if set(value) != {"cohort_snapshot_id", "specification", "frozen"}:
            raise ValueError("snapshot fields")
        if snapshot_id != "design-snapshot-" + content_digest(value):
            raise ValueError("snapshot digest mismatch")
        raw = value["specification"]
        spec = DesignSpecification(raw["design_id"], tuple(raw["column_ids"]),
                                   validate_columns(raw["definitions"]))
        if load_design(store, spec.design_id) != spec or spec.to_value() != raw:
            raise ValueError("snapshot declaration mismatch")
        revision = load_cohort_snapshot(store, value["cohort_snapshot_id"])
        frozen = FrozenDesign.from_value(value["frozen"])
        validate_design_binding(frozen, revision, spec)
        return frozen, value["cohort_snapshot_id"]
    except (ValueError, TypeError, KeyError) as exc:
        raise ArchiveFormatError("invalid design snapshot") from exc
