import json
import math
import tempfile
from pathlib import Path
from binomial.archive.store import ArchiveStore
from binomial.archive.schema import encode_value
from binomial.archive.fit_records import read_result
from binomial.cohort.batches import apply_cohort
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design
from binomial.fitting.service import fit, fit_null
from binomial.reporting.service import report, compare_null
from samples import boundary_rows, finite_rows, boundary_effects


def main():
    with tempfile.TemporaryDirectory(prefix="binomial-demo-") as directory:
        path = Path(directory) / "study.sqlite"
        with ArchiveStore(path) as store:
            r = apply_cohort(store, "boundary", "input", boundary_rows())
            register_design(store, "uv", ["u", "v"], [
                ColumnDefinition("u", source="u"), ColumnDefinition("v", source="v")])
            boundary_fit = fit(store, "boundary", ("boundary", r.revision_id), "uv")
            boundary_report = report(store, "boundary", boundary_fit, boundary_effects())
            null_id = fit_null(store, "null-restore", boundary_fit,
                               [{"coefficients": {"u": 1}, "rhs": 0}])
            comparison_id = compare_null(store, "comparison-restore", null_id)
            apply_cohort(store, "boundary", "correction", [
                {"row_id": "a", "values": {"u": 1, "v": 0}, "n": 4, "k": 2}])
            initial = apply_cohort(store, "finite", "input", finite_rows())
            register_design(store, "x", ["x"], [ColumnDefinition("x", source="x")])
            old_fit = fit(store, "old", ("finite", initial.revision_id), "x")
            old_report = report(store, "old", old_fit, [{"name": "x", "coefficients": {"x": 1}}])
            old_values = (read_result(store, old_fit), read_result(store, old_report))
            corrected = apply_cohort(store, "finite", "correction", finite_rows(3))
            new_fit = fit(store, "new", ("finite", corrected.revision_id), "x")
            new_report = report(store, "new", new_fit, [{"name": "x", "coefficients": {"x": 1}}])
        with ArchiveStore(path) as store:
            assert (read_result(store, old_fit), read_result(store, old_report)) == old_values
            probabilities = read_result(store, boundary_fit)["probabilities"]
            items = read_result(store, boundary_report)["items"]
            assert probabilities == [1, 0.5, 0.5]
            assert [item["status"] for item in items] == ["not_estimable", "estimable", "estimable"]
            assert items[1]["variance"] == 1
            updated = read_result(store, new_report)["items"][0]
            assert abs(updated["estimate"] - math.log(3)) <= 1e-8
            assert abs(updated["variance"] - 4 / 3) <= 1e-8
            null_value = read_result(store, null_id)
            comparison = read_result(store, comparison_id)
            assert null_value["probabilities"] == [0.5, 0.5, 0.5]
            assert null_value["boundary"] == [None, None, None]
            assert abs(null_value["log_likelihood"] + 5 * math.log(2)) <= 1e-8
            assert abs(comparison["statistic"] - 2 * math.log(2)) <= 1e-8
            fresh = read_result(store, compare_null(store, "comparison-after", null_id))
            assert fresh["original_log_likelihood"] == comparison["original_log_likelihood"]
            assert fresh["null_log_likelihood"] == comparison["null_log_likelihood"]
            assert fresh["statistic"] == comparison["statistic"]
            output = {
                "boundary": {"probabilities": probabilities, "effects": items},
                "after_reopen": {
                    "old_probability": read_result(store, old_fit)["probabilities"][0],
                    "new_probability": read_result(store, new_fit)["probabilities"][0],
                    "old_effect": old_values[1]["items"][0], "new_effect": updated,
                    "old_binding_preserved": read_result(store, old_report)["fit_id"] == old_fit},
                "null": {
                    "probabilities": null_value["probabilities"],
                    "boundary_restored": null_value["boundary"] == [None, None, None],
                    "null_log_likelihood": comparison["null_log_likelihood"],
                    "original_log_likelihood": comparison["original_log_likelihood"],
                    "statistic": comparison["statistic"],
                    "statistic_after_correction": fresh["statistic"]}}
            print(encode_value(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
