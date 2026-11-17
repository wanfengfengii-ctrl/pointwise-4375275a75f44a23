from dataclasses import dataclass
from fractions import Fraction


def solve_exact(matrix, rhs, width=None):
    rows = [list(map(Fraction, row)) for row in matrix]
    width = len(rows[0]) if width is None and rows else (width or 0)
    if len(rhs) != len(rows) or any(len(row) != width for row in rows):
        raise ValueError("exact system dimension mismatch")
    a = [row + [Fraction(b)] for row, b in zip(rows, rhs)]
    pivots = []
    current = 0
    for col in range(width):
        pivot = next((i for i in range(current, len(a)) if a[i][col]), None)
        if pivot is None:
            continue
        a[current], a[pivot] = a[pivot], a[current]
        scale = a[current][col]
        a[current] = [v / scale for v in a[current]]
        for i in range(len(a)):
            if i != current and a[i][col]:
                scale = a[i][col]
                a[i] = [u - scale * v for u, v in zip(a[i], a[current])]
        pivots.append(col)
        current += 1
        if current == len(a):
            break
    if any(not any(row[:width]) and row[width] for row in a):
        return None
    answer = [Fraction() for _ in range(width)]
    for i, col in enumerate(pivots):
        answer[col] = a[i][width]
    return tuple(answer)


@dataclass(frozen=True)
class ExactRowSpace:
    basis: tuple
    width: int

    def coordinates(self, vector):
        v = tuple(map(Fraction, vector))
        if len(v) != self.width:
            raise ValueError("space dimension mismatch")
        matrix = [tuple(row[j] for row in self.basis) for j in range(self.width)]
        return solve_exact(matrix, v, len(self.basis))


def row_space(rows, width=None):
    rows = tuple(tuple(map(Fraction, r)) for r in rows)
    width = len(rows[0]) if width is None and rows else (width or 0)
    if any(len(r) != width for r in rows):
        raise ValueError("ragged exact matrix")
    basis = []
    for row in rows:
        if ExactRowSpace(tuple(basis), width).coordinates(row) is None:
            basis.append(row)
    return ExactRowSpace(tuple(basis), width)


def independent_constraints(matrix, rhs):
    space = row_space(matrix)
    kept, values = [], []
    for row, value in zip(matrix, rhs):
        coordinates = row_space(kept, space.width).coordinates(row)
        if coordinates is None:
            kept.append(tuple(map(Fraction, row)))
            values.append(Fraction(value))
        elif sum((w * b for w, b in zip(coordinates, values)), Fraction()) != value:
            raise ValueError("inconsistent constraints")
    return tuple(kept), tuple(values)
