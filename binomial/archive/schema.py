import hashlib
import json
import math
from fractions import Fraction

SCHEMA_VERSION = 1


class ArchiveFormatError(ValueError):
    pass


class ResultNotFound(LookupError):
    pass


class RequestConflict(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("identity must be a nonempty string of at most 128 characters")
    return value


def _pack(value):
    if isinstance(value, Fraction):
        return {"$rational": [value.numerator, value.denominator]}
    if isinstance(value, float) and not math.isfinite(value):
        raise ArchiveFormatError("nonfinite number")
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ArchiveFormatError("object keys must be strings")
        if "$rational" in value:
            raise ArchiveFormatError("reserved object key")
        return {k: _pack(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_pack(v) for v in value]
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ArchiveFormatError("unsupported value")


def _unpack(value):
    if isinstance(value, list):
        return [_unpack(v) for v in value]
    if isinstance(value, dict):
        if "$rational" in value:
            pair = value["$rational"]
            if (set(value) != {"$rational"} or not isinstance(pair, list)
                    or len(pair) != 2 or any(type(x) is not int for x in pair)
                    or pair[1] <= 0):
                raise ArchiveFormatError("invalid rational")
            result = Fraction(*pair)
            if [result.numerator, result.denominator] != pair:
                raise ArchiveFormatError("noncanonical rational")
            return result
        return {k: _unpack(v) for k, v in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        raise ArchiveFormatError("nonfinite number")
    return value


def encode_value(value):
    return json.dumps(_pack(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_value(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ArchiveFormatError("duplicate JSON key")
            result[key] = value
        return result
    try:
        return _unpack(json.loads(text, object_pairs_hook=pairs))
    except (ValueError, TypeError, OverflowError) as exc:
        raise ArchiveFormatError("invalid archive encoding") from exc


def content_digest(value):
    return hashlib.sha256(encode_value(value).encode("utf-8")).hexdigest()


def validate_envelope(value, kind=None, record_id=None):
    if (not isinstance(value, dict)
            or set(value) != {"version", "kind", "id", "payload", "digest"}
            or type(value["version"]) is not int or value["version"] != SCHEMA_VERSION
            or not isinstance(value["payload"], dict)):
        raise ArchiveFormatError("invalid record envelope")
    identifier(value["id"])
    identifier(value["kind"])
    if kind is not None and value["kind"] != kind:
        raise ArchiveFormatError("record kind mismatch")
    if record_id is not None and value["id"] != record_id:
        raise ArchiveFormatError("record identity mismatch")
    if content_digest(value["payload"]) != value["digest"]:
        raise ArchiveFormatError("record digest mismatch")
    return value["payload"]
