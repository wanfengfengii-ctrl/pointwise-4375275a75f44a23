from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    row_id: str
    values: tuple
    n: int
    k: int

    def __post_init__(self):
        source = self.values.items() if isinstance(self.values, dict) else self.values
        object.__setattr__(self, "values", tuple(sorted(tuple(pair) for pair in source)))

    def to_value(self):
        return {"row_id": self.row_id, "values": dict(self.values), "n": self.n, "k": self.k}


@dataclass(frozen=True)
class BatchReceipt:
    cohort_id: str
    request_id: str
    revision_id: str

    def to_value(self):
        return {"cohort_id": self.cohort_id, "request_id": self.request_id,
                "revision_id": self.revision_id}
