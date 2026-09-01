import datetime
import math
from io import BytesIO

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _option_price(
    underlying_price: float,
    strike_price: float,
    dte: int,
    risk_free_rate: float,
    iv: float,
    option_type: str,
) -> float:
    if dte <= 0:
        if option_type == "CALL":
            return max(underlying_price - strike_price, 0.0)
        return max(strike_price - underlying_price, 0.0)

    years = dte / 365.0
    safe_iv = max(float(iv), 0.000000001)
    d1 = (
        math.log(underlying_price / strike_price)
        + (risk_free_rate + 0.5 * safe_iv * safe_iv) * years
    ) / (safe_iv * math.sqrt(years))
    d2 = d1 - safe_iv * math.sqrt(years)

    if option_type == "CALL":
        return (
            underlying_price * _normal_cdf(d1)
            - strike_price * math.exp(-risk_free_rate * years) * _normal_cdf(d2)
        )
    return (
        strike_price * math.exp(-risk_free_rate * years) * _normal_cdf(-d2)
        - underlying_price * _normal_cdf(-d1)
    )


def _pnl_display(value: float) -> str:
    if value > 0:
        return f"+${value:,.0f}"
    if value < 0:
        return f"-${abs(value):,.0f}"
    return "$0"


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
) -> BytesIO:
    """Generate an auditable option thesis workbook with visible cached results.

    Excel does not calculate downloaded workbooks while they remain in Protected
    View. Each derived cell therefore contains both a valid Excel formula and its
    calculated value so all matrices are populated immediately on open.
    """
    option_type = str(option_type or "PUT").upper()
    if option_type not in {"CALL", "PUT"}:
        raise ValueError("option_type must be CALL or PUT")
    if baseline_price <= 0 or strike_price <= 0:
        raise ValueError("baseline_price and strike_price must be positive")
    if entry_premium < 0 or multiplier <= 0 or starting_dte < 0 or quantity <= 0:
        raise ValueError("entry_premium, multiplier, quantity, or starting_dte is invalid")

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
        ("Implied volatility", iv, "%", "IV calibrated to current mark", input_percent_format),
        ("Risk-free rate", risk_free_rate, "%", "Short-term risk-free rate", input_percent_format),
        ("Expiration date", expiry_datetime, "date", "Contract expiration", input_date_format),
        ("Starting DTE", starting_dte, "calendar days", "Days to expiration", input_format),
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

    total_premium = entry_premium * multiplier * quantity
    breakeven = strike_price - entry_premium if option_type == "PUT" else strike_price + entry_premium
    breakeven_pct = (1 - breakeven / baseline_price) if option_type == "PUT" else (breakeven / baseline_price - 1)
    assumptions.merge_range("A13:D13", "Key outputs", section_format)
    assumptions.write("A14", "Total premium at risk", text_format)
    assumptions.write_formula("B14", "=B6*B7*B8", currency_format, total_premium)
    assumptions.write("A15", "Expiration breakeven", text_format)
    assumptions.write_formula("B15", "=B5-B6" if option_type == "PUT" else "=B5+B6", currency_format, breakeven)
    assumptions.write("A16", "Breakeven % from baseline", text_format)
    assumptions.write_formula("B16", "=1-(B15/B4)" if option_type == "PUT" else "=(B15/B4)-1", percent_format, breakeven_pct)
    assumptions.freeze_panes(3, 0)

    date_columns = [
        (dte, expiration_date - datetime.timedelta(days=dte))
        for dte in range(starting_dte, -1, -1)
    ]
    pct_steps = [value / 100.0 for value in range(10, -11, -1)]

    # 2. Option Price Matrix
    price_sheet = workbook.add_worksheet("Option Price Matrix")
    price_sheet.merge_range(0, 0, 0, max(2, len(date_columns) + 1), "Option Price Matrix", title_format)
    price_sheet.write(1, 0, "Rows = Underlying % change. Columns = calendar dates remaining.", note_format)
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
        scenario_price = baseline_price * (1 + pct)
        price_sheet.write_number(row, 0, pct, percent_format)
        price_sheet.write_formula(row, 1, f"='Assumptions'!$B$4*(1+A{excel_row})", currency_format, scenario_price)
        for column, (dte, _) in enumerate(date_columns, start=2):
            excel_column = xl_col_to_name(column)
            underlying_ref = f"$B{excel_row}"
            strike_ref = "'Assumptions'!$B$5"
            time_ref = f"({excel_column}$2/365)"
            safe_time_ref = f"MAX({time_ref},0.00001)"
            rate_ref = "'Assumptions'!$B$10"
            volatility_ref = "MAX('Assumptions'!$B$9,0.000000001)"
            d1 = (
                f"((LN({underlying_ref}/{strike_ref})+({rate_ref}+0.5*{volatility_ref}^2)*{safe_time_ref})"
                f"/({volatility_ref}*SQRT({safe_time_ref})))"
            )
            d2 = f"({d1}-{volatility_ref}*SQRT({safe_time_ref}))"
            if option_type == "CALL":
                calculation = (
                    f"{underlying_ref}*NORM.S.DIST({d1},TRUE)-{strike_ref}*EXP(-{rate_ref}*{time_ref})"
                    f"*NORM.S.DIST({d2},TRUE)"
                )
                intrinsic = f"MAX({underlying_ref}-{strike_ref},0)"
            else:
                calculation = (
                    f"{strike_ref}*EXP(-{rate_ref}*{time_ref})*NORM.S.DIST(-{d2},TRUE)"
                    f"-{underlying_ref}*NORM.S.DIST(-{d1},TRUE)"
                )
                intrinsic = f"MAX({strike_ref}-{underlying_ref},0)"
            formula = f"=IF({excel_column}$2=0,{intrinsic},{calculation})"
            cached_value = _option_price(
                scenario_price,
                strike_price,
                dte,
                risk_free_rate,
                iv,
                option_type,
            )
            cached_option_prices[(row, column)] = cached_value
            price_sheet.write_formula(row, column, formula, currency_format, cached_value)
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
        scenario_price = baseline_price * (1 + pct)
        pnl_sheet.write_number(row, 0, pct, percent_format)
        pnl_sheet.write_formula(row, 1, f"='Option Price Matrix'!B{excel_row}", currency_format, scenario_price)
        for column, _ in enumerate(date_columns, start=2):
            excel_column = xl_col_to_name(column)
            option_price_value = cached_option_prices[(row, column)]
            pnl_value = (option_price_value - entry_premium) * multiplier * quantity
            cached_pnl[(row, column)] = pnl_value
            formula = (
                f"=('Option Price Matrix'!{excel_column}{excel_row}-'Assumptions'!$B$6)"
                "*'Assumptions'!$B$7*'Assumptions'!$B$8"
            )
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
        scenario_price = baseline_price * (1 + pct)
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
