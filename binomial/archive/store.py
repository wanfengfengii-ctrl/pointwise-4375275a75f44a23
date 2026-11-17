import sqlite3
from contextlib import contextmanager

from binomial.archive.schema import (
    SCHEMA_VERSION, ArchiveFormatError, RequestConflict, content_digest,
    decode_value, encode_value, identifier, validate_envelope,
)


class ArchiveStore:
    def __init__(self, path=":memory:"):
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._active = False
        self._fail_write = None
        self._fail_commit = False
        try:
            self._initialize()
        except BaseException:
            self.connection.close()
            raise

    @classmethod
    def open(cls, path=":memory:"):
        return cls(path)

    def _initialize(self):
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if version == 0 and not tables:
            self.connection.executescript(
                "BEGIN; CREATE TABLE records("
                "id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL);"
                "CREATE TABLE receipts(scope TEXT, request TEXT, fingerprint TEXT NOT NULL,"
                "result TEXT NOT NULL, PRIMARY KEY(scope,request));"
                "CREATE TABLE currents(cohort TEXT PRIMARY KEY, revision TEXT NOT NULL);"
                "PRAGMA user_version=1; COMMIT;")
        elif version != SCHEMA_VERSION or tables != {"records", "receipts", "currents"}:
            raise ArchiveFormatError("unsupported archive schema")
        expected = {
            "records": ["id", "kind", "body"],
            "receipts": ["scope", "request", "fingerprint", "result"],
            "currents": ["cohort", "revision"],
        }
        for table, names in expected.items():
            actual = [r[1] for r in self.connection.execute("PRAGMA table_info(" + table + ")")]
            if actual != names:
                raise ArchiveFormatError("invalid archive table")

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def arm_failure(self, write_number=None, before_commit=False):
        if write_number is not None and (type(write_number) is not int or write_number < 1):
            raise ValueError("write_number must be positive")
        self._fail_write = write_number
        self._fail_commit = bool(before_commit)

    def _written(self):
        if not self._active:
            raise RuntimeError("write outside transaction")
        if self._fail_write is not None:
            self._fail_write -= 1
            if self._fail_write == 0:
                self._fail_write = None
                raise sqlite3.OperationalError("injected persistence failure")

    @contextmanager
    def transaction(self):
        if self._active:
            raise RuntimeError("nested transaction")
        self.connection.execute("BEGIN IMMEDIATE")
        self._active = True
        try:
            yield self
            if self._fail_commit:
                self._fail_commit = False
                raise sqlite3.OperationalError("injected commit failure")
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        finally:
            self._active = False

    def get_record(self, record_id, kind=None):
        identifier(record_id)
        row = self.connection.execute(
            "SELECT kind,body FROM records WHERE id=?", (record_id,)).fetchone()
        if row is None:
            return None
        value = decode_value(row[1])
        payload = validate_envelope(value, kind or row[0], record_id)
        if value["kind"] != row[0]:
            raise ArchiveFormatError("record index mismatch")
        return payload

    def put_record(self, record_id, kind, payload):
        if not self._active:
            raise RuntimeError("write outside transaction")
        identifier(record_id)
        identifier(kind)
        envelope = {"version": SCHEMA_VERSION, "id": record_id, "kind": kind,
                    "payload": payload, "digest": content_digest(payload)}
        encoded = encode_value(envelope)
        old = self.connection.execute("SELECT body FROM records WHERE id=?", (record_id,)).fetchone()
        if old is not None:
            if old[0] != encoded:
                raise ArchiveFormatError("immutable record conflict")
            return
        self.connection.execute("INSERT INTO records VALUES(?,?,?)", (record_id, kind, encoded))
        self._written()

    def get_receipt(self, scope, request_id, fingerprint=None):
        identifier(request_id)
        row = self.connection.execute(
            "SELECT fingerprint,result FROM receipts WHERE scope=? AND request=?",
            (scope, request_id)).fetchone()
        if row is None:
            return None
        if fingerprint is not None and row[0] != fingerprint:
            raise RequestConflict("request content conflict")
        return decode_value(row[1])

    def put_receipt(self, scope, request_id, fingerprint, result):
        if not self._active:
            raise RuntimeError("write outside transaction")
        old = self.get_receipt(scope, request_id, fingerprint)
        if old is not None:
            if old != decode_value(encode_value(result)):
                raise ArchiveFormatError("receipt result conflict")
            return
        self.connection.execute("INSERT INTO receipts VALUES(?,?,?,?)",
                                (scope, request_id, fingerprint, encode_value(result)))
        self._written()

    def current_revision(self, cohort_id):
        identifier(cohort_id)
        row = self.connection.execute("SELECT revision FROM currents WHERE cohort=?", (cohort_id,)).fetchone()
        return None if row is None else row[0]

    def set_current(self, cohort_id, revision_id):
        if not self._active:
            raise RuntimeError("write outside transaction")
        self.connection.execute(
            "INSERT INTO currents VALUES(?,?) ON CONFLICT(cohort) DO UPDATE SET revision=excluded.revision",
            (cohort_id, revision_id))
        self._written()
