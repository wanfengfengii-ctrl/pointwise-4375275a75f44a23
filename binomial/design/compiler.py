from dataclasses import dataclass
from binomial.archive.schema import content_digest, identifier
from binomial.design.columns import evaluate_column


@dataclass(frozen=True)
class FrozenDesign:
    cohort_id: str
    revision_id: str
    design_id: str
    design_digest: str
    row_ids: tuple
    column_ids: tuple
    x: tuple
    n: tuple
    k: tuple

    def to_value(self):
        return {"cohort_id": self.cohort_id, "revision_id": self.revision_id,
                "design_id": self.design_id, "design_digest": self.design_digest,
                "row_ids": list(self.row_ids), "column_ids": list(self.column_ids),
                "x": [list(r) for r in self.x], "n": list(self.n), "k": list(self.k)}

    @classmethod
    def from_value(cls, value):
        result = cls(**{**value, "row_ids": tuple(value["row_ids"]),
                        "column_ids": tuple(value["column_ids"]),
                        "x": tuple(tuple(r) for r in value["x"]),
                        "n": tuple(value["n"]), "k": tuple(value["k"])})
        validate_frozen_design(result)
        return result

    @property
    def digest(self):
        return content_digest(self.to_value())


def validate_frozen_design(design):
    for name in (design.cohort_id, design.revision_id, design.design_id):
        identifier(name)
    rows, cols = len(design.row_ids), len(design.column_ids)
    if not 1 <= rows <= 12 or not 1 <= cols <= 4:
        raise ValueError("invalid frozen dimensions")
    if tuple(sorted(design.row_ids)) != design.row_ids or len(set(design.row_ids)) != rows:
        raise ValueError("invalid frozen row identities")
    if len(set(design.column_ids)) != cols:
        raise ValueError("duplicate frozen columns")
    for name in design.row_ids + design.column_ids:
        identifier(name)
    if not isinstance(design.design_digest, str) or len(design.design_digest) != 64:
        raise ValueError("invalid design digest")
    if len(design.x) != rows or len(design.n) != rows or len(design.k) != rows:
        raise ValueError("frozen length mismatch")
    for x, n, k in zip(design.x, design.n, design.k):
        if len(x) != cols or any(type(v) is not int or abs(v) > 8 for v in x):
            raise ValueError("invalid frozen matrix")
        if type(n) is not int or type(k) is not int or not 1 <= n <= 20 or not 0 <= k <= n:
            raise ValueError("invalid frozen counts")
    return design


def compile_design(revision, specification):
    rules = {c.column_id: c for c in specification.definitions}
    rows = tuple(sorted(revision.rows, key=lambda r: r.row_id))
    result = FrozenDesign(
        revision.cohort_id, revision.revision_id, specification.design_id,
        specification.digest, tuple(r.row_id for r in rows), specification.column_ids,
        tuple(tuple(evaluate_column(rules[c], r) for c in specification.column_ids) for r in rows),
        tuple(r.n for r in rows), tuple(r.k for r in rows))
    return validate_frozen_design(result)
