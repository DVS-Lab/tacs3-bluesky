"""Small shared parsers. Unknown flags stay unknown (including sentinel 999)."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def number(value):
    try:
        n = float(value)
        return n if np.isfinite(n) else np.nan
    except (TypeError, ValueError):
        return np.nan


def flag(value):
    s = str(value).strip().lower()
    if s in {"true", "1", "1.0"}:
        return True
    if s in {"false", "0", "0.0"}:
        return False
    return None


def flags(series):
    return series.map(flag)


def numeric(frame, column):
    return pd.to_numeric(frame.get(column, pd.Series(index=frame.index, dtype=float)), errors="coerce")


def column(frame, name, default=""):
    return frame[name] if name in frame else pd.Series(default, index=frame.index)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, default=str, allow_nan=False) + "\n")


def write_csv(frame, path):
    # Preserve Unix timestamps and submillisecond residuals on CSV round trips.
    frame.to_csv(path, index=False, float_format="%.17g")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else np.nan


def median(series):
    valid = series.dropna()
    return valid.median() if len(valid) else np.nan
