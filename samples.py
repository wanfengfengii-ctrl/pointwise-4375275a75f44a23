def boundary_rows():
    return [
        {"row_id": "a", "values": {"u": 1, "v": 0}, "n": 1, "k": 1},
        {"row_id": "b", "values": {"u": 0, "v": 1}, "n": 2, "k": 1},
        {"row_id": "c", "values": {"u": 0, "v": -1}, "n": 2, "k": 1},
    ]


def finite_rows(successes=2):
    return [{"row_id": "r", "values": {"x": 1}, "n": 4, "k": successes}]


def boundary_effects():
    return [
        {"name": "first", "coefficients": {"u": 1}},
        {"name": "second", "coefficients": {"v": 1}},
        {"name": "zero", "coefficients": {}},
    ]
