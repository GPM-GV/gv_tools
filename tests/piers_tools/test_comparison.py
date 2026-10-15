import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from piers_tools.comparison import circular_mean, read_standalone, read_wind, InputDataError, process_range


class ProcessingTests(unittest.TestCase):
    def test_range_one_csv_full_index_and_partial_instrument_availability(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            gauge_dir = root / 'standalone/WFFpad/2026/01'
            gauge_dir.mkdir(parents=True)
            (gauge_dir / 'Standalone_TB_2026_0110.dat').write_text('')
            rows_df = pd.DataFrame({'TIMESTAMP': pd.date_range('2026-01-11', periods=60, freq='s'), 'A': 0})
            (gauge_dir / 'Standalone_TB_2026_0111.dat').write_text('AMOUNT_OF_RAIN_PER_TIP: 0.01 inch\nLAT/LON:37,-75\n' + rows_df.to_csv(index=False))
            wind_dir = root / 'PIERS_Gauges_Daily/TEST/2026/01/10'
            wind_dir.mkdir(parents=True)
            (wind_dir / 'TEST_wind_20260110_daily.csv').write_text('20260110000012 01 180 2\n')
            output = root / 'results'
            result_df = process_range('2026-01-10', '2026-01-11', output, root=root, stations=['TEST'])
            self.assertEqual(result_df.shape, (2880, 3))
            self.assertTrue(result_df.loc['2026-01-10', 'WFFpad__A__rain_in'].isna().all())
            self.assertEqual(result_df.iloc[0]['TEST__wind_speed_m_s'], 2)
            self.assertEqual(list(output.iterdir()), [output / 'comparison_2026-01-10_2026-01-11.csv'])
            reloaded_df = pd.read_csv(next(output.iterdir()), index_col='TIMESTAMP', parse_dates=True)
            pd.testing.assert_frame_equal(result_df, reloaded_df, check_freq=False)
            daily_output = root / 'daily_results'
            process_range('2026-01-10', '2026-01-11', daily_output, root=root, stations=['TEST'], output_mode='daily')
            self.assertEqual(len(list(daily_output.glob('*.csv'))), 2)

    def test_empty_truncated_and_header_only_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rain.dat'
            for content in ['', 'AMOUNT_OF_RAIN_PER_TIP: 0.01 inch\n',
                            'AMOUNT_OF_RAIN_PER_TIP: 0.01 inch\nLAT/LON:37,-75\nTIMESTAMP,A\n']:
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises(InputDataError) as caught:
                        read_standalone(path, '2026-04-15')
                    self.assertIn(str(path), str(caught.exception))

    def test_direction_wrap_and_cancellation(self):
        self.assertAlmostEqual(circular_mean([359, 1]), 0)
        self.assertTrue(np.isnan(circular_mean([90, 270])))
        self.assertTrue(np.isnan(circular_mean([])))

    def test_rain_missing_minute_is_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rain.dat'
            rows = pd.DataFrame({'TIMESTAMP': pd.date_range('2026-07-22', periods=120, freq='s'), 'A': 0})
            rows.loc[0, 'A'] = 1
            rows = rows.drop(index=65)
            path.write_text('AMOUNT_OF_RAIN_PER_TIP: 0.01 inch\nLAT/LON:37,-75\n' + rows.to_csv(index=False))
            rain, count, _ = read_standalone(path, '2026-07-22')
            self.assertEqual(rain.iloc[0, 0], .01)
            self.assertTrue(np.isnan(rain.iloc[1, 0]))
            self.assertEqual(count.iloc[1, 0], 59)
            self.assertTrue(np.isnan(rain.iloc[2, 0]))

    def test_wind_bad_duplicates_and_empty_minutes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'wind.csv'
            path.write_text('20260722000012 01 359 2\n20260722000022 01 001 4\n20260722000022 01 001 4\nbad packet\n20260722000212 01 180 0\n')
            wind, count, meta = read_wind(path, '2026-07-22', 'TEST')
            self.assertEqual(wind.iloc[0, 0], 3)
            self.assertAlmostEqual(wind.iloc[0, 1], 0)
            self.assertTrue(wind.iloc[1].isna().all())
            self.assertEqual(count.iloc[0, 0], 2)
            self.assertEqual(meta['rejected_lines'], 1)
            self.assertEqual(meta['duplicate_packets_removed'], 1)


if __name__ == '__main__':
    unittest.main()
