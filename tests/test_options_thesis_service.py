import datetime
import re
import unittest
import zipfile

from services.options_thesis_service import build_options_thesis_data, generate_thesis_excel


def _formula_and_cached_value(archive, worksheet_path, address):
    worksheet_xml = archive.read(worksheet_path).decode("utf-8")
    match = re.search(
        rf'<c[^>]*r="{address}"[^>]*>.*?<f[^>]*>(.*?)</f>.*?<v>(.*?)</v>',
        worksheet_xml,
        re.DOTALL,
    )
    if not match:
        raise AssertionError(f"Formula cell {worksheet_path}:{address} was not found")
    return match.group(1), match.group(2)


class OptionsThesisServiceTests(unittest.TestCase):
    def setUp(self):
        self.workbook_stream = generate_thesis_excel(
            underlying_symbol="AAPL",
            baseline_price=245.00,
            strike_price=245.00,
            entry_premium=0.08,
            multiplier=100,
            iv=0.1501,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 9, 25),
            starting_dte=26,
            option_type="PUT",
        )

    def test_formula_cells_include_visible_cached_results(self):
        with zipfile.ZipFile(self.workbook_stream) as archive:
            option_formula, option_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet2.xml", "C4"
            )
            pnl_formula, pnl_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet3.xml", "C4"
            )
            combined_formula, combined_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet4.xml", "C4"
            )

        self.assertIn("NORM.S.DIST", option_formula)
        self.assertNotEqual(option_value, "")
        self.assertIn("Option Price Matrix", pnl_formula)
        self.assertNotEqual(pnl_value, "")
        self.assertIn("TEXT", combined_formula)
        self.assertRegex(combined_value, r"^\$\d+\.\d{2} / ")

    def test_underlying_price_column_is_populated(self):
        with zipfile.ZipFile(self.workbook_stream) as archive:
            formula, cached_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet4.xml", "B4"
            )

        self.assertIn("Option Price Matrix", formula)
        self.assertEqual(float(cached_value), 269.5)

    def test_quantity_scales_expiration_pnl(self):
        workbook_stream = generate_thesis_excel(
            underlying_symbol="AAPL",
            baseline_price=245.00,
            strike_price=245.00,
            entry_premium=0.08,
            multiplier=100,
            quantity=2,
            iv=0.1501,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 9, 25),
            starting_dte=0,
            option_type="PUT",
        )
        with zipfile.ZipFile(workbook_stream) as archive:
            formula, cached_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet3.xml", "C24"
            )

        self.assertIn("'Assumptions'!$B$8", formula)
        self.assertEqual(float(cached_value), 4884.0)

    def test_scenario_prices_round_to_the_chart_cent_increment(self):
        workbook_stream = generate_thesis_excel(
            underlying_symbol="AAPL",
            baseline_price=316.85,
            strike_price=302.50,
            entry_premium=0.05,
            multiplier=100,
            quantity=2,
            iv=0.1501,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 9, 2),
            starting_dte=0,
            option_type="PUT",
        )
        with zipfile.ZipFile(workbook_stream) as archive:
            price_formula, price_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet2.xml", "B24"
            )
            pnl_formula, pnl_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet3.xml", "C24"
            )

        self.assertIn("ROUND", price_formula)
        self.assertEqual(float(price_value), 285.17)
        self.assertIn("'Assumptions'!$B$8", pnl_formula)
        self.assertAlmostEqual(float(pnl_value), 3456.0, places=2)

    def test_canonical_thesis_data_matches_workbook_scenario_conventions(self):
        thesis = build_options_thesis_data(
            underlying_symbol="AAPL",
            baseline_price=316.85,
            strike_price=302.50,
            entry_premium=0.05,
            multiplier=100,
            quantity=2,
            iv=0.1501,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 9, 2),
            starting_dte=0,
            option_type="PUT",
        )

        expiration_row = thesis["rows"][-1]
        self.assertEqual(thesis["columns"], [{"dte": 0, "date": "2026-09-02"}])
        self.assertEqual(expiration_row["percent_change"], -0.1)
        self.assertEqual(expiration_row["underlying_price"], 285.17)
        self.assertAlmostEqual(expiration_row["pnl"][0], 3456.0, places=2)


if __name__ == "__main__":
    unittest.main()
