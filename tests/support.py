import unittest
from binomial.archive.store import ArchiveStore
from binomial.cohort.batches import apply_cohort
from binomial.design.columns import ColumnDefinition
from binomial.design.specification import register_design
from binomial.fitting.service import fit
from binomial.reporting.service import report
from binomial.archive.fit_records import read_result


def observation(row_id, x, n, k):
    return {"row_id": row_id, "values": dict(x), "n": n, "k": k}


def effect(name, **coefficients):
    return {"name": name, "coefficients": coefficients}


def setup_analysis(store, rows, columns, cohort="study", design="design", request="input"):
    receipt = apply_cohort(store, cohort, request, rows)
    register_design(store, design, columns, [ColumnDefinition(c, source=c) for c in columns])
    fit_id = fit(store, "fit-" + request, (cohort, receipt.revision_id), design)
    return receipt, fit_id


class MemoryCase(unittest.TestCase):
    def setUp(self):
        self.store = ArchiveStore()

    def tearDown(self):
        self.store.close()

    def analyze(self, rows, columns, **kwargs):
        return setup_analysis(self.store, rows, columns, **kwargs)

    def results(self, fit_id, effects, request="effects"):
        report_id = report(self.store, request, fit_id, effects)
        return read_result(self.store, report_id)["items"]

    def count(self, table):
        if table not in {"records", "receipts", "currents"}:
            raise ValueError("unknown test table")
        return self.store.connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
