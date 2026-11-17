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
from binomial.fitting.service import fit
from binomial.reporting.service import report
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
            output = {
                "boundary": {"probabilities": probabilities, "effects": items},
                "after_reopen": {
                    "old_probability": read_result(store, old_fit)["probabilities"][0],
                    "new_probability": read_result(store, new_fit)["probabilities"][0],
                    "old_effect": old_values[1]["items"][0], "new_effect": updated,
                    "old_binding_preserved": read_result(store, old_report)["fit_id"] == old_fit}}
            print(encode_value(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
