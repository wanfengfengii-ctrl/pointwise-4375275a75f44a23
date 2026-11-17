from dataclasses import dataclass
from binomial.archive.schema import ArchiveFormatError, RequestConflict, ResultNotFound, content_digest, identifier
from binomial.design.columns import validate_columns

DesignConflict = RequestConflict


@dataclass(frozen=True)
class DesignSpecification:
    design_id: str
    column_ids: tuple
    definitions: tuple

    def to_value(self):
        return {"design_id": self.design_id, "column_ids": list(self.column_ids),
                "definitions": [c.to_value() for c in self.definitions]}

    @property
    def digest(self):
        return content_digest(self.to_value())


def _specification(design_id, column_ids, definitions):
    identifier(design_id)
    ids = tuple(column_ids)
    rules = validate_columns(definitions)
    if not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        raise ValueError("invalid column order")
    catalog = {c.column_id for c in rules}
    if any(identifier(c) not in catalog for c in ids):
        raise ValueError("unknown design column")
    return DesignSpecification(design_id, ids, rules)


def register_design(store, design_id, column_ids, definitions):
    spec = _specification(design_id, column_ids, definitions)
    with store.transaction():
        old = store.get_record("design-" + content_digest(design_id), "design")
        if old is not None and old != spec.to_value():
            raise DesignConflict("design is immutable")
        store.put_record("design-" + content_digest(design_id), "design", spec.to_value())
    return spec


def load_design(store, design_id):
    value = store.get_record("design-" + content_digest(identifier(design_id)), "design")
    if value is None:
        raise ResultNotFound("design not found")
    try:
        result = _specification(value["design_id"], value["column_ids"], value["definitions"])
        if result.design_id != design_id or result.to_value() != value:
            raise ValueError("design binding mismatch")
        return result
    except (ValueError, TypeError, KeyError) as exc:
        raise ArchiveFormatError("invalid design") from exc
