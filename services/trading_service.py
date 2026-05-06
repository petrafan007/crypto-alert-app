from core.extensions import db
from trading_models import AllActivity

def calculate_avg_entry_fifo(user_id, symbol, target_amount=None, dust_threshold_usd=1.0):
    """
    Calculate the weighted-average entry price for the user's *current* holdings of ``symbol``.

    The calculation walks forward through the user's transaction history using FIFO:
    - Buys/receives add new lots at their execution price.
    - Sells/withdrawals consume lots from the front of the queue.
    - Whenever the remaining position is completely closed out or the residual value
      drops below ``dust_threshold_usd`` (default: $1.00), the cost basis resets.

    Returns:
        tuple(avg_entry_price, total_cost_basis, total_amount)
        When no qualifying lots remain the values are (0.0, 0.0, 0.0).
    """
    activities = AllActivity.query.filter_by(user_id=user_id, asset=symbol).order_by(AllActivity.date.asc()).all()

    if not activities:
        return 0.0, 0.0, 0.0

    buys = {'BUY', 'TRANSFER', 'RECEIVE', 'GIFT', 'BONUS'}
    sells = {'SELL', 'WITHDRAWAL', 'SEND'}

    lots = []  # FIFO queue of {"amount": float, "price": float}
    total_amount = 0.0
    total_cost = 0.0

    for activity in activities:
        qty = float(activity.amount or 0.0)
        cost_basis = float(activity.cost_basis or 0.0)
        # proceeds = float(activity.proceeds or 0.0)
        # fee = float(activity.fee or 0.0)
        avg_entry = float(activity.avg_entry or 0.0)
        price_sold_at = float(activity.price_sold_at or 0.0)
        tx_type = activity.type

        if tx_type in buys and qty > 0:
            if avg_entry > 0:
                price = avg_entry
            elif cost_basis > 0:
                price = cost_basis / qty
            elif price_sold_at > 0:
                price = price_sold_at
            else:
                # Fallback: treat as zero-cost transfer
                price = 0.0

            lots.append({"amount": qty, "price": price})
            total_amount += qty
            total_cost += qty * price

        elif tx_type in sells and qty != 0:
            amount_to_remove = abs(qty)

            while amount_to_remove > 0 and lots:
                lot = lots[0]
                removable = min(lot["amount"], amount_to_remove)
                total_amount -= removable
                total_cost -= removable * lot["price"]
                lot["amount"] -= removable
                amount_to_remove -= removable

                if lot["amount"] <= 1e-12:
                    lots.pop(0)

            # If the sell exceeded current lots, wipe everything
            if amount_to_remove > 1e-12:
                lots.clear()
                total_amount = 0.0
                total_cost = 0.0

        # Reset the book if the remaining value is effectively zero
        if total_amount <= 1e-12 or total_cost <= dust_threshold_usd:
            lots.clear()
            total_amount = 0.0
            total_cost = 0.0

    # Align with the actual on-chain/portfolio balance when provided
    if target_amount is not None and total_amount > target_amount + 1e-12:
        excess = total_amount - target_amount
        while excess > 1e-12 and lots:
            lot = lots[0]
            removable = min(lot["amount"], excess)
            total_amount -= removable
            total_cost -= removable * lot["price"]
            lot["amount"] -= removable
            excess -= removable
            if lot["amount"] <= 1e-12:
                lots.pop(0)

    if total_amount <= 0 or total_cost <= 0 or total_cost <= dust_threshold_usd:
        return 0.0, 0.0, 0.0

    avg_entry = total_cost / total_amount
    return avg_entry, total_cost, total_amount

def get_cost_basis_for_asset(user_id, symbol, target_amount=None):
    """
    Returns the cost basis for the *current holdings* of a given asset for the user using FIFO.
    """
    _, cost_basis, _ = calculate_avg_entry_fifo(user_id, symbol, target_amount=target_amount)
    return cost_basis
