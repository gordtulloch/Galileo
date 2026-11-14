"""Astrospheric hourly forecast parsing (What's Up Tonight strip; Options > Planning API key)."""
import pytest

from galileo.planning import astrospheric as a


@pytest.mark.requirement("TC-WUT-120")
@pytest.mark.priority("P3")
def test_tc_wut_120_astrospheric_hourly_and_errors():
    """WUT-120: Astrospheric hourly values parse with their colours; no key gives a stated reason."""
    fc = {"Cloud": [{"UTCForecastHour": "2026-11-14T03:00:00Z", "HourOffset": 1,
                     "Value": {"ActualValue": 40.0, "ValueColor": "#112233"}},
                    {"bad": 1}]}
    h = a.hourly(fc)
    assert list(h) == ["Cloud"]
    when, value, color = h["Cloud"][0]
    assert (when.hour, value, color) == (3, 40.0, "#112233")
    live = {"HourlyForecast": [{"UTCForecastHour": "2026-11-14T21:00:00Z", "HourOffset": 0,
                                "Cloud": {"ValueColor": "#9EDEDE", "ActualValue": 62.7},
                                "Transparency": {"ValueColor": "#F8F7F7", "ActualValue": 29.0},
                                "Seeing": {"ValueColor": "#94D4D4", "ActualValue": 2.0}}]}
    h = a.hourly(live)
    assert set(h) == {"Cloud", "Seeing", "Transparency"} and h["Seeing"][0][1] == 2.0
    assert a.hourly(None) == {}
    data, err = a.fetch_forecast("", 1.0, 2.0)
    assert data is None and "API key" in err
    assert a.display_value("Temperature", 278.15) == pytest.approx(5.0)
    assert a.display_value("Wind", 5.6) == 5.6


@pytest.mark.requirement("TC-WUT-120")
@pytest.mark.priority("P3")
def test_tc_wut_120_aurora_and_smoke_cells():
    """WUT-120: NOAA Kp forecast rows become 3-hour coloured cells; bad rows are skipped."""
    from galileo.planning import sky_conditions as sc
    cells = sc.parse_kp_forecast([{"time_tag": "2026-11-14T18:00:00", "kp": "5.33"}, {"time_tag": "bad"}, {}])
    assert len(cells) == 1 and cells[0][1] == 5.33 and cells[0][3] == 3.0
    assert sc.kp_color(1.0) != sc.kp_color(6.0)
    assert sc.aqi_color(25) != sc.aqi_color(250)
    assert sc.parse_kp_forecast(None) == []
