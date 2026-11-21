"""AV Water-Physics, ISO 21448 (SOTIF) Sensor-Degradation & SF Buried-Creek / King-Tide Engine.

Pure Python stdlib, zero network calls, <5 ms execution, and never raises.
All physical constants and SF hydrology parameters are grounded verbatim in:
  - research/AV_WATER_PHYSICS.md (OEM specs, Hale & Querry 1973, ISO 21448, UN ECE R100, NWS)
  - research/SF_HYDROLOGY_AND_TIDES.md (SFEI buried creeks, SFPUC combined sewer, NOAA 9414290)
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "media" / "physics_report.json"

# ---------------------------------------------------------------------------
# 1. Verified OEM Vehicle Specs (research/AV_WATER_PHYSICS.md)
# ---------------------------------------------------------------------------
VEHICLES: dict[str, dict[str, Any]] = {
    "jaguar_ipace": {
        "name": "Jaguar I-PACE (Waymo Gen-5)",
        "ground_clearance_mm": 174,
        "sidewall_mm": 123,
        "hub_height_mm": 367,
        "max_static_wading_mm": 500,
        "tire_psi": 37,
        "tire_size": "245/50R20",
        "is_ev": True,
    },
    "ioniq5": {
        "name": "Hyundai Ioniq 5 (Waymo Gen-6)",
        "ground_clearance_mm": 160,
        "sidewall_mm": 129,
        "hub_height_mm": 362,
        "max_static_wading_mm": None,
        "tire_psi": 36,
        "tire_size": "235/55R19",
        "is_ev": True,
    },
    "sedan": {
        "name": "Mid-size Passenger Sedan (Camry / Civic)",
        "ground_clearance_mm": 145,
        "sidewall_mm": 118,
        "hub_height_mm": 325,
        "max_static_wading_mm": None,
        "tire_psi": 35,
        "tire_size": "215/55R17",
        "is_ev": False,
    },
}

# ---------------------------------------------------------------------------
# 2. Decision 1 `car_depth` Level -> Physical Water Depth Mapping
# ---------------------------------------------------------------------------
DEPTH_LEVEL_MM: dict[int, dict[str, Any]] = {
    0: {"label": "dry or damp road", "depth_mm": 0, "depth_in": 0.0},
    1: {"label": "wet road, thin film of water", "depth_mm": 5, "depth_in": 0.2},
    2: {"label": "puddles in the lane, below the tire tread", "depth_mm": 50, "depth_in": 2.0},
    3: {"label": "water over the tire sidewall, below the wheel hub", "depth_mm": 150, "depth_in": 5.9},
    4: {"label": "water at or above the wheel hub, stall risk for a car", "depth_mm": 320, "depth_in": 12.6},
}

# Optical & RF attenuation constants (Hale & Querry 1973; 77 GHz automotive radar)
ALPHA_WATER_M_INV: dict[int, float] = {
    1550: 693.0,  # ~74.5x stronger than 905 nm
    905: 9.3,
}
RADAR_77GHZ_DB_PER_MM = 30.0
HYDROPLANE_COEFF = 10.35  # NASA Horne & Dreher: V_p (mph) = 10.35 * sqrt(tire_psi)
OUTFALL_BACKPRESSURE_FT = 6.0
SFPUC_DESIGN_STORM_3H_IN = 1.3

# ---------------------------------------------------------------------------
# 3. NOAA Station 9414290 (Golden Gate, MLLW) Verified Tide Table
# ---------------------------------------------------------------------------
GOLDEN_GATE_TIDES: dict[str, dict[str, Any]] = {
    "2026-11-18": {
        "golden_gate_tide_ft": 4.94,
        "high_tide_time": "06:45 AM PST",
        "low_tide_ft": 2.37,
        "low_tide_time": "12:45 PM PST",
        "king_tide_window": False,
        "lunar_phase": "Neap-to-building tide during record 2.64 in rainstorm",
    },
    "2026-11-24": {
        "golden_gate_tide_ft": 6.94,
        "high_tide_time": "10:05 AM PST",
        "low_tide_ft": -1.49,
        "low_tide_time": "05:03 PM PST",
        "king_tide_window": True,
        "lunar_phase": "Full Beaver Supermoon (6:53 AM PST) — King Tide Day 1",
    },
    "2026-11-25": {
        "golden_gate_tide_ft": 7.03,
        "high_tide_time": "10:49 AM PST",
        "low_tide_ft": -1.65,
        "low_tide_time": "05:52 PM PST",
        "king_tide_window": True,
        "lunar_phase": "PEAK KING TIDE DAY (+2.09 ft above Nov 18; 8.68 ft swing)",
    },
    "2026-11-26": {
        "golden_gate_tide_ft": 6.95,
        "high_tide_time": "11:38 AM PST",
        "low_tide_ft": -1.61,
        "low_tide_time": "06:42 PM PST",
        "king_tide_window": True,
        "lunar_phase": "King Tide Day 3 — tail of Supermoon King Tide window",
    },
}

DEFAULT_TIDE_RECORD: dict[str, Any] = {
    "golden_gate_tide_ft": 5.50,
    "high_tide_time": "N/A (SF mean high water baseline)",
    "low_tide_ft": 0.50,
    "low_tide_time": "N/A",
    "king_tide_window": False,
    "lunar_phase": "Baseline SF Bay MHW estimate (outside verified Nov 2026 table)",
}

# ---------------------------------------------------------------------------
# 4. SF Historic Buried-Creek & Filled-Bay-Margin Basins (SFEI / SFPUC)
# ---------------------------------------------------------------------------
# Each entry specifies corridor anchor points (lat, lon), capture radius (km),
# canonical basin name, outfall name, inside-Bay amplification (ft), and lag (min).
_BASIN_CORRIDORS: tuple[dict[str, Any], ...] = (
    {
        "basin": "Mission Creek / Mission Bay Fill",
        "outfall_name": "Potrero Point (Mission Creek CSD Outfall)",
        "amplification_ft": 0.50,
        "lag_min": 33,
        "max_radius_km": 1.15,
        "anchors": (
            (37.7764, -122.3939),  # 4th & King / Caltrain (r50_c66)
            (37.7735, -122.3965),  # Mission Creek Channel / 7th & Berry
            (37.7675, -122.3910),  # Mission Bay / 3rd & 16th
            (37.7705, -122.4075),  # Division & 9th / SoMa trough
            (37.7634, -122.4152),  # 17th & Folsom (SFPUC Folsom Stormwater Project)
            (37.7593, -122.4108),  # 20th & Alabama / Florida (r39_c57)
        ),
        "hydrology_note": (
            "1850s/1906 rubble fill over historic Mission Creek tidal estuary; "
            "bowl-shaped valley with chronic manhole geysers under tailwater backpressure."
        ),
    },
    {
        "basin": "Mission Creek / Mission Bay Fill",
        "outfall_name": "Rincon Point / Pier 22½ (SoMa / Embarcadero CSD Outfall)",
        "amplification_ft": 0.15,
        "lag_min": 18,
        "max_radius_km": 0.85,
        "anchors": (
            (37.7805, -122.3910),  # 691 2nd St / 2nd & Townsend (r53_c68)
            (37.7845, -122.3935),  # 2nd & Harrison / South Park SoMa fill edge
            (37.7860, -122.3880),  # Rincon Point / Pier 22½ Embarcadero
            (37.7820, -122.3990),  # 4th & Bryant / SoMa low-lying fill
        ),
        "hydrology_note": (
            "Low-lying SoMa / South Beach bay-fill margin draining to Rincon Point CSD outfalls "
            "adjacent to the historic Mission Bay shoreline."
        ),
    },
    {
        "basin": "Hayes Creek / Ghost Arroyo",
        "outfall_name": "Rincon Point / Pier 22½ (SoMa / Civic Center CSD Outfall)",
        "amplification_ft": 0.15,
        "lag_min": 18,
        "max_radius_km": 0.90,
        "anchors": (
            (37.7785, -122.4193),  # Grove & Van Ness (r52_c52)
            (37.7768, -122.4255),  # Hayes Valley / Laguna
            (37.7796, -122.4143),  # Civic Center / UN Plaza (groundwater-fed fountain)
            (37.7818, -122.4095),  # Market St & 7th/6th (BART 24/7 dewatering corridor)
            (37.7762, -122.4325),  # Alamo Square eastern headwaters
        ),
        "hydrology_note": (
            "Buried perennial stream ('Ghost Arroyo') from Alamo Square under Civic Center; "
            "shallow groundwater forces 24/7 BART dewatering pumps and rapid surface ponding."
        ),
    },
    {
        "basin": "Islais Creek",
        "outfall_name": "Hunters Point (Islais Creek CSD Outfall)",
        "amplification_ft": 0.80,
        "lag_min": 42,
        "max_radius_km": 1.65,
        "anchors": (
            (37.73825, -122.40695),  # Bayshore & Industrial (r25_c59, Nov 18 Waymo stall)
            (37.7355, -122.4110),    # Lower Alemany Blvd (10-ft SFPUC tunnel corridor)
            (37.7430, -122.4005),    # Toland & Oakdale / Industrial fill
            (37.7485, -122.3880),    # Islais Creek Channel / 3rd & Cargo
            (37.7475, -122.3945),    # Cesar Chavez / Evans / Illinois
            (37.7345, -122.4260),    # Glen Park / Alemany canyon mouth
        ),
        "hydrology_note": (
            "SF's largest historic drainage basin (~1/3 of city) funneled through buried culverts "
            "into flat Bay fill; Hunters Point tidal amplification reaches +0.80 ft."
        ),
    },
    {
        "basin": "Washerwoman's Lagoon / Marina Fill",
        "outfall_name": "Marina / Fort Point (North Shore CSD Outfall)",
        "amplification_ft": 0.05,
        "lag_min": 5,
        "max_radius_km": 1.00,
        "anchors": (
            (37.8045, -122.4380),  # Marina Blvd
            (37.7998, -122.4355),  # Lombard & Fillmore
            (37.8010, -122.4310),  # Laguna & Chestnut (Laguna Pequeña)
            (37.8035, -122.4235),  # Polk & Bay
            (37.8030, -122.4475),  # Palace of Fine Arts / Crissy margin
        ),
        "hydrology_note": (
            "Former tidal lagoon (Laguna Pequeña) filled with loose sand and 1906 debris "
            "just above Bay high-tide elevation."
        ),
    },
)

HERO_BLOCKS: tuple[dict[str, Any], ...] = (
    {
        "cell": "r50_c66",
        "name": "4th & King",
        "role": "/ride Caltrain destination (Mission Creek fill)",
        "lat": 37.7764,
        "lon": -122.3939,
        "verdict": {"depth_level": 3, "lane_covered": 0.91, "edges_hidden": 0.84},
    },
    {
        "cell": "r52_c52",
        "name": "Grove & Van Ness",
        "role": "/ride v2 watch block (Hayes Creek / Civic Center)",
        "lat": 37.7785,
        "lon": -122.4193,
        "verdict": {"depth_level": 2, "lane_covered": 0.72, "edges_hidden": 0.58},
    },
    {
        "cell": "r53_c68",
        "name": "691 2nd St",
        "role": "SoMa / 2nd & Townsend 311 photo block",
        "lat": 37.7805,
        "lon": -122.3910,
        "verdict": {"depth_level": 3, "lane_covered": 0.86, "edges_hidden": 0.78},
    },
    {
        "cell": "r25_c59",
        "name": "Bayshore & Industrial / Islais Creek",
        "role": "Nov 18 Waymo stall corridor (Islais Creek basin)",
        "lat": 37.73825,
        "lon": -122.40695,
        "verdict": {"depth_level": 4, "lane_covered": 0.98, "edges_hidden": 0.96},
    },
)


# ---------------------------------------------------------------------------
# Safe Coercion & Geometry Helpers
# ---------------------------------------------------------------------------
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _clamp01(value: Any, default: float = 0.0) -> float:
    val = _safe_float(value, default)
    return max(0.0, min(1.0, val))


def _clamp_depth_level(value: Any, default: int = 0) -> int:
    try:
        lvl = int(round(float(value)))
    except Exception:
        lvl = default
    return max(0, min(4, lvl))


def _resolve_vehicle(vehicle: Any) -> tuple[str, dict[str, Any]]:
    raw = str(vehicle or "jaguar_ipace").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in VEHICLES:
        return raw, VEHICLES[raw]
    if "ioniq" in raw or "gen6" in raw or "gen_6" in raw:
        return "ioniq5", VEHICLES["ioniq5"]
    if "sedan" in raw or "camry" in raw or "civic" in raw:
        return "sedan", VEHICLES["sedan"]
    return "jaguar_ipace", VEHICLES["jaguar_ipace"]


def _normalize_date(date: Any) -> str:
    raw = str(date or "2026-11-18").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return "2026-11-18"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0088
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl * 0.5) ** 2
    return 2.0 * r_km * math.asin(min(1.0, math.sqrt(max(0.0, a))))


# ---------------------------------------------------------------------------
# 3. Beer-Lambert LiDAR Round-Trip Water Transmission
# ---------------------------------------------------------------------------
def lidar_transmission(depth_mm: float, wavelength_nm: int = 1550) -> float:
    """Return Beer-Lambert round-trip LiDAR transmission exp(-2 * alpha * depth_m).

    Uses Hale & Querry (1973) liquid-water attenuation coefficients:
      - 1550 nm: alpha = 693.0 m^-1
      -  905 nm: alpha =   9.3 m^-1
    Never raises; returns a float in [0.0, 1.0].
    """
    try:
        d_mm = max(0.0, _safe_float(depth_mm, 0.0))
        if d_mm == 0.0:
            return 1.0
        wl = int(round(_safe_float(wavelength_nm, 1550.0)))
        if wl in ALPHA_WATER_M_INV:
            alpha = ALPHA_WATER_M_INV[wl]
        else:
            nearest_wl = min(ALPHA_WATER_M_INV, key=lambda k: abs(k - wl))
            alpha = ALPHA_WATER_M_INV[nearest_wl]
        exponent = -2.0 * alpha * (d_mm / 1000.0)
        if exponent < -700.0:
            return 0.0
        return max(0.0, min(1.0, math.exp(exponent)))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 4. ISO 21448 (SOTIF) Sensor Degradation & Vehicle Flood Physics
# ---------------------------------------------------------------------------
def sotif_sensor_risk(
    depth_level: int,
    lane_covered: float,
    edges_hidden: float,
    vehicle: str = "jaguar_ipace",
) -> dict[str, Any]:
    """Compute ISO 21448 SOTIF sensor-degradation, hydrodynamic, and EV HV flood risks.

    Never raises.
    """
    try:
        lvl = _clamp_depth_level(depth_level, 0)
        lc = round(_clamp01(lane_covered, 0.0), 3)
        eh = round(_clamp01(edges_hidden, 0.0), 3)
        veh_key, spec = _resolve_vehicle(vehicle)

        depth_info = DEPTH_LEVEL_MM[lvl]
        depth_mm = int(depth_info["depth_mm"])
        depth_in = float(depth_info["depth_in"])
        depth_label = str(depth_info["label"])

        ground_clearance_mm = int(spec["ground_clearance_mm"])
        clearance_margin_mm = ground_clearance_mm - depth_mm

        t_1550 = lidar_transmission(depth_mm, 1550)
        t_905 = lidar_transmission(depth_mm, 905)
        lidar_1550_roundtrip_pct = round(t_1550 * 100.0, 4)
        lidar_905_roundtrip_pct = round(t_905 * 100.0, 2)
        radar_77ghz_db_loss = round(depth_mm * RADAR_77GHZ_DB_PER_MM, 1)

        tire_psi = _safe_float(spec["tire_psi"], 37.0)
        hydroplane_critical_mph = round(HYDROPLANE_COEFF * math.sqrt(max(1.0, tire_psi)), 1)

        # UN ECE R100 HV isolation / underbody electrical breach risk
        if lvl >= 4 or depth_mm >= ground_clearance_mm:
            un_r100_hv_risk = "critical"
        elif lvl >= 3 or clearance_margin_mm <= 40:
            un_r100_hv_risk = "elevated"
        else:
            un_r100_hv_risk = "low"

        # NWS / FEMA / AAA flotation & loss-of-traction risk (6 in elevated, 12 in critical)
        if depth_mm >= 300 or lvl >= 4:
            flotation_risk = "critical"
        elif depth_mm >= 150 or lvl >= 3 or depth_mm >= ground_clearance_mm:
            flotation_risk = "elevated"
        else:
            flotation_risk = "low"

        specular_mirror_risk = bool(lvl >= 2 and lc >= 0.5)
        camera_curb_blind = bool(eh >= 0.5)

        if flotation_risk == "critical" or un_r100_hv_risk == "critical":
            recommended_action = "avoid"
        elif lvl >= 3 and (lc >= 0.5 or eh >= 0.5):
            recommended_action = "avoid"
        elif lvl >= 2 and (lc >= 0.5 or eh >= 0.5):
            recommended_action = "slow"
        else:
            recommended_action = "proceed"

        veh_short = spec["name"].split(" (")[0]
        if lvl >= 4:
            sotif_summary = (
                f"ISO 21448 SOTIF CRITICAL: ~{depth_mm} mm ({depth_in:.1f} in) exceeds {veh_short} "
                f"{ground_clearance_mm} mm clearance by {abs(clearance_margin_mm)} mm, blacks out "
                f"1550 nm LiDAR ({lidar_1550_roundtrip_pct:.1f}%, 905 nm {lidar_905_roundtrip_pct:.1f}%) "
                f"and 77 GHz radar (~{radar_77ghz_db_loss:.0f} dB), with critical UN R100 HV and NWS 12 in flotation risk."
            )
        elif lvl == 3:
            margin_phrase = (
                f"leaves only {clearance_margin_mm} mm clearance"
                if clearance_margin_mm >= 0
                else f"breaches chassis clearance by {abs(clearance_margin_mm)} mm"
            )
            sotif_summary = (
                f"ISO 21448 SOTIF HIGH: ~{depth_mm} mm ({depth_in:.1f} in) sidewall-deep water {margin_phrase} "
                f"under {veh_short}, drops 1550 nm LiDAR to {lidar_1550_roundtrip_pct:.1f}% "
                f"(905 nm {lidar_905_roundtrip_pct:.1f}%), blocks 77 GHz radar (~{radar_77ghz_db_loss:.0f} dB), "
                f"and triggers {un_r100_hv_risk} UN R100 HV / {flotation_risk} flotation risk (edges_hidden={eh:.2f})."
            )
        elif lvl == 2:
            sotif_summary = (
                f"ISO 21448 SOTIF WATCH: ~{depth_mm} mm ({depth_in:.1f} in) lane puddles leave "
                f"{clearance_margin_mm} mm clearance under {veh_short} but extinguish 1550 nm LiDAR "
                f"({lidar_1550_roundtrip_pct:.1f}%, 905 nm {lidar_905_roundtrip_pct:.1f}%) via specular mirror "
                f"reflection and attenuate 77 GHz radar (~{radar_77ghz_db_loss:.0f} dB; Vp={hydroplane_critical_mph:.1f} mph)."
            )
        else:
            sotif_summary = (
                f"ISO 21448 SOTIF nominal: ~{depth_mm} mm ({depth_in:.1f} in) surface leaves "
                f"{clearance_margin_mm} mm clearance under {veh_short} (905 nm LiDAR {lidar_905_roundtrip_pct:.1f}%, "
                f"1550 nm {lidar_1550_roundtrip_pct:.2f}%, hydroplaning Vp={hydroplane_critical_mph:.1f} mph) "
                f"with low HV and flotation risk."
            )

        return {
            "vehicle": veh_key,
            "vehicle_name": spec["name"],
            "depth_level": lvl,
            "depth_label": depth_label,
            "depth_mm": depth_mm,
            "depth_in": depth_in,
            "lane_covered": lc,
            "edges_hidden": eh,
            "ground_clearance_mm": ground_clearance_mm,
            "clearance_margin_mm": clearance_margin_mm,
            "sidewall_mm": int(spec["sidewall_mm"]),
            "hub_height_mm": int(spec["hub_height_mm"]),
            "max_static_wading_mm": spec["max_static_wading_mm"],
            "lidar_1550_roundtrip_pct": lidar_1550_roundtrip_pct,
            "lidar_905_roundtrip_pct": lidar_905_roundtrip_pct,
            "radar_77ghz_db_loss": radar_77ghz_db_loss,
            "hydroplane_critical_mph": hydroplane_critical_mph,
            "un_r100_hv_risk": un_r100_hv_risk,
            "flotation_risk": flotation_risk,
            "specular_mirror_risk": specular_mirror_risk,
            "camera_curb_blind": camera_curb_blind,
            "recommended_action": recommended_action,
            "sotif_summary": sotif_summary,
        }
    except Exception:
        return {
            "vehicle": "jaguar_ipace",
            "vehicle_name": VEHICLES["jaguar_ipace"]["name"],
            "depth_level": 0,
            "depth_label": DEPTH_LEVEL_MM[0]["label"],
            "depth_mm": 0,
            "depth_in": 0.0,
            "lane_covered": 0.0,
            "edges_hidden": 0.0,
            "ground_clearance_mm": 174,
            "clearance_margin_mm": 174,
            "sidewall_mm": 123,
            "hub_height_mm": 367,
            "max_static_wading_mm": 500,
            "lidar_1550_roundtrip_pct": 100.0,
            "lidar_905_roundtrip_pct": 100.0,
            "radar_77ghz_db_loss": 0.0,
            "hydroplane_critical_mph": 63.0,
            "un_r100_hv_risk": "low",
            "flotation_risk": "low",
            "specular_mirror_risk": False,
            "camera_curb_blind": False,
            "recommended_action": "proceed",
            "sotif_summary": "ISO 21448 SOTIF fallback nominal evaluation.",
        }


# ---------------------------------------------------------------------------
# 5. SF Buried-Creek / Bay-Fill Basin & King-Tide Backpressure Engine
# ---------------------------------------------------------------------------
def buried_creek_basin(lat: float, lon: float, date: str = "2026-11-18") -> dict[str, Any]:
    """Map (lat, lon) to the nearest SF historic buried creek / bay-fill basin and tide state.

    Never raises.
    """
    try:
        lat_f = _safe_float(lat, 37.7764)
        lon_f = _safe_float(lon, -122.3939)
        norm_date = _normalize_date(date)

        if norm_date in GOLDEN_GATE_TIDES:
            tide_rec = GOLDEN_GATE_TIDES[norm_date]
            tide_source = "noaa_9414290_verified"
        else:
            tide_rec = DEFAULT_TIDE_RECORD
            tide_source = "sf_baseline_mhw"

        best_corridor: dict[str, Any] | None = None
        best_dist_km = float("inf")

        for corridor in _BASIN_CORRIDORS:
            min_anchor_dist = min(
                _haversine_km(lat_f, lon_f, a_lat, a_lon)
                for a_lat, a_lon in corridor["anchors"]
            )
            if min_anchor_dist <= corridor["max_radius_km"] and min_anchor_dist < best_dist_km:
                best_dist_km = min_anchor_dist
                best_corridor = corridor

        if best_corridor is not None:
            basin_name = str(best_corridor["basin"])
            outfall_name = str(best_corridor["outfall_name"])
            amp_ft = float(best_corridor["amplification_ft"])
            lag_min = int(best_corridor["lag_min"])
            hydrology_note = str(best_corridor["hydrology_note"])
            is_historic_fill = True
            dist_km = round(best_dist_km, 3)
        else:
            nearest_any = min(
                _haversine_km(lat_f, lon_f, a_lat, a_lon)
                for corridor in _BASIN_CORRIDORS
                for a_lat, a_lon in corridor["anchors"]
            )
            basin_name = "Upland / Outside Historic Fill"
            outfall_name = "Upland Gravity Drainage (No Historic Fill)"
            amp_ft = 0.0
            lag_min = 0
            hydrology_note = (
                "Outside SF's historic buried-creek and bay-fill margins; drains via gravity "
                "downslope into low-lying combined-sewer basins."
            )
            is_historic_fill = False
            dist_km = round(nearest_any, 3)

        gg_tide = float(tide_rec["golden_gate_tide_ft"])
        amplified_tide = round(gg_tide + amp_ft, 2)
        outfall_backpressure = bool(amplified_tide >= OUTFALL_BACKPRESSURE_FT)

        return {
            "basin": basin_name,
            "is_historic_fill": is_historic_fill,
            "hydrology_note": hydrology_note,
            "outfall_name": outfall_name,
            "distance_to_channel_km": dist_km,
            "date": norm_date,
            "station": "9414290",
            "station_name": "San Francisco (Fort Point / Golden Gate)",
            "golden_gate_tide_ft": gg_tide,
            "high_tide_time": str(tide_rec["high_tide_time"]),
            "low_tide_ft": float(tide_rec["low_tide_ft"]),
            "low_tide_time": str(tide_rec["low_tide_time"]),
            "outfall_amplification_ft": amp_ft,
            "outfall_tide_lag_min": lag_min,
            "amplified_tide_ft": amplified_tide,
            "outfall_backpressure": outfall_backpressure,
            "king_tide_window": bool(tide_rec["king_tide_window"]),
            "lunar_phase": str(tide_rec["lunar_phase"]),
            "sewer_design_ceiling_in_3h": SFPUC_DESIGN_STORM_3H_IN,
            "tide_source": tide_source,
        }
    except Exception:
        return {
            "basin": "Upland / Outside Historic Fill",
            "is_historic_fill": False,
            "hydrology_note": "Fallback SF hydrology basin record.",
            "outfall_name": "Upland Gravity Drainage (No Historic Fill)",
            "distance_to_channel_km": 0.0,
            "date": "2026-11-18",
            "station": "9414290",
            "station_name": "San Francisco (Fort Point / Golden Gate)",
            "golden_gate_tide_ft": 4.94,
            "high_tide_time": "06:45 AM PST",
            "low_tide_ft": 2.37,
            "low_tide_time": "12:45 PM PST",
            "outfall_amplification_ft": 0.0,
            "outfall_tide_lag_min": 0,
            "amplified_tide_ft": 4.94,
            "outfall_backpressure": False,
            "king_tide_window": False,
            "lunar_phase": "Fallback",
            "sewer_design_ceiling_in_3h": SFPUC_DESIGN_STORM_3H_IN,
            "tide_source": "fallback",
        }


# ---------------------------------------------------------------------------
# 6. Combined Block Physics Assessment
# ---------------------------------------------------------------------------
def _extract_verdict_inputs(verdict: dict[str, Any] | None) -> tuple[int, float, float]:
    """Normalize any Decision 1 / vision.py / sim.py verdict dict into (depth_level, lane_covered, edges_hidden)."""
    if not isinstance(verdict, dict):
        return 0, 0.0, 0.0

    rubric = verdict.get("rubric") if isinstance(verdict.get("rubric"), dict) else {}

    # 1. depth_level
    if verdict.get("depth_level") is not None:
        depth_level = _clamp_depth_level(verdict.get("depth_level"), 0)
    elif verdict.get("car_depth") is not None:
        depth_level = _clamp_depth_level(verdict.get("car_depth"), 0)
    else:
        raw_label = str(verdict.get("depth_label") or "").strip().lower()
        label_map = {
            "none": 0,
            "dry": 0,
            "wet": 1,
            "puddle": 2,
            "puddles": 2,
            "ankle": 3,
            "sidewall": 3,
            "impassable": 4,
            "hub": 4,
        }
        if raw_label in label_map:
            depth_level = label_map[raw_label]
        elif verdict.get("depth_score") is not None:
            depth_level = _clamp_depth_level(_clamp01(verdict.get("depth_score"), 0.0) * 4.0, 0)
        else:
            depth_level = 0

    # 2. lane_covered
    lc_raw = verdict.get("lane_covered")
    if lc_raw is None:
        lc_raw = rubric.get("lane_covered")
    if lc_raw is None:
        lc_raw = verdict.get("flooded_p")
    lane_covered = _clamp01(lc_raw, 0.0 if depth_level < 2 else 0.75)

    # 3. edges_hidden
    eh_raw = verdict.get("edges_hidden")
    if eh_raw is None:
        eh_raw = rubric.get("edges_hidden")
    if eh_raw is None:
        eh_raw = max(0.0, lane_covered - 0.1) if depth_level >= 2 else 0.0
    edges_hidden = _clamp01(eh_raw, 0.0)

    return depth_level, lane_covered, edges_hidden


def assess_block_physics(
    lat: float,
    lon: float,
    verdict: dict[str, Any] | None = None,
    date: str = "2026-11-18",
    vehicle: str = "jaguar_ipace",
) -> dict[str, Any]:
    """Combine ISO 21448 SOTIF sensor physics with SF buried-creek & King-Tide backpressure.

    Never raises.
    """
    try:
        lat_f = _safe_float(lat, 37.7764)
        lon_f = _safe_float(lon, -122.3939)
        norm_date = _normalize_date(date)
        depth_level, lane_covered, edges_hidden = _extract_verdict_inputs(verdict)

        sotif = sotif_sensor_risk(
            depth_level=depth_level,
            lane_covered=lane_covered,
            edges_hidden=edges_hidden,
            vehicle=vehicle,
        )
        basin = buried_creek_basin(lat_f, lon_f, date=norm_date)

        # Compound risk grade
        if sotif["flotation_risk"] == "critical" or sotif["un_r100_hv_risk"] == "critical":
            combined_risk = "critical"
        elif sotif["depth_level"] >= 3 and basin["outfall_backpressure"]:
            combined_risk = "critical"
        elif sotif["depth_level"] >= 3 or (sotif["depth_level"] >= 2 and basin["outfall_backpressure"]):
            combined_risk = "high"
        elif sotif["depth_level"] >= 2 or (basin["is_historic_fill"] and basin["outfall_backpressure"]):
            combined_risk = "elevated"
        else:
            combined_risk = "low"

        tide_tag = (
            f"OUTFALL BACKPRESSURE ({basin['amplified_tide_ft']:.2f} ft MLLW at {basin['outfall_name']}, "
            f"+{basin['outfall_amplification_ft']:.2f} ft over {basin['golden_gate_tide_ft']:.2f} ft Golden Gate)"
            if basin["outfall_backpressure"]
            else f"free-draining tide ({basin['amplified_tide_ft']:.2f} ft MLLW at {basin['outfall_name']}, "
            f"+{basin['outfall_amplification_ft']:.2f} ft over {basin['golden_gate_tide_ft']:.2f} ft Golden Gate)"
        )

        engineering_brief = (
            f"[{combined_risk.upper()}] {basin['basin']} on {norm_date} ({tide_tag}). "
            f"{sotif['sotif_summary']}"
        )

        return {
            "lat": round(lat_f, 6),
            "lon": round(lon_f, 6),
            "date": norm_date,
            "vehicle": sotif["vehicle"],
            "combined_risk": combined_risk,
            "sotif": sotif,
            "basin": basin,
            "engineering_brief": engineering_brief,
            "ok": True,
        }
    except Exception:
        fallback_sotif = sotif_sensor_risk(0, 0.0, 0.0, "jaguar_ipace")
        fallback_basin = buried_creek_basin(37.7764, -122.3939, "2026-11-18")
        return {
            "lat": 37.7764,
            "lon": -122.3939,
            "date": "2026-11-18",
            "vehicle": "jaguar_ipace",
            "combined_risk": "low",
            "sotif": fallback_sotif,
            "basin": fallback_basin,
            "engineering_brief": "Fallback physics assessment.",
            "ok": False,
        }


# ---------------------------------------------------------------------------
# 7. CLI Report Generator (`python -m gem.physics`)
# ---------------------------------------------------------------------------
def build_physics_report(dates: tuple[str, ...] = ("2026-11-18", "2026-11-25")) -> dict[str, Any]:
    """Evaluate all 4 hero SF blocks across replay & Peak King Tide dates and return report dict."""
    t0 = time.perf_counter()
    evaluations: list[dict[str, Any]] = []
    by_date: dict[str, list[dict[str, Any]]] = {}

    for dt in dates:
        date_rows: list[dict[str, Any]] = []
        for blk in HERO_BLOCKS:
            primary = assess_block_physics(
                lat=blk["lat"],
                lon=blk["lon"],
                verdict=blk["verdict"],
                date=dt,
                vehicle="jaguar_ipace",
            )
            vehicle_matrix = {}
            for vkey in VEHICLES:
                v_sotif = sotif_sensor_risk(
                    depth_level=blk["verdict"]["depth_level"],
                    lane_covered=blk["verdict"]["lane_covered"],
                    edges_hidden=blk["verdict"]["edges_hidden"],
                    vehicle=vkey,
                )
                vehicle_matrix[vkey] = {
                    "ground_clearance_mm": v_sotif["ground_clearance_mm"],
                    "clearance_margin_mm": v_sotif["clearance_margin_mm"],
                    "hydroplane_critical_mph": v_sotif["hydroplane_critical_mph"],
                    "un_r100_hv_risk": v_sotif["un_r100_hv_risk"],
                    "flotation_risk": v_sotif["flotation_risk"],
                    "recommended_action": v_sotif["recommended_action"],
                }

            entry = {
                "cell": blk["cell"],
                "name": blk["name"],
                "role": blk["role"],
                "input_verdict": blk["verdict"],
                "assessment": primary,
                "vehicle_comparison": vehicle_matrix,
            }
            evaluations.append(entry)
            date_rows.append(entry)
        by_date[dt] = date_rows

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "engine": "gem.physics",
        "execution_ms": elapsed_ms,
        "vehicles": VEHICLES,
        "depth_level_mm": {str(k): v for k, v in DEPTH_LEVEL_MM.items()},
        "optical_and_rf_constants": {
            "alpha_1550_m_inv": ALPHA_WATER_M_INV[1550],
            "alpha_905_m_inv": ALPHA_WATER_M_INV[905],
            "absorption_ratio_1550_over_905": round(ALPHA_WATER_M_INV[1550] / ALPHA_WATER_M_INV[905], 2),
            "radar_77ghz_db_per_mm": RADAR_77GHZ_DB_PER_MM,
            "hydroplane_coeff": HYDROPLANE_COEFF,
            "outfall_backpressure_threshold_ft": OUTFALL_BACKPRESSURE_FT,
            "source": "Hale & Querry (1973), ISO 21448:2022, UN ECE R100, NWS/FEMA",
        },
        "tides_noaa_9414290": GOLDEN_GATE_TIDES,
        "dates": list(dates),
        "by_date": by_date,
        "evaluations": evaluations,
    }


def _format_table(report: dict[str, Any]) -> str:
    headers = (
        "Date",
        "Block (Cell)",
        "Basin",
        "Tide (GG->Out)",
        "BP",
        "Depth",
        "Clr(mm)",
        "1550/905%",
        "77GHz dB",
        "HV / Float",
        "Risk",
    )
    rows: list[tuple[str, ...]] = []
    for ev in report["evaluations"]:
        a = ev["assessment"]
        s = a["sotif"]
        b = a["basin"]
        block_label = f"{ev['name']} ({ev['cell']})"
        if len(block_label) > 28:
            block_label = f"Bayshore & Ind. ({ev['cell']})"
        basin_short = (
            b["basin"]
            .replace("Mission Creek / Mission Bay Fill", "Mission Creek Fill")
            .replace("Hayes Creek / Ghost Arroyo", "Hayes Creek")
            .replace("Washerwoman's Lagoon / Marina Fill", "Marina Fill")
        )
        tide_str = f"{b['golden_gate_tide_ft']:.2f}->{b['amplified_tide_ft']:.2f}ft"
        bp_str = "YES" if b["outfall_backpressure"] else "no"
        depth_str = f"L{s['depth_level']} {s['depth_mm']}mm"
        clr_str = f"{s['clearance_margin_mm']:+d}"
        lidar_str = f"{s['lidar_1550_roundtrip_pct']:.1f}/{s['lidar_905_roundtrip_pct']:.1f}"
        radar_str = f"{s['radar_77ghz_db_loss']:.0f}"
        hv_fl = f"{s['un_r100_hv_risk'][:4]}/{s['flotation_risk'][:4]}"
        risk = a["combined_risk"].upper()
        rows.append(
            (
                a["date"],
                block_label,
                basin_short,
                tide_str,
                bp_str,
                depth_str,
                clr_str,
                lidar_str,
                radar_str,
                hv_fl,
                risk,
            )
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    sep = "-+-".join("-" * w for w in widths)
    lines = [
        f"AV Water-Physics, ISO 21448 SOTIF & SF King-Tide Report (Jaguar I-PACE Gen-5 | {report['execution_ms']:.2f} ms)",
        " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        sep,
    ]
    for r in rows:
        lines.append(" | ".join(r[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def main() -> int:
    report = build_physics_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(_format_table(report))
    print(f"\nWrote {REPORT_PATH} ({len(report['evaluations'])} block-date evaluations in {report['execution_ms']:.2f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
