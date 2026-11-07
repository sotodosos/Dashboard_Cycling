import tempfile
import unittest
from pathlib import Path

import pandas as pd

from garmin_dashboard import analytics, health, planning, reports, streams


class StreamTests(unittest.TestCase):
    def test_stream_values_accepts_list_and_cached_result(self):
        payload = [{"type": "watts", "data": [100, 200]}]
        self.assertEqual(streams.stream_values(payload, "watts"), [100, 200])
        self.assertEqual(
            streams.stream_values({"streams": payload, "error": None}, "watts"),
            [100, 200],
        )
        self.assertEqual(streams.stream_values(["malformed"], "watts"), [])

    def test_power_duration_curve(self):
        curve = streams.power_duration_curve([100, 200, 300], durations=(1, 2))
        self.assertEqual(curve["watts"].tolist(), [300.0, 250.0])


class ActivityMergeTests(unittest.TestCase):
    def test_merge_keeps_intervals_record_and_separate_activity_types(self):
        garmin_raw = pd.DataFrame([
            {"activity_id": "g1", "start_time_local": "2026-01-01 08:00:00",
             "activity_type": "road_biking", "duration_s": 3600, "distance_m": 30000},
            {"activity_id": "g2", "start_time_local": "2026-01-01 08:30:00",
             "activity_type": "road_biking", "duration_s": 3600, "distance_m": 30000},
        ])
        intervals_raw = pd.DataFrame([
            {"activity_id": "i1", "start_time_local": "2026-01-01 08:00:30",
             "activity_type": "Ride", "duration_s": 3600, "distance_m": 30000},
        ])
        combined = analytics.combine_activities(
            analytics.prepare_activities(garmin_raw),
            analytics.prepare_intervals_activities(intervals_raw),
        )
        self.assertEqual(set(combined["activity_id"]), {"i1", "g2"})
        self.assertEqual(len(combined), 2)

    def test_power_zones_prefer_indoor_ftp_for_both_contexts(self):
        settings = {"ftp": 200, "indoor_ftp": 250}
        outdoor = analytics.zone_model(settings, "power", indoor=False)
        indoor = analytics.zone_model(settings, "power", indoor=True)
        self.assertEqual(outdoor[0]["max"], 138)
        self.assertEqual(indoor[0]["max"], 138)


class PlanningTests(unittest.TestCase):
    def test_elevation_target_does_not_read_minutes_as_meters(self):
        target = planning._parse_planned_range(
            "10 min suaves + 3x15 min, salida con 900-950 m positivos", "m"
        )
        self.assertEqual(target, (900.0, 950.0, False))

    def test_block_editor_roundtrip(self):
        records = [{
            "Nombre": "Tempo", "Repeticiones": 3, "Duración (min)": 8,
            "Potencia desde (%)": 85, "Potencia hasta (%)": 90,
            "FC desde (ppm)": None, "FC hasta (ppm)": None,
            "Cadencia (rpm)": 90, "Notas": "Controlado",
        }]
        blocks, invalid = planning.blocks_from_records(records)
        self.assertEqual(invalid, 0)
        self.assertEqual(blocks[0]["nombre"], "Tempo")
        rendered = planning.blocks_text(blocks, ftp=300)[0]
        self.assertIn("255", rendered)
        self.assertIn("270 W", rendered)

    def test_plan_save_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            planning.save_plan(path, [{"sesion": "Fondo", "bloques": []}])
            items, error = planning.load_plan(path)
            self.assertIsNone(error)
            self.assertEqual(items[0]["sesion"], "Fondo")


class HealthAndReportTests(unittest.TestCase):
    def test_health_bands_use_personal_reference(self):
        frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=10),
            "resting_hr": [50] * 9 + [58],
            "sleep_h": [8] * 10,
        })
        result = health.reference_bands(frame)
        self.assertEqual(result["resting_hr"]["status"], "Por encima")
        self.assertEqual(result["sleep"]["status"], "Dentro")

    def test_report_serializes_and_uses_metric_rows(self):
        report = reports.build_activity_report(
            activity={"name": "Rodillo"},
            metrics={"distance_km": 40, "elapsed_s": 3600},
            health={
                "sleep_h": 7.5,
                "sleep_score": 82,
                "resting_hr": 52,
                "hrv": 48,
            },
            zones_hr=pd.DataFrame(),
            zones_power=pd.DataFrame(),
        )
        self.assertIn("Rodillo", reports.report_text(report))
        self.assertIn("calidad del sueño 82/100", reports.report_text(report))
        self.assertEqual(report["health"]["hrv"], 48)
        self.assertIn('"activity"', reports.report_json(report))
        self.assertTrue(reports.metric_rows({"distance_km": 40}))


if __name__ == "__main__":
    unittest.main()
