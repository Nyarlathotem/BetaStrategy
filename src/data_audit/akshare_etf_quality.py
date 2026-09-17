"""Pure validation helpers for the AKShare ETF EOD audit.

This module performs no network access.  It can be run repeatedly against
cached CSV files so request failures never become data-quality failures.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


DATE_COLUMN = "日期"
PRICE_COLUMNS = ("开盘", "收盘", "最高", "最低")
FLOW_COLUMNS = ("成交量", "成交额")
OPTIONAL_COLUMNS = ("涨跌幅", "涨跌额", "换手率")
EXPECTED_COLUMNS = (DATE_COLUMN, *PRICE_COLUMNS, *FLOW_COLUMNS, *OPTIONAL_COLUMNS)
EXCHANGE_SUFFIX = {
    "SSE": "SH",
    "SH": "SH",
    "XSHG": "SH",
    "SZSE": "SZ",
    "SZ": "SZ",
    "XSHE": "SZ",
}


@dataclass(frozen=True)
class NormalizedCode:
    canonical_code: str
    akshare_symbol: str
    exchange: str


def normalize_code(code: str, exchange: str | None = None) -> NormalizedCode:
    """Preserve the canonical exchange suffix and derive AKShare's 6 digits."""

    value = str(code).strip().upper()
    match = re.fullmatch(r"(?P<digits>\d{6})(?:\.(?P<suffix>SH|SZ))?", value)
    if not match:
        raise ValueError(f"unsupported ETF code: {code!r}")
    digits = match.group("digits")
    suffix = match.group("suffix")
    exchange_key = str(exchange).strip().upper() if exchange is not None else ""
    exchange_suffix = EXCHANGE_SUFFIX.get(exchange_key)
    if suffix and exchange_suffix and suffix != exchange_suffix:
        raise ValueError(
            f"code suffix {suffix} conflicts with exchange {exchange!r}"
        )
    suffix = suffix or exchange_suffix
    if not suffix:
        raise ValueError("exchange is required when canonical suffix is absent")
    canonical = f"{digits}.{suffix}"
    return NormalizedCode(canonical, digits, "SSE" if suffix == "SH" else "SZSE")


def dataframe_sha256(frame: pd.DataFrame) -> str:
    """Return a stable content hash including column order and row order."""

    payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def classify_request_outcome(
    frame: pd.DataFrame | None, error: BaseException | None = None
) -> str:
    """Keep transport failure, successful empty response and data separate."""

    if error is not None:
        return "request_failed"
    if frame is None:
        raise ValueError("frame cannot be None when no request error is supplied")
    return "empty" if frame.empty else "success"


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def infer_volume_amount_units(frame: pd.DataFrame) -> dict[str, Any]:
    """Score plausible volume/amount unit pairs against the daily price range."""

    required = {"成交量", "成交额", "最低", "最高"}
    if not required.issubset(frame.columns):
        return {"best_unit": None, "eligible_rows": 0, "scores": {}}
    work = _numeric(frame, tuple(required))
    eligible = work[
        (work["成交量"] > 0)
        & (work["成交额"] > 0)
        & (work["最低"] > 0)
        & (work["最高"] >= work["最低"])
    ].copy()
    if eligible.empty:
        return {"best_unit": None, "eligible_rows": 0, "scores": {}}
    candidates = {
        "volume=share,amount=yuan": 1.0,
        "volume=lot,amount=yuan": 100.0,
        "volume=share,amount=thousand_yuan": 0.001,
        "volume=lot,amount=thousand_yuan": 0.1,
    }
    scores: dict[str, float] = {}
    medians: dict[str, float] = {}
    for name, denominator_multiplier in candidates.items():
        average_price = eligible["成交额"] / (
            eligible["成交量"] * denominator_multiplier
        )
        inside = (average_price >= eligible["最低"] * 0.98) & (
            average_price <= eligible["最高"] * 1.02
        )
        scores[name] = float(inside.mean())
        medians[name] = float(average_price.median())
    best = max(scores, key=scores.get)
    return {
        "best_unit": best,
        "eligible_rows": int(len(eligible)),
        "scores": scores,
        "median_implied_prices": medians,
    }


def validate_history(frame: pd.DataFrame) -> dict[str, Any]:
    """Validate keys, dates, fields, OHLC, flows, percent change and extremes."""

    result: dict[str, Any] = {
        "row_count": int(len(frame)),
        "columns": list(frame.columns),
        "missing_required_columns": [
            column for column in EXPECTED_COLUMNS if column not in frame.columns
        ],
    }
    if frame.empty:
        result.update(
            {
                "first_date": None,
                "last_date": None,
                "duplicate_dates": 0,
                "invalid_dates": 0,
                "weekend_rows": 0,
                "sorted_ascending": True,
            }
        )
        return result

    work = _numeric(frame, (*PRICE_COLUMNS, *FLOW_COLUMNS, *OPTIONAL_COLUMNS))
    dates = pd.to_datetime(work.get(DATE_COLUMN), errors="coerce")
    valid_dates = dates.dropna()
    result["first_date"] = (
        valid_dates.min().strftime("%Y-%m-%d") if not valid_dates.empty else None
    )
    result["last_date"] = (
        valid_dates.max().strftime("%Y-%m-%d") if not valid_dates.empty else None
    )
    result["invalid_dates"] = int(dates.isna().sum())
    result["duplicate_dates"] = int(dates.duplicated(keep=False).sum())
    result["weekend_rows"] = int((dates.dt.dayofweek >= 5).fillna(False).sum())
    result["sorted_ascending"] = bool(valid_dates.is_monotonic_increasing)

    non_null_counts: dict[str, int] = {}
    non_null_rates: dict[str, float] = {}
    for column in (*PRICE_COLUMNS, *FLOW_COLUMNS, *OPTIONAL_COLUMNS):
        if column in work.columns:
            count = int(work[column].notna().sum())
            non_null_counts[column] = count
            non_null_rates[column] = count / len(work)
        else:
            non_null_counts[column] = 0
            non_null_rates[column] = 0.0
    result["nonnull_counts"] = non_null_counts
    result["nonnull_rates"] = non_null_rates

    if set(PRICE_COLUMNS).issubset(work.columns):
        price_positive = (work[list(PRICE_COLUMNS)] > 0).all(axis=1)
        ohlc_order = (
            (work["最低"] <= work["开盘"])
            & (work["开盘"] <= work["最高"])
            & (work["最低"] <= work["收盘"])
            & (work["收盘"] <= work["最高"])
        )
        result["nonpositive_price_rows"] = int((~price_positive).sum())
        result["invalid_ohlc_rows"] = int((~ohlc_order).sum())
    else:
        result["nonpositive_price_rows"] = None
        result["invalid_ohlc_rows"] = None

    for column in FLOW_COLUMNS:
        result[f"negative_{column}_rows"] = (
            int((work[column] < 0).sum()) if column in work.columns else None
        )
    if set(FLOW_COLUMNS).issubset(work.columns):
        result["zero_volume_with_price_rows"] = int(
            ((work["成交量"] == 0) & (work.get("收盘", 0) > 0)).sum()
        )
        result["zero_amount_with_volume_rows"] = int(
            ((work["成交额"] == 0) & (work["成交量"] > 0)).sum()
        )

    if {"收盘", "涨跌额", "涨跌幅"}.issubset(work.columns):
        implied_previous = work["收盘"] - work["涨跌额"]
        implied_pct = np.where(
            implied_previous > 0,
            work["涨跌额"] / implied_previous * 100,
            np.nan,
        )
        pct_diff = np.abs(implied_pct - work["涨跌幅"])
        eligible = pd.Series(implied_pct, index=work.index).notna() & work["涨跌幅"].notna()
        result["pct_check_eligible_rows"] = int(eligible.sum())
        result["pct_inconsistent_rows_0_02pp"] = int(
            (eligible & (pct_diff > 0.02)).sum()
        )
        result["pct_max_abs_diff_pp"] = (
            float(np.nanmax(pct_diff)) if eligible.any() else None
        )

    extreme_rows = pd.Series(False, index=work.index)
    for column in (*PRICE_COLUMNS, *FLOW_COLUMNS):
        if column not in work.columns:
            continue
        positive = work.loc[work[column] > 0, column]
        if positive.empty:
            continue
        median = float(positive.median())
        if median > 0:
            extreme_rows |= (work[column] > median * 1000) | (
                (work[column] > 0) & (work[column] < median / 1000)
            )
    result["extreme_rows_1000x_median"] = int(extreme_rows.sum())
    result["unit_inference"] = infer_volume_amount_units(work)
    return result


def collect_anomalies(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a compact row-level anomaly sample without changing source values."""

    if frame.empty or DATE_COLUMN not in frame.columns:
        return pd.DataFrame(columns=[DATE_COLUMN, "anomaly"])
    work = _numeric(frame, (*PRICE_COLUMNS, *FLOW_COLUMNS, *OPTIONAL_COLUMNS))
    reasons: list[list[str]] = [[] for _ in range(len(work))]
    if set(PRICE_COLUMNS).issubset(work.columns):
        conditions = {
            "nonpositive_price": ~(work[list(PRICE_COLUMNS)] > 0).all(axis=1),
            "invalid_ohlc": ~(
                (work["最低"] <= work["开盘"])
                & (work["开盘"] <= work["最高"])
                & (work["最低"] <= work["收盘"])
                & (work["收盘"] <= work["最高"])
            ),
        }
        for label, condition in conditions.items():
            for position in np.flatnonzero(condition.to_numpy()):
                reasons[position].append(label)
    if "成交量" in work.columns:
        for position in np.flatnonzero((work["成交量"] < 0).to_numpy()):
            reasons[position].append("negative_volume")
    if "成交额" in work.columns:
        for position in np.flatnonzero((work["成交额"] < 0).to_numpy()):
            reasons[position].append("negative_amount")
    output = work.copy()
    output["anomaly"] = ["|".join(value) for value in reasons]
    return output[output["anomaly"] != ""].copy()


def compare_adjustments(
    raw: pd.DataFrame, qfq: pd.DataFrame, hfq: pd.DataFrame
) -> dict[str, Any]:
    """Compare date/flow equality and implicit OHLC adjustment ratios."""

    frames = {"raw": raw.copy(), "qfq": qfq.copy(), "hfq": hfq.copy()}
    date_sets: dict[str, set[str]] = {}
    for name, frame in frames.items():
        frame[DATE_COLUMN] = pd.to_datetime(frame[DATE_COLUMN], errors="coerce")
        date_sets[name] = set(frame[DATE_COLUMN].dropna().dt.strftime("%Y-%m-%d"))
        frames[name] = _numeric(frame, (*PRICE_COLUMNS, *FLOW_COLUMNS))
    result: dict[str, Any] = {
        "date_sets_equal": date_sets["raw"] == date_sets["qfq"] == date_sets["hfq"],
        "raw_only_vs_qfq": len(date_sets["raw"] - date_sets["qfq"]),
        "qfq_only_vs_raw": len(date_sets["qfq"] - date_sets["raw"]),
        "raw_only_vs_hfq": len(date_sets["raw"] - date_sets["hfq"]),
        "hfq_only_vs_raw": len(date_sets["hfq"] - date_sets["raw"]),
    }
    joined = frames["raw"].merge(
        frames["qfq"], on=DATE_COLUMN, suffixes=("_raw", "_qfq"), how="inner"
    ).merge(frames["hfq"], on=DATE_COLUMN, how="inner")
    rename = {
        column: f"{column}_hfq"
        for column in (*PRICE_COLUMNS, *FLOW_COLUMNS)
        if column in joined.columns
    }
    joined = joined.rename(columns=rename)
    result["joined_rows"] = int(len(joined))
    for flow in FLOW_COLUMNS:
        columns = [f"{flow}_raw", f"{flow}_qfq", f"{flow}_hfq"]
        if set(columns).issubset(joined.columns):
            same = np.isclose(joined[columns[0]], joined[columns[1]], equal_nan=True) & np.isclose(
                joined[columns[0]], joined[columns[2]], equal_nan=True
            )
            result[f"{flow}_equal_rows"] = int(same.sum())
            result[f"{flow}_unequal_rows"] = int((~same).sum())
    for mode in ("qfq", "hfq"):
        ratio_columns: list[str] = []
        for price in PRICE_COLUMNS:
            raw_column = f"{price}_raw"
            adjusted_column = f"{price}_{mode}"
            if {raw_column, adjusted_column}.issubset(joined.columns):
                ratio_column = f"ratio_{mode}_{price}"
                joined[ratio_column] = joined[adjusted_column] / joined[raw_column]
                ratio_columns.append(ratio_column)
        ratios = joined[ratio_columns].replace([np.inf, -np.inf], np.nan)
        positive = (ratios > 0).all(axis=1)
        spread = (ratios.max(axis=1) - ratios.min(axis=1)) / ratios.median(axis=1)
        close_ratio = joined.get(f"ratio_{mode}_收盘", pd.Series(dtype=float))
        transitions = close_ratio.pct_change().abs() > 0.001
        result[f"{mode}_positive_ratio_rows"] = int(positive.sum())
        result[f"{mode}_ratio_inconsistent_rows_0_1pct"] = int((spread > 0.001).sum())
        result[f"{mode}_factor_transition_rows_0_1pct"] = int(transitions.sum())
        result[f"{mode}_ratio_min"] = float(ratios.min().min()) if not ratios.empty else None
        result[f"{mode}_ratio_max"] = float(ratios.max().max()) if not ratios.empty else None
    return result


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
