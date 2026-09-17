import pandas as pd
import pytest

from src.data_audit.akshare_etf_quality import (
    classify_request_outcome,
    compare_adjustments,
    infer_volume_amount_units,
    normalize_code,
    validate_history,
)


def sample_frame(multiplier: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2026-08-03", "2026-08-04"],
            "开盘": [4.0 * multiplier, 4.1 * multiplier],
            "收盘": [4.1 * multiplier, 4.2 * multiplier],
            "最高": [4.2 * multiplier, 4.3 * multiplier],
            "最低": [3.9 * multiplier, 4.0 * multiplier],
            "成交量": [1000, 2000],
            "成交额": [405000, 830000],
            "涨跌幅": [2.5, 2.44],
            "涨跌额": [0.1 * multiplier, 0.1 * multiplier],
            "换手率": [1.0, 2.0],
        }
    )


def test_normalize_code_preserves_exchange() -> None:
    normalized = normalize_code("510300.SH", "SSE")
    assert normalized.canonical_code == "510300.SH"
    assert normalized.akshare_symbol == "510300"
    assert normalized.exchange == "SSE"


def test_normalize_code_rejects_exchange_conflict() -> None:
    with pytest.raises(ValueError):
        normalize_code("510300.SH", "SZSE")


def test_duplicate_and_ohlc_detection() -> None:
    frame = sample_frame()
    frame.loc[1, "日期"] = frame.loc[0, "日期"]
    frame.loc[1, "最低"] = 4.25
    result = validate_history(frame)
    assert result["duplicate_dates"] == 2
    assert result["invalid_ohlc_rows"] == 1


def test_percent_change_uses_implicit_previous_close() -> None:
    result = validate_history(sample_frame())
    assert result["pct_check_eligible_rows"] == 2
    assert result["pct_inconsistent_rows_0_02pp"] == 0


def test_volume_unit_inference_prefers_lots_and_yuan() -> None:
    result = infer_volume_amount_units(sample_frame())
    assert result["best_unit"] == "volume=lot,amount=yuan"
    assert result["scores"]["volume=lot,amount=yuan"] == 1.0


def test_adjustment_comparison() -> None:
    raw = sample_frame()
    qfq = sample_frame(0.5)
    hfq = sample_frame(2.0)
    result = compare_adjustments(raw, qfq, hfq)
    assert result["date_sets_equal"] is True
    assert result["成交量_unequal_rows"] == 0
    assert result["成交额_unequal_rows"] == 0
    assert result["qfq_ratio_inconsistent_rows_0_1pct"] == 0
    assert result["hfq_positive_ratio_rows"] == 2


def test_empty_is_not_request_failure() -> None:
    empty = pd.DataFrame(columns=["日期"])
    result = validate_history(empty)
    assert result["row_count"] == 0
    assert result["first_date"] is None
    assert classify_request_outcome(empty) == "empty"
    assert classify_request_outcome(None, ConnectionError("closed")) == "request_failed"
