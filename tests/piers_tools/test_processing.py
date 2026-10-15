import unittest

import pandas as pd

from piers_tools.processing import clean_merged_dataframe, id_tips


class ProcessingTests(unittest.TestCase):
    def test_tip_algorithm_counts_full_increments_and_ignores_resets(self):
        self.assertEqual(
            id_tips([10, 10, 11, 11, 15, 0, 0, 2]),
            [0, 0, 1, 0, 4, 0, 0, 2],
        )

    def test_cleaning_renames_by_name_not_column_position(self):
        row = {
            "Group": "WFF",
            "Gauge type": "PIERS",
            "Tips_B": 2,
            "rssi_max": -70,
            "GaugeID": "PIERS0001",
            "Station Location": "North Jetty",
            "latitude": 38.123,
            "longitude": -75.456,
            "Accum_B [in]": 0.08,
            "record_count": 96,
            "Rain_Tip_A": 0.2,
            "battery_voltage_max": 13.5,
            "Accum_A [mm]": 1.0,
            "rssi_min": -90,
            "Accum_B [mm]": 2.0,
            "Tips_A": 1,
            "Rain_Tip_B": 0.254,
            "battery_voltage_min": 12.5,
            "Accum_A [in]": 0.04,
            "Bias [%]": -5.0,
        }
        result = clean_merged_dataframe(pd.DataFrame([row]))
        self.assertEqual(result.at[0, "Packets"], 96)
        self.assertEqual(result.at[0, "Group"], "WFF")
        self.assertEqual(result.at[0, "Station Location"], "North Jetty")
        self.assertEqual(result.at[0, "# Tips_A"], 1)
        self.assertEqual(result.at[0, "Volts_min"], 12.5)

    def test_report_rows_follow_group_order_then_gauge_id(self):
        base = {
            "Gauge type": "PIERS",
            "Station Location": "Site",
            "latitude": 38.0,
            "longitude": -75.0,
            "record_count": 96,
            "Rain_Tip_A": 0.254,
            "Rain_Tip_B": 0.254,
            "battery_voltage_min": 12.5,
            "battery_voltage_max": 13.0,
            "rssi_min": -90,
            "rssi_max": -70,
            "Tips_A": 0,
            "Tips_B": 0,
            "Accum_A [mm]": 0.0,
            "Accum_B [mm]": 0.0,
            "Accum_A [in]": 0.0,
            "Accum_B [in]": 0.0,
            "Bias [%]": 0.0,
        }
        rows = [
            {**base, "Group": "INCUS", "GaugeID": "PIERS0009"},
            {**base, "Group": "WFF", "GaugeID": "PIERS0002"},
            {**base, "Group": "GPM", "GaugeID": "PIERS0010"},
            {**base, "Group": "WFF", "GaugeID": "PIERS0001"},
            {**base, "Group": "PCMK", "GaugeID": "PIERS0004"},
            {**base, "Group": "IPMSI", "GaugeID": "PIERS0005"},
        ]
        result = clean_merged_dataframe(pd.DataFrame(rows))
        self.assertEqual(
            list(zip(result["Group"], result["GaugeID"])),
            [
                ("GPM", "PIERS0010"),
                ("WFF", "PIERS0001"),
                ("WFF", "PIERS0002"),
                ("PCMK", "PIERS0004"),
                ("IPMSI", "PIERS0005"),
                ("INCUS", "PIERS0009"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
