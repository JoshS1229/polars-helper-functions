import pytest

import polars_helper_functions.helpers as helpers
from polars_helper_functions import timer_end, timer_start


def test_timer_with_description(monkeypatch, capsys):
    readings = iter([100.0, 112.432])
    monkeypatch.setattr(helpers.time, "perf_counter", lambda: next(readings))

    start = timer_start("Merge FMIS")
    elapsed = timer_end(start)

    assert elapsed == pytest.approx(12.432)
    assert capsys.readouterr().out == "Merged FMIS Elapsed Time: 12.43 seconds\n"


def test_timer_without_description(monkeypatch, capsys):
    readings = iter([20.0, 21.25])
    monkeypatch.setattr(helpers.time, "perf_counter", lambda: next(readings))

    elapsed = timer_end(timer_start())

    assert elapsed == pytest.approx(1.25)
    assert capsys.readouterr().out == "Elapsed Time: 1.25 seconds\n"


def test_timer_formats_long_duration(monkeypatch, capsys):
    readings = iter([10.0, 135.678])
    monkeypatch.setattr(helpers.time, "perf_counter", lambda: next(readings))

    timer_end(timer_start("Process data"))

    assert capsys.readouterr().out == (
        "Processed data Elapsed Time: 2 minutes 5.68 seconds\n"
    )


def test_timer_start_rejects_non_string_description():
    with pytest.raises(TypeError, match="description"):
        timer_start(42)
