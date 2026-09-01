import datetime
import math
from io import BytesIO

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name


def _option_price(
    underlying_price: float,
    strike_price: float,
    dte: int,
    risk_free_rate: float,
    iv: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float:
    if dte <= 0:
        if option_type == "CALL":
            return max(underlying_price - strike_price, 0.0)
        return max(strike_price - underlying_price, 0.0)

    years = dte / 365.0
    safe_iv = max(float(iv), 0.000000001)
    steps = max(50, min(200, int(dte) * 4))
    time_step = years / steps
    up = math.exp(safe_iv * math.sqrt(time_step))
    down = 1.0 / up
    growth = math.exp((risk_free_rate - dividend_yield) * time_step)
    probability = (growth - down) / (up - down)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("Unable to price this option with the supplied volatility and rates")
    discount = math.exp(-risk_free_rate * time_step)

    asset_prices = [
        underlying_price * (up ** (steps - index)) * (down ** index)
        for index in range(steps + 1)
    ]
    if option_type == "CALL":
        option_values = [max(price - strike_price, 0.0) for price in asset_prices]
    else:
        option_values = [max(strike_price - price, 0.0) for price in asset_prices]

    for step in range(steps - 1, -1, -1):
        next_values = []
        for index in range(step + 1):
            continuation = discount * (
                probability * option_values[index]
                + (1.0 - probability) * option_values[index + 1]
            )
            asset_price = underlying_price * (up ** (step - index)) * (down ** index)
            exercise = (
                max(asset_price - strike_price, 0.0)
                if option_type == "CALL"
                else max(strike_price - asset_price, 0.0)
            )
            next_values.append(max(continuation, exercise))
        option_values = next_values
    return option_values[0]


def _implied_volatility(
    market_premium: float,
    underlying_price: float,
    strike_price: float,
    dte: int,
    risk_free_rate: float,
    option_type: str,
    dividend_yield: float = 0.0,
) -> float | None:
    intrinsic = (
        max(underlying_price - strike_price, 0.0)
        if option_type == "CALL"
        else max(strike_price - underlying_price, 0.0)
    )
    upper_bound = underlying_price if option_type == "CALL" else strike_price
    if market_premium < intrinsic or market_premium > upper_bound or market_premium <= 0:
        return None

    low, high = 0.01, 5.0
    low_price = _option_price(
        underlying_price, strike_price, dte, risk_free_rate, low, option_type, dividend_yield
    )
    high_price = _option_price(
        underlying_price, strike_price, dte, risk_free_rate, high, option_type, dividend_yield
    )
    if market_premium < low_price - 0.005 or market_premium > high_price + 0.005:
        return None
    for _ in range(60):
        midpoint = (low + high) / 2.0
        modeled_price = _option_price(
            underlying_price, strike_price, dte, risk_free_rate, midpoint, option_type, dividend_yield
        )
        if modeled_price < market_premium:
            low = midpoint
        else:
            high = midpoint
    result = (low + high) / 2.0
    reproduced_price = _option_price(
        underlying_price, strike_price, dte, risk_free_rate, result, option_type, dividend_yield
    )
    return result if abs(reproduced_price - market_premium) <= 0.005 else None


def _pnl_display(value: float) -> str:
    if value > 0:
        return f"+${value:,.0f}"
    if value < 0:
        return f"-${abs(value):,.0f}"
    return "$0"


def _scenario_prices(
    baseline_price: float,
    strike_price: float,
    breakeven: float,
) -> tuple[float, list[dict]]:
    key_prices = {
        "Strike": round(strike_price, 2),
        "Breakeven": round(breakeven, 2),
    }
    maximum_move = max(
        0.10,
        *(abs(price / baseline_price - 1) for price in key_prices.values()),
    )
    range_points = max(10, int(math.ceil(maximum_move * 20 - 1e-12) * 5))
    range_percent = range_points / 100.0
    percent_steps = (
        list(range(range_points, 10, -5))
        + list(range(10, -11, -1))
        + list(range(-15, -range_points - 1, -5))
    )

    rows_by_price = {}
    for percentage_point in percent_steps:
        underlying_price = round(baseline_price * (1 + percentage_point / 100.0), 2)
        if underlying_price <= 0:
            continue
        rows_by_price.setdefault(underlying_price, {
            "percent_change": percentage_point / 100.0,
            "underlying_price": underlying_price,
            "reference_levels": [],
        })

    for label, price in key_prices.items():
        if price <= 0:
            continue
        row = rows_by_price.setdefault(price, {
            "percent_change": price / baseline_price - 1,
            "underlying_price": price,
            "reference_levels": [],
        })
        row["reference_levels"].append(label)

    return range_percent, sorted(
        rows_by_price.values(),
        key=lambda row: row["underlying_price"],
        reverse=True,
    )


def build_options_thesis_data(
    underlying_symbol: str,
    baseline_price: float,
    strike_price: float,
    entry_premium: float,
    multiplier: int,
    iv: float,
    risk_free_rate: float,
    expiration_date: datetime.date,
    starting_dte: int,
    option_type: str = "PUT",
    quantity: int = 1,
    market_premium: float | None = None,
    dividend_yield: float = 0.0,
    action: str = "BUY",
) -> dict:
    """Build the canonical option-thesis values used by UI and Excel exports."""
    option_type = str(option_type or "PUT").upper()
    if option_type not in {"CALL", "PUT"}:
        raise ValueError("option_type must be CALL or PUT")
    if baseline_price <= 0 or strike_price <= 0:
        raise ValueError("baseline_price and strike_price must be positive")
    if entry_premium < 0 or multiplier <= 0 or starting_dte < 0 or quantity <= 0:
        raise ValueError("entry_premium, multiplier, quantity, or starting_dte is invalid")
    if dividend_yield < 0:
        raise ValueError("dividend_yield cannot be negative")

    action = str(action or "BUY").upper()
    position_direction = -1 if action.startswith("SELL") else 1
    if iv > 0:
        resolved_iv = float(iv)
        iv_source = "Webull contract implied volatility"
    else:
        resolved_iv = _implied_volatility(
            float(market_premium or 0),
            baseline_price,
            strike_price,
            starting_dte,
            risk_free_rate,
            option_type,
            dividend_yield,
        )
        if resolved_iv is None:
            raise ValueError("Implied volatility is unavailable for this contract")
        iv_source = "Derived from the current market mark"

    normalized_symbol = str(underlying_symbol or "OPTION").upper().strip()
    breakeven = strike_price - entry_premium if option_type == "PUT" else strike_price + entry_premium
    scenario_range_percent, scenario_rows = _scenario_prices(
        baseline_price,
        strike_price,
        breakeven,
    )
    date_columns = [
        {
            "dte": dte,
            "date": (expiration_date - datetime.timedelta(days=dte)).isoformat(),
        }
        for dte in range(starting_dte, -1, -1)
    ]
    rows = []
    for scenario in scenario_rows:
        underlying_price = scenario["underlying_price"]
        option_prices = [
            _option_price(
                underlying_price,
                strike_price,
                column["dte"],
                risk_free_rate,
                resolved_iv,
                option_type,
                dividend_yield,
            )
            for column in date_columns
        ]
        rows.append({
            "percent_change": scenario["percent_change"],
            "underlying_price": underlying_price,
            "reference_levels": scenario["reference_levels"],
            "option_prices": option_prices,
            "pnl": [
                (option_price - entry_premium) * multiplier * quantity * position_direction
                for option_price in option_prices
            ],
        })

    breakeven_pct = (1 - breakeven / baseline_price) if option_type == "PUT" else (breakeven / baseline_price - 1)
    return {
        "underlying_symbol": normalized_symbol,
        "option_type": option_type,
        "action": action,
        "scenario_range_percent": scenario_range_percent,
        "scenario_convention": "Current spot is 0%; 1% steps through +/-10%, then 5% tail steps with exact strike and breakeven rows.",
        "assumptions": [
            {"label": f"Baseline {normalized_symbol} price", "value": baseline_price, "format": "currency", "units": "$/share", "note": "Current underlying price"},
            {"label": "Strike", "value": strike_price, "format": "currency", "units": "$/share", "note": f"Selected {option_type} strike"},
            {"label": "Entry premium", "value": entry_premium, "format": "currency", "units": "$/share", "note": "Limit entry price"},
            {"label": "Contract multiplier", "value": multiplier, "format": "number", "units": "shares/contract", "note": "Standard multiplier"},
            {"label": "Contracts", "value": quantity, "format": "number", "units": "contracts", "note": "Selected position size"},
            {"label": "Implied volatility", "value": resolved_iv, "format": "percent", "units": "%", "note": iv_source},
            {"label": "Risk-free rate", "value": risk_free_rate, "format": "percent", "units": "%", "note": "Short-term risk-free rate"},
            {"label": "Expiration date", "value": expiration_date.isoformat(), "format": "date", "units": "date", "note": "Contract expiration"},
            {"label": "Starting DTE", "value": starting_dte, "format": "number", "units": "calendar days", "note": "Days to expiration"},
            {"label": "Dividend yield", "value": dividend_yield, "format": "percent", "units": "%", "note": "Continuous annual yield; zero when unavailable"},
            {"label": "Exercise model", "value": "American CRR binomial", "format": "text", "units": "model", "note": "Early exercise evaluated at every time step"},
            {"label": "Position direction", "value": action, "format": "text", "units": "side", "note": "P&L sign follows the order side"},
        ],
        "key_outputs": [
            {"label": "Total premium at risk", "value": entry_premium * multiplier * quantity, "format": "currency"},
            {"label": "Expiration breakeven", "value": breakeven, "format": "currency"},
            {"label": "Breakeven % from baseline", "value": breakeven_pct, "format": "percent"},
        ],
        "columns": date_columns,
        "rows": rows,
    }


def generate_thesis_excel(
    underlying_symbol: str,
    baseline_price: float,
    strike_price: float,
    entry_premium: float,
    multiplier: int,
    iv: float,
    risk_free_rate: float,
    expiration_date: datetime.date,
    starting_dte: int,
    option_type: str = "PUT",
    quantity: int = 1,
    market_premium: float | None = None,
    dividend_yield: float = 0.0,
    action: str = "BUY",
) -> BytesIO:
    """Generate a workbook from the same canonical American-option thesis as the UI."""
    thesis_data = build_options_thesis_data(
        underlying_symbol=underlying_symbol,
        baseline_price=baseline_price,
        strike_price=strike_price,
        entry_premium=entry_premium,
        multiplier=multiplier,
        iv=iv,
        risk_free_rate=risk_free_rate,
        expiration_date=expiration_date,
        starting_dte=starting_dte,
        option_type=option_type,
        quantity=quantity,
        market_premium=market_premium,
        dividend_yield=dividend_yield,
        action=action,
    )
    underlying_symbol = thesis_data["underlying_symbol"]
    option_type = thesis_data["option_type"]
    assumptions_by_label = {
        item["label"]: item for item in thesis_data["assumptions"]
    }
    resolved_iv = assumptions_by_label["Implied volatility"]["value"]
    iv_note = assumptions_by_label["Implied volatility"]["note"]

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {
        "in_memory": True,
        "use_future_functions": True,
    })
    workbook.set_calc_mode("auto")

    title_format = workbook.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": "#FFFFFF",
        "bg_color": "#1F4E78",
        "align": "left",
        "valign": "vcenter",
    })
    header_format = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#4472C4",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
    })
    header_date_format = workbook.add_format({
        "bold": True,
        "font_color": "#FFFFFF",
        "bg_color": "#4472C4",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
        "num_format": "mmm d, yyyy",
    })
    section_format = workbook.add_format({
        "bold": True,
        "font_color": "#1F1F1F",
        "bg_color": "#D9EAF7",
        "border": 1,
    })
    input_format = workbook.add_format({"bg_color": "#FFF2CC", "border": 1})
    text_format = workbook.add_format({"border": 1})
    note_format = workbook.add_format({"font_color": "#666666", "border": 1})
    currency_format = workbook.add_format({"num_format": "$#,##0.00", "border": 1})
    input_currency_format = workbook.add_format({"num_format": "$#,##0.00", "bg_color": "#FFF2CC", "border": 1})
    percent_format = workbook.add_format({"num_format": "0.00%", "border": 1})
    input_percent_format = workbook.add_format({"num_format": "0.00%", "bg_color": "#FFF2CC", "border": 1})
    date_format = workbook.add_format({"num_format": "mmm d, yyyy", "border": 1, "align": "center"})
    input_date_format = workbook.add_format({"num_format": "yyyy-mm-dd", "bg_color": "#FFF2CC", "border": 1})
    matrix_text_format = workbook.add_format({"border": 1, "align": "center"})

    # 1. Assumptions
    assumptions = workbook.add_worksheet("Assumptions")
    assumptions.set_column("A:A", 30)
    assumptions.set_column("B:C", 18)
    assumptions.set_column("D:D", 58)
    assumptions.set_row(0, 24)
    assumptions.merge_range("A1:D1", f"{underlying_symbol} Options Scenario Model", title_format)
    for column, value in enumerate(["Input", "Value", "Units", "Notes / Source"]):
        assumptions.write(2, column, value, header_format)

    expiry_datetime = datetime.datetime.combine(expiration_date, datetime.time.min)
    inputs = [
        (f"Baseline {underlying_symbol} price", baseline_price, "$/share", "Current underlying price", input_currency_format),
        ("Strike", strike_price, "$/share", f"Selected {option_type} strike", input_currency_format),
        ("Entry premium", entry_premium, "$/share", "Limit entry price", input_currency_format),
        ("Contract multiplier", multiplier, "shares/contract", "Standard multiplier", input_format),
        ("Contracts", quantity, "contracts", "Selected position size", input_format),
        ("Implied volatility", resolved_iv, "%", iv_note, input_percent_format),
        ("Risk-free rate", risk_free_rate, "%", "Short-term risk-free rate", input_percent_format),
        ("Expiration date", expiry_datetime, "date", "Contract expiration", input_date_format),
        ("Starting DTE", starting_dte, "calendar days", "Days to expiration", input_format),
        ("Dividend yield", dividend_yield, "%", "Continuous annual yield; zero when unavailable", input_percent_format),
        ("Exercise model", "American CRR binomial", "model", "Early exercise evaluated at every time step", input_format),
        ("Position direction", thesis_data["action"], "side", "P&L sign follows the order side", input_format),
    ]
    for row, (name, value, units, note, value_format) in enumerate(inputs, start=3):
        assumptions.write(row, 0, name, text_format)
        if isinstance(value, datetime.datetime):
            assumptions.write_datetime(row, 1, value, value_format)
        elif isinstance(value, (int, float)):
            assumptions.write_number(row, 1, value, value_format)
        else:
            assumptions.write(row, 1, value, value_format)
        assumptions.write(row, 2, units, text_format)
        assumptions.write(row, 3, note, note_format)

    total_premium = thesis_data["key_outputs"][0]["value"]
    breakeven = thesis_data["key_outputs"][1]["value"]
    breakeven_pct = thesis_data["key_outputs"][2]["value"]
    key_section_row = 3 + len(inputs)
    assumptions.merge_range(key_section_row, 0, key_section_row, 3, "Key outputs", section_format)
    assumptions.write(key_section_row + 1, 0, "Total premium at risk", text_format)
    assumptions.write_formula(key_section_row + 1, 1, "=B6*B7*B8", currency_format, total_premium)
    assumptions.write(key_section_row + 2, 0, "Expiration breakeven", text_format)
    assumptions.write_formula(
        key_section_row + 2,
        1,
        "=B5-B6" if option_type == "PUT" else "=B5+B6",
        currency_format,
        breakeven,
    )
    assumptions.write(key_section_row + 3, 0, "Breakeven % from baseline", text_format)
    breakeven_cell = f"B{key_section_row + 3}"
    assumptions.write_formula(
        key_section_row + 3,
        1,
        f"=1-({breakeven_cell}/B4)" if option_type == "PUT" else f"=({breakeven_cell}/B4)-1",
        percent_format,
        breakeven_pct,
    )
    assumptions.freeze_panes(3, 0)

    date_columns = [
        (column["dte"], datetime.date.fromisoformat(column["date"]))
        for column in thesis_data["columns"]
    ]
    scenario_rows = thesis_data["rows"]
    pct_steps = [scenario["percent_change"] for scenario in scenario_rows]

    # 2. Option Price Matrix
    price_sheet = workbook.add_worksheet("Option Price Matrix")
    price_sheet.merge_range(0, 0, 0, max(2, len(date_columns) + 1), "Option Price Matrix", title_format)
    price_sheet.write(1, 0, "American CRR values. Rows = spot change; columns = calendar dates remaining.", note_format)
    price_sheet.write(2, 0, "% Change", header_format)
    price_sheet.write(2, 1, "Price", header_format)
    price_sheet.set_column(0, 0, 12)
    price_sheet.set_column(1, 1, 14)
    for column, (dte, date_value) in enumerate(date_columns, start=2):
        price_sheet.set_column(column, column, 15)
        price_sheet.write_number(1, column, dte, note_format)
        price_sheet.write_datetime(2, column, datetime.datetime.combine(date_value, datetime.time.min), header_date_format)
        price_sheet.set_column(column, column, 15, date_format)

    cached_option_prices = {}
    for row, pct in enumerate(pct_steps, start=3):
        excel_row = row + 1
        scenario = scenario_rows[row - 3]
        scenario_price = scenario["underlying_price"]
        price_sheet.write_number(row, 0, pct, percent_format)
        if scenario["reference_levels"]:
            price_sheet.write_comment(row, 0, ", ".join(scenario["reference_levels"]))
        price_sheet.write_formula(row, 1, f"=ROUND('Assumptions'!$B$4*(1+A{excel_row}),2)", currency_format, scenario_price)
        for column, _ in enumerate(date_columns, start=2):
            cached_value = scenario["option_prices"][column - 2]
            cached_option_prices[(row, column)] = cached_value
            price_sheet.write_number(row, column, cached_value, currency_format)
    price_sheet.freeze_panes(3, 2)

    # 3. P&L Matrix
    pnl_sheet = workbook.add_worksheet("P&L Matrix")
    pnl_sheet.merge_range(0, 0, 0, max(2, len(date_columns) + 1), "P&L Matrix", title_format)
    pnl_sheet.write(2, 0, "% Change", header_format)
    pnl_sheet.write(2, 1, "Price", header_format)
    pnl_sheet.set_column(0, 0, 12)
    pnl_sheet.set_column(1, 1, 14)
    for column, (_, date_value) in enumerate(date_columns, start=2):
        pnl_sheet.set_column(column, column, 15)
        pnl_sheet.write_datetime(2, column, datetime.datetime.combine(date_value, datetime.time.min), header_date_format)

    cached_pnl = {}
    for row, pct in enumerate(pct_steps, start=3):
        excel_row = row + 1
        scenario = scenario_rows[row - 3]
        scenario_price = scenario["underlying_price"]
        pnl_sheet.write_number(row, 0, pct, percent_format)
        pnl_sheet.write_formula(row, 1, f"='Option Price Matrix'!B{excel_row}", currency_format, scenario_price)
        for column, _ in enumerate(date_columns, start=2):
            excel_column = xl_col_to_name(column)
            option_price_value = cached_option_prices[(row, column)]
            pnl_value = scenario["pnl"][column - 2]
            cached_pnl[(row, column)] = pnl_value
            unsigned_formula = (
                f"=('Option Price Matrix'!{excel_column}{excel_row}-'Assumptions'!$B$6)"
                "*'Assumptions'!$B$7*'Assumptions'!$B$8"
            )
            formula = f"=-({unsigned_formula[1:]})" if thesis_data["action"].startswith("SELL") else unsigned_formula
            pnl_sheet.write_formula(row, column, formula, currency_format, pnl_value)
    pnl_sheet.conditional_format(3, 2, 3 + len(pct_steps) - 1, 2 + len(date_columns) - 1, {
        "type": "cell", "criteria": ">", "value": 0,
        "format": workbook.add_format({"font_color": "#006100", "bg_color": "#C6EFCE"}),
    })
    pnl_sheet.conditional_format(3, 2, 3 + len(pct_steps) - 1, 2 + len(date_columns) - 1, {
        "type": "cell", "criteria": "<", "value": 0,
        "format": workbook.add_format({"font_color": "#9C0006", "bg_color": "#FFC7CE"}),
    })
    pnl_sheet.freeze_panes(3, 2)

    # 4. Combined View
    combined_sheet = workbook.add_worksheet("Combined View")
    combined_sheet.merge_range(0, 0, 0, max(2, len(date_columns) + 1), "Combined View", title_format)
    combined_sheet.write(2, 0, "% Change", header_format)
    combined_sheet.write(2, 1, "Price", header_format)
    combined_sheet.set_column(0, 0, 12)
    combined_sheet.set_column(1, 1, 14)
    for column, (_, date_value) in enumerate(date_columns, start=2):
        combined_sheet.set_column(column, column, 20)
        combined_sheet.write_datetime(2, column, datetime.datetime.combine(date_value, datetime.time.min), header_date_format)

    for row, pct in enumerate(pct_steps, start=3):
        excel_row = row + 1
        scenario = scenario_rows[row - 3]
        scenario_price = scenario["underlying_price"]
        combined_sheet.write_number(row, 0, pct, percent_format)
        combined_sheet.write_formula(row, 1, f"='Option Price Matrix'!B{excel_row}", currency_format, scenario_price)
        for column, _ in enumerate(date_columns, start=2):
            excel_column = xl_col_to_name(column)
            option_reference = f"'Option Price Matrix'!{excel_column}{excel_row}"
            pnl_reference = f"'P&L Matrix'!{excel_column}{excel_row}"
            formula = (
                f'=TEXT({option_reference},"$0.00")&" / "&'
                f'IF({pnl_reference}>0,"+$"&TEXT({pnl_reference},"#,##0"),'
                f'IF({pnl_reference}<0,"-$"&TEXT(ABS({pnl_reference}),"#,##0"),"$0"))'
            )
            cached_text = f"${cached_option_prices[(row, column)]:,.2f} / {_pnl_display(cached_pnl[(row, column)])}"
            combined_sheet.write_formula(row, column, formula, matrix_text_format, cached_text)
    combined_sheet.freeze_panes(3, 2)

    workbook.close()
    output.seek(0)
    return output
