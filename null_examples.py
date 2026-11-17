"""Fixed public examples for the affine-null extension; no V2 implementation."""
import math
from copy import deepcopy
from binomial.archive.store import ArchiveStore
from binomial.archive.schema import encode_value
from binomial.archive.fit_records import read_result
from binomial.cohort.batches import apply_cohort
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design
from binomial.fitting.service import fit
from samples import boundary_rows


def cases():
    half = math.log(2)
    sigmoid_one = 1 / (1 + math.exp(-1))
    common = {
        "columns": ["u", "v"],
        "rows": boundary_rows(),
        "original_probabilities": [1, 0.5, 0.5],
    }
    definitions = [
        ("restore_boundary", [{"coefficients": {"u": 1}, "rhs": 0}],
         [0.5, 0.5, 0.5], [None, None, None], -5 * half, 2 * half),
        ("nonzero_rhs", [{"coefficients": {"u": 1}, "rhs": 1}],
         [sigmoid_one, 0.5, 0.5], [None, None, None],
         -4 * half - math.log1p(math.exp(-1)), 2 * math.log1p(math.exp(-1))),
        ("coupled", [{"coefficients": {"u": 1, "v": 1}, "rhs": 1}],
         [0.7733951063913902, 0.44334877659784755, 0.5566512234021525],
         [None, None, None], -3.055395062476727, 0.5656126804738916),
        ("still_separated", [{"coefficients": {"v": 1}, "rhs": 1}],
         [1, sigmoid_one, 1 - sigmoid_one], [1, None, None],
         -3.2530467500728913, 0.9609160556662202),
        ("empty", [], [1, 0.5, 0.5], [1, None, None], -4 * half, 0),
    ]
    result = [
        {**common, "name": name, "rows": boundary_rows(), "equations": equations,
         "null_probabilities": probabilities, "null_boundary": boundary,
         "null_log_likelihood": likelihood, "statistic": statistic}
        for name, equations, probabilities, boundary, likelihood, statistic in definitions
    ]
    transformed = {
        **result[2], "name": "coupled_transformed", "columns": ["s", "t"],
        "rows": [
            {"row_id": "a", "values": {"s": 1, "t": 2}, "n": 1, "k": 1},
            {"row_id": "b", "values": {"s": 0, "t": 1}, "n": 2, "k": 1},
            {"row_id": "c", "values": {"s": 0, "t": -1}, "n": 2, "k": 1}],
        "equations": [{"coefficients": {"s": 1, "t": 3}, "rhs": 1}]}
    result.append(transformed)
    result.append({
        "name": "unidentified_difference", "columns": ["u", "v"],
        "rows": [{"row_id": "a", "values": {"u": 1, "v": 1}, "n": 4, "k": 3}],
        "equations": [{"coefficients": {"u": 1, "v": -1}, "rhs": 1}],
        "original_probabilities": [0.75], "null_probabilities": [0.75],
        "null_boundary": [None], "null_log_likelihood": 3 * math.log(0.75) + math.log(0.25),
        "statistic": 0})
    return [deepcopy(case) for case in result]


def prepare_original(store, case, tag):
    receipt = apply_cohort(store, tag, "input", case["rows"])
    columns = case["columns"]
    register_design(store, tag, columns, [ColumnDefinition(c, source=c) for c in columns])
    return fit(store, "fit-" + tag, (tag, receipt.revision_id), tag)


def verify_v1_examples():
    output = []
    with ArchiveStore() as store:
        for case in cases():
            fit_id = prepare_original(store, case, case["name"])
            original = read_result(store, fit_id)
            assert len(original["probabilities"]) == len(case["original_probabilities"])
            for actual, expected in zip(original["probabilities"], case["original_probabilities"]):
                assert abs(actual - expected) <= 1e-8
            expected_ll = 0.0
            rows = sorted(case["rows"], key=lambda row: row["row_id"])
            for row, p in zip(rows, case["null_probabilities"]):
                if row["k"]:
                    expected_ll += row["k"] * math.log(p)
                if row["n"] != row["k"]:
                    expected_ll += (row["n"] - row["k"]) * math.log1p(-p)
            assert abs(expected_ll - case["null_log_likelihood"]) <= 1e-12
            assert abs(2 * (original["diagnostics"]["log_likelihood"] - expected_ll)
                       - case["statistic"]) <= 1e-12
            output.append({
                "name": case["name"], "original_probabilities": original["probabilities"],
                "equations": case["equations"],
                "expected_null_probabilities": case["null_probabilities"],
                "expected_statistic": case["statistic"]})
    return output


if __name__ == "__main__":
    print(encode_value({"v1_examples": verify_v1_examples()}))
