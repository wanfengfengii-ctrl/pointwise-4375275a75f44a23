from dataclasses import dataclass
from binomial.archive.schema import identifier


@dataclass(frozen=True)
class ColumnDefinition:
    column_id: str
    source: str | None = None
    constant: int | None = None

    def to_value(self):
        return {"column_id": self.column_id, "source": self.source, "constant": self.constant}


def validate_columns(definitions):
    columns = tuple(c if isinstance(c, ColumnDefinition) else ColumnDefinition(**c)
                    for c in definitions)
    if not 1 <= len(columns) <= 4:
        raise ValueError("one to four column rules required")
    if len({c.column_id for c in columns}) != len(columns):
        raise ValueError("duplicate column rule")
    for c in columns:
        identifier(c.column_id)
        if (c.source is None) == (c.constant is None):
            raise ValueError("exactly one source or constant required")
        if c.source is not None:
            identifier(c.source)
        elif type(c.constant) is not int or abs(c.constant) > 8:
            raise ValueError("invalid constant coordinate")
    return tuple(sorted(columns, key=lambda c: c.column_id))


def evaluate_column(column, observation):
    if column.source is None:
        return column.constant
    values = dict(observation.values)
    if column.source not in values:
        raise ValueError("missing design input: " + column.source)
    coordinate = values[column.source]
    if type(coordinate) is not int or abs(coordinate) > 8:
        raise ValueError("invalid design input")
    return coordinate
