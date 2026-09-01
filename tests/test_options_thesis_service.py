import datetime
import re
import unittest
import zipfile

from services.options_thesis_service import _option_price, build_options_thesis_data, generate_thesis_excel


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


def _cell_value(archive, worksheet_path, address):
    worksheet_xml = archive.read(worksheet_path).decode("utf-8")
    match = re.search(rf'<c[^>]*r="{address}"[^>]*>.*?<v>(.*?)</v>', worksheet_xml, re.DOTALL)
    if not match:
        raise AssertionError(f"Cell {worksheet_path}:{address} was not found")
    return match.group(1)


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
            option_value = _cell_value(archive, "xl/worksheets/sheet2.xml", "C4")
            pnl_formula, pnl_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet3.xml", "C4"
            )
            combined_formula, combined_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet4.xml", "C4"
            )

        expected_option_value = _option_price(269.50, 245.00, 26, 0.0379, 0.1501, "PUT")
        self.assertAlmostEqual(float(option_value), expected_option_value, places=8)
        self.assertIn("Option Price Matrix", pnl_formula)
        self.assertNotEqual(pnl_value, "")
        self.assertIn("TEXT", combined_formula)
        self.assertRegex(combined_value, r"^\$\d+\.\d{2} / ")

    def test_assumption_key_output_formulas_reference_the_documented_inputs(self):
        with zipfile.ZipFile(self.workbook_stream) as archive:
            premium_formula, _ = _formula_and_cached_value(
                archive, "xl/worksheets/sheet1.xml", "B17"
            )
            breakeven_formula, _ = _formula_and_cached_value(
                archive, "xl/worksheets/sheet1.xml", "B18"
            )
            percent_formula, _ = _formula_and_cached_value(
                archive, "xl/worksheets/sheet1.xml", "B19"
            )

        self.assertEqual(premium_formula, "B6*B7*B8")
        self.assertEqual(breakeven_formula, "B5-B6")
        self.assertEqual(percent_formula, "1-(B18/B4)")

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
                archive, "xl/worksheets/sheet3.xml", "C25"
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
                archive, "xl/worksheets/sheet2.xml", "B26"
            )
            pnl_formula, pnl_value = _formula_and_cached_value(
                archive, "xl/worksheets/sheet3.xml", "C26"
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

    def test_far_otm_contract_expands_around_current_spot_and_includes_key_levels(self):
        thesis = build_options_thesis_data(
            underlying_symbol="AAPL",
            baseline_price=316.85,
            strike_price=235.00,
            entry_premium=0.04,
            multiplier=100,
            quantity=2,
            iv=0.1501,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 10, 2),
            starting_dte=32,
            option_type="PUT",
        )

        self.assertEqual(thesis["scenario_range_percent"], 0.30)
        self.assertEqual(thesis["rows"][0]["percent_change"], 0.30)
        self.assertEqual(thesis["rows"][-1]["percent_change"], -0.30)
        self.assertEqual(
            next(row for row in thesis["rows"] if row["percent_change"] == 0)["underlying_price"],
            316.85,
        )
        self.assertEqual(
            next(row for row in thesis["rows"] if "Strike" in row["reference_levels"])["underlying_price"],
            235.00,
        )
        self.assertEqual(
            next(row for row in thesis["rows"] if "Breakeven" in row["reference_levels"])["underlying_price"],
            234.96,
        )

    def test_american_put_model_honors_early_exercise_value(self):
        option_value = _option_price(
            underlying_price=100,
            strike_price=150,
            dte=30,
            risk_free_rate=0.05,
            iv=0.20,
            option_type="PUT",
        )

        self.assertGreaterEqual(option_value, 50.0)

    def test_crr_model_matches_standard_one_year_benchmarks(self):
        call_value = _option_price(100, 100, 365, 0.05, 0.20, "CALL")
        put_value = _option_price(100, 100, 365, 0.05, 0.20, "PUT")

        self.assertAlmostEqual(call_value, 10.45, delta=0.03)
        self.assertAlmostEqual(put_value, 6.09, delta=0.03)

    def test_missing_provider_iv_is_derived_from_market_mark(self):
        thesis = build_options_thesis_data(
            underlying_symbol="AAPL",
            baseline_price=316.85,
            strike_price=235.00,
            entry_premium=0.04,
            multiplier=100,
            quantity=2,
            iv=0,
            market_premium=0.04,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 10, 2),
            starting_dte=32,
            option_type="PUT",
        )

        iv_assumption = next(item for item in thesis["assumptions"] if item["label"] == "Implied volatility")
        self.assertGreater(iv_assumption["value"], 0.30)
        self.assertEqual(iv_assumption["note"], "Derived from the current market mark")

    def test_sell_thesis_reverses_position_pnl(self):
        common = dict(
            underlying_symbol="AAPL",
            baseline_price=245.00,
            strike_price=245.00,
            entry_premium=0.08,
            multiplier=100,
            quantity=1,
            iv=0.25,
            risk_free_rate=0.0379,
            expiration_date=datetime.date(2026, 9, 25),
            starting_dte=26,
            option_type="PUT",
        )
        buy = build_options_thesis_data(**common, action="BUY")
        sell = build_options_thesis_data(**common, action="SELL")

        self.assertAlmostEqual(sell["rows"][0]["pnl"][0], -buy["rows"][0]["pnl"][0], places=8)


if __name__ == "__main__":
    unittest.main()
