"""Defaults for the ``climate`` section (``pipeline/physical/climate.py``)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Mean annual sea-level temperature: equator_c - lat_coefficient * latitude² + offset_c (°C).
    "equator_c": 28.0,
    "lat_coefficient": 0.0079,  # °C per degree² of latitude
    "offset_c": 0.0,  # global warming (+) or cooling (-) of the whole world, °C
    "lapse_c_per_km": 6.5,  # temperature drop per km of height above sea level
    "temperature_noise_c": 4.0,  # amplitude of the regional temperature noise, °C
    "temperature_feature_km": 1500.0,
    "temperature_octaves": 3,  # fBm gain and lacunarity are terrain.fbm_gain / terrain.fbm_lacunarity
    # Prevailing winds carry moisture across each row: from the west between these absolute latitudes
    # (westerlies), from the east elsewhere (trade winds and polar easterlies).
    "westerly_band_deg": [30.0, 60.0],
    "recharge_km": 430.0,  # air over sea regains full moisture after this many km
    "decay_km": 1700.0,  # air over land loses moisture with e-folding distance decay_km
    "orographic_rise_m": 500.0,  # height gained in one step that wrings out the most rain (upslope)
    "orographic_base": 0.35,  # share of the air's moisture rained out on flat land (0..1)
    "shadow_rise_m": 2000.0,  # moisture lost per step = rise / shadow_rise_m (rain shadow behind ranges)
    "max_shadow_loss": 0.5,  # cap on the per-step rain-shadow loss (0..1)
    "min_keep": 0.2,  # air always keeps at least this share of its moisture per land step (0..1)
    # Moisture mixes wind-borne rain, regional noise and nearness to the coast, then is rank-normalised
    # over land so the classifier sees an even 0..1 spread.
    "rain_weight": 0.55,
    "noise_weight": 0.3,
    "coast_weight": 0.25,
    "coast_km": 215.0,  # e-folding distance of the coastal moisture term
    "moisture_feature_km": 1200.0,
    "moisture_octaves": 4,
    # Annual rainfall: (rain_min_mm + rain_span_mm * moisture^rain_exponent) * cold factor, where the cold
    # factor clamp(cold_floor + (t + cold_offset_c) / cold_span_c, cold_floor, 1) dries out cold air.
    "rain_min_mm": 50.0,
    "rain_span_mm": 3200.0,
    "rain_exponent": 1.8,
    "cold_floor": 0.45,
    "cold_offset_c": 10.0,
    "cold_span_c": 50.0,
}
