"""Global trading mode (Real / Paper / QSE) & mode-aware Dashboard/Orders APIs.

Provides:
  - GET/POST /api/global-mode (persisted site-wide mode synced with broker flags)
  - GET /api/dashboard/paper-portfolio (merged Webull test + Binance paper)
  - GET /api/dashboard/paper-watchlist, /paper-watchlist-live, /add, /remove
    (strictly isolated to paper_watchlist_items)
  - GET /api/dashboard/qse-portfolio & /qse-watchlist (admin-only, GET-only,
    pure read models with zero database writes)
  - GET /api/dashboard/orders?mode=paper|qse (mode-scoped global orders feed)
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import re

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from core.extensions import db
from credentials import UserSetting
from event_algo import is_event_strategy_admin
from models import PaperWatchlistItem, WebullTestPosition
from portfolio_algo_models import (
    DEFAULT_QUANT_WATCHLISTS,
    PortfolioEngineState,
    PortfolioStrategyAccount,
    PortfolioStrategyConfig,
    PortfolioStrategyLot,
    PortfolioStrategyOrder,
    PortfolioStrategyPosition,
)
from routes.portfolio_algo import _quant_account_mapping, portfolio_admin_required
from trading_models import TestOrder, TestPortfolio, TradingSettings

logger = logging.getLogger(__name__)

dashboard_modes_bp = Blueprint('dashboard_modes', __name__)

VALID_GLOBAL_MODES = ('real', 'paper', 'qse')
OPEN_TEST_ORDER_STATUSES = {'NEW', 'ACTIVE', 'PARTIALLY_FILLED', 'TRIGGERED'}
OPEN_WEBULL_TEST_STATUSES = {'Working', 'Open', 'WORKING', 'OPEN', 'NEW', 'PENDING', 'SUBMITTED'}
OPEN_QUANT_ORDER_STATUSES = {'OPEN', 'WORKING', 'PENDING', 'NEW', 'SUBMITTED'}
QSE_MODULE_ORDER = ['equities', 'options', 'crypto', 'futures', 'events']


def resolve_global_mode(user, setting=None):
    """Return the effective global mode for `user`, coercing QSE to real for non-admins."""
    if setting is None and user is not None:
        setting = UserSetting.query.filter_by(user_id=user.id).first()
    raw = str(getattr(setting, 'global_trading_mode', None) or 'real').strip().lower()
    if raw not in VALID_GLOBAL_MODES:
        raw = 'real'
    if raw == 'qse' and not is_event_strategy_admin(user):
        return 'real'
    return raw


@dashboard_modes_bp.route('/api/global-mode', methods=['GET'])
@login_required
def api_get_global_mode():
    setting = UserSetting.query.filter_by(user_id=current_user.id).first()
    t_settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
    mode = resolve_global_mode(current_user, setting)
    return jsonify({
        'success': True,
        'mode': mode,
        'is_admin': bool(is_event_strategy_admin(current_user)),
        'webull_test_mode_enabled': bool(getattr(setting, 'webull_test_mode_enabled', False)),
        'binance_test_mode_enabled': bool(getattr(t_settings, 'test_mode_enabled', False)),
    })


@dashboard_modes_bp.route('/api/global-mode', methods=['POST'])
@login_required
def api_set_global_mode():
    data = request.get_json(silent=True) or {}
    mode = str(data.get('mode') or '').strip().lower()
    if mode not in VALID_GLOBAL_MODES:
        return jsonify({
            'success': False,
            'error': 'Invalid mode. Must be real, paper, or qse.',
        }), 400
    if mode == 'qse' and not is_event_strategy_admin(current_user):
        return jsonify({
            'success': False,
            'error': 'Administrator privilege required for Quantitative Strategy Engine mode.',
        }), 403

    setting = UserSetting.query.filter_by(user_id=current_user.id).first()
    if not setting:
        setting = UserSetting(user_id=current_user.id)
        db.session.add(setting)

    t_settings = TradingSettings.query.filter_by(user_id=current_user.id).first()
    if not t_settings:
        t_settings = TradingSettings(
            user_id=current_user.id,
            test_mode_enabled=(mode == 'paper'),
            max_order_size_usd=0.0,
            require_2fa=False,
        )
        db.session.add(t_settings)

    setting.global_trading_mode = mode
    # Keep persisted broker paper flags synchronized with global mode:
    # paper -> both enabled; real or qse -> both disabled (QSE is read-only).
    is_paper = (mode == 'paper')
    setting.webull_test_mode_enabled = is_paper
    t_settings.test_mode_enabled = is_paper
    db.session.commit()

    return jsonify({
        'success': True,
        'mode': mode,
        'is_admin': bool(is_event_strategy_admin(current_user)),
        'webull_test_mode_enabled': is_paper,
        'binance_test_mode_enabled': is_paper,
    })


def _serialize_paper_watchlist_item(item, current_price=None, change_24h=None):
    is_webull = item.provider == 'webull'
    inst = (item.instrument_type or ('EQUITY' if is_webull else 'CRYPTO')).upper()
    asset_type = 'stock' if inst == 'EQUITY' else 'crypto'
    return {
        'id': f'paper-wl-{item.id}',
        'raw_id': item.id,
        'symbol': item.symbol,
        'provider': item.provider,
        'source': 'webull_test' if is_webull else 'binance_paper',
        'source_label': 'Webull Paper' if is_webull else 'Binance.US Paper',
        'instrument_type': inst,
        'asset_type': asset_type,
        'is_external': is_webull,
        'is_paper': True,
        'display_name': item.display_name or item.symbol,
        'current_price': current_price,
        'change_24h': change_24h,
        'created_at': item.created_at.isoformat() + 'Z' if item.created_at else None,
    }


def _fetch_live_paper_price(provider, symbol, instrument_type, user_id):
    """Fetch a live quote for a paper watchlist or QSE watchlist symbol."""
    sym = str(symbol or '').upper().strip()
    inst = str(instrument_type or 'EQUITY').upper().strip()
    if inst == 'CRYPTO' or provider == 'binance':
        from services.binance_service import fetch_binance_price
        price = fetch_binance_price(sym)
        return float(price) if price and float(price) > 0 else None
    from routes.portfolio import _fetch_stock_price_yf
    price = _fetch_stock_price_yf(sym, user_id=user_id)
    return float(price) if price and float(price) > 0 else None


@dashboard_modes_bp.route('/api/dashboard/paper-portfolio', methods=['GET'])
@login_required
def api_dashboard_paper_portfolio():
    """Merged read model of Webull test positions and Binance.US paper holdings."""
    portfolio_rows = []
    pending_orders = []
    webull_complete = True
    binance_complete = True
    webull_total = 0.0
    webull_cash = 0.0
    binance_total = 0.0
    binance_usd = 0.0
    binance_usdt = 0.0

    # 1. Webull test ledger
    try:
        from services.webull_paper_trading_service import (
            get_webull_test_account_summary,
            get_webull_test_orders,
            get_webull_test_positions,
        )
        hidden_wb_ids = {
            row.id for row in WebullTestPosition.query.filter_by(
                user_id=current_user.id, hidden=True
            ).all()
        }
        wb_summary = get_webull_test_account_summary(current_user.id) or {}
        webull_total = float(wb_summary.get('net_liquidation') or 0.0)
        webull_cash = float(wb_summary.get('cash_balance') or wb_summary.get('total_cash_balance') or 0.0)

        for pos in get_webull_test_positions(current_user.id) or []:
            raw_id_str = str(pos.get('id') or '').replace('paper_pos_', '')
            if raw_id_str.isdigit() and int(raw_id_str) in hidden_wb_ids:
                continue
            qty = float(pos.get('quantity') or pos.get('amount') or 0.0)
            if qty <= 0:
                continue
            avail = float(pos.get('available_quantity') if pos.get('available_quantity') is not None else qty)
            cost_price = float(pos.get('cost_price') or 0.0)
            curr_price = float(pos.get('current_price') or pos.get('last_price') or 0.0)
            multiplier = int(pos.get('contract_multiplier') or 1)
            cost_basis = round(cost_price * qty * multiplier, 2)
            curr_val = float(pos.get('current_value') if pos.get('current_value') is not None else pos.get('market_value') or (curr_price * qty * multiplier))
            pct_change = float(pos.get('unrealized_profit_loss_rate') or 0.0)
            acct_name = pos.get('account_name') or 'Individual Cash'
            acct_id = pos.get('account_id') or 'TEST_ACC_INDIVIDUAL_CASH'
            inst_type = str(pos.get('instrument_type') or 'EQUITY').upper()
            portfolio_rows.append({
                'id': pos.get('id'),
                'raw_id': int(raw_id_str) if raw_id_str.isdigit() else None,
                'symbol': pos.get('symbol'),
                'underlying_symbol': pos.get('underlying_symbol') or pos.get('symbol'),
                'amount': qty,
                'available_amount': avail,
                'avg_entry': cost_price,
                'current_price': curr_price,
                'current_value': curr_val,
                'cost_basis': cost_basis,
                'pct_change': pct_change,
                'unrealized_pnl': float(pos.get('unrealized_profit_loss') or 0.0),
                'source': 'webull_test',
                'provider': 'webull',
                'is_external': True,
                'is_paper': True,
                'instrument_type': inst_type,
                'asset_type': 'crypto' if inst_type == 'CRYPTO' else 'stock',
                'side': pos.get('side') or 'LONG',
                'account_id': acct_id,
                'webull_account_id': acct_id,
                'webull_account_id_masked': '••••TEST',
                'webull_account_type': f'{acct_name} (Paper)',
                'contract_multiplier': multiplier,
            })

        wb_orders = get_webull_test_orders(current_user.id) or []
        for o in wb_orders:
            if not isinstance(o, dict):
                continue
            status = str(o.get('status') or '')
            if status not in OPEN_WEBULL_TEST_STATUSES:
                continue
            pending_orders.append({
                'id': o.get('order_id') or o.get('id'),
                'order_id': o.get('order_id') or o.get('id'),
                'symbol': o.get('symbol'),
                'base_asset': str(o.get('symbol') or '').upper(),
                'side': str(o.get('side') or 'BUY').upper(),
                'type': o.get('order_type') or 'LIMIT',
                'status': status,
                'quantity': float(o.get('quantity') or 0.0),
                'price': float(o.get('limit_price') or o.get('stop_price') or 0.0),
                'source': 'webull_test',
                'provider': 'webull',
                'account_id': o.get('account_id') or 'TEST_ACC_INDIVIDUAL_CASH',
                'webull_account_id': o.get('account_id') or 'TEST_ACC_INDIVIDUAL_CASH',
                'instrument_type': o.get('instrument_type') or 'EQUITY',
                'is_paper': True,
                'created_at': o.get('created_at'),
            })
    except Exception as exc:
        logger.warning('Paper portfolio Webull test read failed: %s', exc, exc_info=True)
        webull_complete = False

    # 2. Binance paper ledger
    try:
        from services.binance_paper_service import account_summary as binance_paper_summary
        from services.binance_service import fetch_binance_price

        summary = binance_paper_summary(current_user.id) or {}
        bals = summary.get('balances') or {}
        binance_usd = float(bals.get('USD') or 0.0)
        binance_usdt = float(bals.get('USDT') or 0.0)

        holdings = TestPortfolio.query.filter_by(user_id=current_user.id).filter(
            TestPortfolio.quantity > 0
        ).all()

        holdings_value_sum = 0.0
        for h in holdings:
            sym = str(h.symbol or '').upper().strip()
            if not sym or sym in {'USD', 'USDT'}:
                continue
            qty = float(h.quantity or 0.0)
            if qty <= 0:
                continue
            avg_price = float(h.avg_entry_price or 0.0)
            cost_basis = float(h.total_cost_basis or (avg_price * qty))
            curr_price = None
            try:
                p = fetch_binance_price(sym)
                curr_price = float(p) if p and float(p) > 0 else None
            except Exception as price_err:
                logger.debug('Binance paper price lookup failed for %s: %s', sym, price_err)
            if curr_price is None:
                curr_price = avg_price
            curr_val = qty * curr_price
            holdings_value_sum += curr_val
            if bool(getattr(h, 'hidden', False)):
                continue
            pnl = curr_val - cost_basis
            pct_change = (pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0
            portfolio_rows.append({
                'id': f'binance-paper-{h.id}',
                'raw_id': h.id,
                'symbol': sym,
                'amount': qty,
                'available_amount': qty,
                'avg_entry': avg_price,
                'current_price': curr_price,
                'current_value': round(curr_val, 2),
                'cost_basis': round(cost_basis, 2),
                'pct_change': round(pct_change, 2),
                'unrealized_pnl': round(pnl, 2),
                'source': 'binance_paper',
                'provider': 'binance',
                'is_external': False,
                'is_paper': True,
                'instrument_type': 'CRYPTO',
                'asset_type': 'crypto',
                'account_label': 'Binance.US Paper',
            })

        binance_total = round(holdings_value_sum + binance_usd + binance_usdt, 2)

        open_test_orders = TestOrder.query.filter_by(user_id=current_user.id).filter(
            TestOrder.status.in_(list(OPEN_TEST_ORDER_STATUSES))
        ).order_by(TestOrder.created_at.desc()).all()
        for o in open_test_orders:
            sym = str(o.symbol or '').upper()
            base = sym[:-4] if sym.endswith('USDT') else (sym[:-3] if sym.endswith('USD') else sym)
            pending_orders.append({
                'id': f'test_{o.id}',
                'order_id': f'test_{o.id}',
                'symbol': sym,
                'base_asset': base,
                'side': str(o.side or 'BUY').upper(),
                'type': o.type or 'LIMIT',
                'status': 'ACTIVE' if o.status in {'NEW', 'ACTIVE', 'PARTIALLY_FILLED'} else o.status,
                'quantity': float(o.quantity or 0.0),
                'price': float(o.price or o.stop_price or 0.0),
                'source': 'binance_paper',
                'provider': 'binance',
                'is_paper': True,
                'created_at': o.created_at.isoformat() + 'Z' if o.created_at else None,
            })
    except Exception as exc:
        logger.warning('Paper portfolio Binance paper read failed: %s', exc, exc_info=True)
        binance_complete = False

    return jsonify({
        'success': True,
        'portfolio': portfolio_rows,
        'account_totals': {
            'all': round(webull_total + binance_total, 2),
            'webull': round(webull_total, 2),
            'binance': round(binance_total, 2),
        },
        'pending_orders': pending_orders,
        'pending_mode': 'paper',
        'sources': {
            'webull_test': {'complete': webull_complete},
            'binance_paper': {'complete': binance_complete},
        },
        'account_detail': {
            'webull_cash': round(webull_cash, 2),
            'binance_usd': round(binance_usd, 2),
            'binance_usdt': round(binance_usdt, 2),
        },
    })


@dashboard_modes_bp.route('/api/dashboard/paper-watchlist', methods=['GET'])
@login_required
def api_dashboard_paper_watchlist():
    """Fast stored paint of the isolated paper watchlist (symbols only, prices null)."""
    rows = (
        PaperWatchlistItem.query
        .filter_by(user_id=current_user.id)
        .order_by(PaperWatchlistItem.symbol.asc(), PaperWatchlistItem.id.asc())
        .all()
    )
    return jsonify([_serialize_paper_watchlist_item(r) for r in rows])


@dashboard_modes_bp.route('/api/dashboard/paper-watchlist-live', methods=['GET'])
@login_required
def api_dashboard_paper_watchlist_live():
    """Isolated paper watchlist patched with live quotes."""
    rows = (
        PaperWatchlistItem.query
        .filter_by(user_id=current_user.id)
        .order_by(PaperWatchlistItem.symbol.asc(), PaperWatchlistItem.id.asc())
        .all()
    )
    if not rows:
        return jsonify([])

    user_id = current_user.id
    prices = {}
    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as executor:
        futures = {
            executor.submit(_fetch_live_paper_price, r.provider, r.symbol, r.instrument_type, user_id): r.id
            for r in rows
        }
        for future in as_completed(futures):
            row_id = futures[future]
            try:
                prices[row_id] = future.result()
            except Exception as exc:
                logger.debug('Paper watchlist live price failed for row %s: %s', row_id, exc)
                prices[row_id] = None

    return jsonify([
        _serialize_paper_watchlist_item(r, current_price=prices.get(r.id), change_24h=None)
        for r in rows
    ])


@dashboard_modes_bp.route('/api/dashboard/paper-watchlist/add', methods=['POST'])
@login_required
def api_dashboard_paper_watchlist_add():
    """Add a symbol to the isolated paper watchlist (idempotent)."""
    data = request.get_json(silent=True) or {}
    provider = str(data.get('provider') or '').strip().lower()
    if provider not in ('webull', 'binance'):
        return jsonify({'success': False, 'error': 'Provider must be webull or binance.'}), 400
    symbol = str(data.get('symbol') or '').strip().upper()
    if not symbol or not re.fullmatch(r'[A-Za-z0-9.\-]{1,30}', symbol):
        return jsonify({'success': False, 'error': 'Enter a valid ticker symbol (1-30 chars).'}), 400
    raw_inst = str(data.get('instrument_type') or '').strip().upper()
    if not raw_inst:
        instrument_type = 'CRYPTO' if provider == 'binance' else 'EQUITY'
    elif raw_inst in ('EQUITY', 'STOCK', 'ETF'):
        instrument_type = 'EQUITY'
    elif raw_inst == 'CRYPTO':
        instrument_type = 'CRYPTO'
    else:
        return jsonify({'success': False, 'error': 'instrument_type must be EQUITY or CRYPTO.'}), 400
    if provider == 'binance':
        instrument_type = 'CRYPTO'
    display_name = str(data.get('display_name') or '').strip()[:200] or None

    existing = PaperWatchlistItem.query.filter_by(
        user_id=current_user.id,
        provider=provider,
        symbol=symbol,
        instrument_type=instrument_type,
    ).first()
    if existing:
        return jsonify({'success': True, 'item': _serialize_paper_watchlist_item(existing), 'created': False})

    item = PaperWatchlistItem(
        user_id=current_user.id,
        provider=provider,
        symbol=symbol,
        instrument_type=instrument_type,
        display_name=display_name,
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'item': _serialize_paper_watchlist_item(item), 'created': True}), 201


@dashboard_modes_bp.route('/api/dashboard/paper-watchlist/remove', methods=['POST'])
@login_required
def api_dashboard_paper_watchlist_remove():
    """Remove a symbol from the current user's isolated paper watchlist."""
    data = request.get_json(silent=True) or {}
    raw_id = data.get('id')
    item = None
    if raw_id is not None:
        id_str = str(raw_id).replace('paper-wl-', '').strip()
        if id_str.isdigit():
            item = PaperWatchlistItem.query.filter_by(
                id=int(id_str), user_id=current_user.id
            ).first()
    if item is None and data.get('symbol'):
        symbol = str(data.get('symbol') or '').strip().upper()
        q = PaperWatchlistItem.query.filter_by(user_id=current_user.id, symbol=symbol)
        if data.get('provider'):
            q = q.filter_by(provider=str(data.get('provider')).strip().lower())
        if data.get('instrument_type'):
            q = q.filter_by(instrument_type=str(data.get('instrument_type')).strip().upper())
        item = q.first()

    if item is None:
        return jsonify({'success': False, 'error': 'Paper watchlist item not found.'}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True, 'removed_id': f'paper-wl-{item.id}'})


@dashboard_modes_bp.route('/api/dashboard/qse-portfolio', methods=['GET'])
@portfolio_admin_required
def api_dashboard_qse_portfolio():
    """Admin-only, GET-only, pure read model over the QSE engine ledger (zero writes)."""
    acc = PortfolioStrategyAccount.query.filter_by(user_id=current_user.id).first()
    state = db.session.get(PortfolioEngineState, current_user.id)

    total_equity = float(acc.total_equity) if acc and acc.total_equity is not None else 50000.0
    cash_balance = float(acc.cash_balance) if acc and acc.cash_balance is not None else total_equity
    initial_balance = float(acc.initial_balance) if acc and acc.initial_balance is not None else 50000.0
    return_pct = ((total_equity / initial_balance - 1.0) * 100.0) if initial_balance > 0 else 0.0

    rows = []
    if state is not None:
        open_lots = (
            PortfolioStrategyLot.query
            .filter_by(user_id=current_user.id, generation=state.generation)
            .filter(PortfolioStrategyLot.closed_at.is_(None))
            .order_by(PortfolioStrategyLot.id.asc())
            .all()
        )
        for lot in open_lots:
            pos = db.session.get(PortfolioStrategyPosition, lot.position_id)
            if pos is None or float(pos.quantity or 0.0) <= 0:
                continue
            acct_id, acct_name = _quant_account_mapping(pos.instrument_type, lot.module)
            cost_basis = float(lot.collateral or 0.0)
            unrealized = float(pos.unrealized_pnl or 0.0)
            market_val = cost_basis + unrealized
            pct_change = (unrealized / cost_basis * 100.0) if cost_basis > 0 else 0.0
            qty = float(pos.quantity or 0.0)
            inst_type = str(pos.instrument_type or 'EQUITY').upper()
            rows.append({
                'id': f'QUANT_POS_{pos.id}',
                'symbol': pos.symbol,
                'module': lot.module,
                'amount': qty,
                'available_amount': qty,
                'avg_entry': float(pos.average_cost or 0.0),
                'current_price': float(pos.market_price or 0.0),
                'current_value': round(market_val, 2),
                'cost_basis': round(cost_basis, 2),
                'pct_change': round(pct_change, 2),
                'unrealized_pnl': round(unrealized, 2),
                'source': 'webull_quant',
                'provider': 'webull',
                'is_external': True,
                'is_paper': True,
                'is_quant': True,
                'read_only': True,
                'instrument_type': inst_type,
                'asset_type': 'crypto' if inst_type == 'CRYPTO' else 'stock',
                'side': pos.side or 'LONG',
                'account_id': acct_id,
                'webull_account_id': acct_id,
                'webull_account_id_masked': '••••QSE',
                'webull_account_type': f'{acct_name} (QSE)',
                'stop_price': lot.stop_price,
                'target_price': lot.target_price,
            })

    open_orders = (
        PortfolioStrategyOrder.query
        .filter_by(user_id=current_user.id)
        .filter(PortfolioStrategyOrder.status.in_(list(OPEN_QUANT_ORDER_STATUSES)))
        .order_by(PortfolioStrategyOrder.created_at.desc())
        .limit(200)
        .all()
    )
    pending_orders = []
    for o in open_orders:
        acct_id, acct_name = _quant_account_mapping(o.instrument_type, o.module_name)
        pending_orders.append({
            'id': f'QUANT_{o.id}',
            'order_id': f'QUANT_{o.id}',
            'symbol': o.symbol,
            'base_asset': str(o.symbol or '').upper(),
            'module': str(o.module_name or '').lower(),
            'side': str(o.side or 'BUY').upper(),
            'type': o.order_type or 'LIMIT',
            'status': o.status,
            'quantity': float(o.quantity or 0.0),
            'price': float(o.price or 0.0),
            'source': 'webull_quant',
            'provider': 'webull',
            'account_id': acct_id,
            'webull_account_id': acct_id,
            'account_name': acct_name,
            'instrument_type': o.instrument_type or 'EQUITY',
            'is_paper': True,
            'is_quant': True,
            'read_only': True,
            'created_at': o.created_at.isoformat() + 'Z' if o.created_at else None,
        })

    return jsonify({
        'success': True,
        'read_only': True,
        'portfolio': rows,
        'account_totals': {
            'all': round(total_equity, 2),
            'webull': round(total_equity, 2),
            'binance': 0.0,
        },
        'pending_orders': pending_orders,
        'pending_mode': 'quant',
        'sources': {
            'webull_quant': {'complete': True},
        },
        'account_detail': {
            'cash_balance': round(cash_balance, 2),
            'initial_balance': round(initial_balance, 2),
            'return_pct': round(return_pct, 2),
        },
    })


@dashboard_modes_bp.route('/api/dashboard/qse-watchlist', methods=['GET'])
@portfolio_admin_required
def api_dashboard_qse_watchlist():
    """Admin-only, GET-only, pure read model over QSE configured watchlists.

    Futures roots and event series ALWAYS emit null price and price_state='none'
    so no synthetic price is ever fabricated for multi-contract roots/series.
    """
    cfg = PortfolioStrategyConfig.query.filter_by(
        user_id=current_user.id, name='Default Multi-Asset Portfolio'
    ).first()
    watchlists = dict(DEFAULT_QUANT_WATCHLISTS)
    if cfg and cfg.watchlists_json:
        try:
            parsed = json.loads(cfg.watchlists_json)
            if isinstance(parsed, dict):
                watchlists.update(parsed)
        except (ValueError, TypeError):
            logger.debug('Could not parse watchlists_json for user %s', current_user.id)

    priced_keys = []
    entries = []
    for mod in QSE_MODULE_ORDER:
        for raw_sym in watchlists.get(mod, []) or []:
            sym = str(raw_sym or '').strip().upper()
            if not sym:
                continue
            entries.append((mod, sym))
            if mod in ('equities', 'options', 'crypto'):
                priced_keys.append((mod, sym))

    price_cache = {}
    unique_to_fetch = list(dict.fromkeys(
        ('crypto' if mod == 'crypto' else 'equity', sym) for mod, sym in priced_keys
    ))
    user_id = current_user.id
    if unique_to_fetch:
        with ThreadPoolExecutor(max_workers=min(8, len(unique_to_fetch))) as executor:
            futures = {
                executor.submit(
                    _fetch_live_paper_price,
                    'binance' if kind == 'crypto' else 'webull',
                    sym,
                    'CRYPTO' if kind == 'crypto' else 'EQUITY',
                    user_id,
                ): (kind, sym)
                for kind, sym in unique_to_fetch
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    price_cache[key] = future.result()
                except Exception as exc:
                    logger.debug('QSE watchlist price fetch failed for %s: %s', key, exc)
                    price_cache[key] = None

    rows = []
    for mod, sym in entries:
        if mod in ('futures', 'events'):
            rows.append({
                'module': mod,
                'symbol': sym,
                'current_price': None,
                'change_24h': None,
                'price_state': 'none',
                'read_only': True,
            })
        else:
            kind = 'crypto' if mod == 'crypto' else 'equity'
            rows.append({
                'module': mod,
                'symbol': sym,
                'current_price': price_cache.get((kind, sym)),
                'change_24h': None,
                'price_state': 'live',
                'read_only': True,
            })

    return jsonify({
        'success': True,
        'read_only': True,
        'module_order': QSE_MODULE_ORDER,
        'rows': rows,
    })


@dashboard_modes_bp.route('/api/dashboard/orders', methods=['GET'])
@login_required
def api_dashboard_orders():
    """Global mode-aware Orders feed for Paper and QSE modes."""
    mode = str(request.args.get('mode') or '').strip().lower()
    if mode not in ('paper', 'qse'):
        return jsonify({'success': False, 'error': 'mode must be paper or qse.'}), 400

    if mode == 'qse':
        if not is_event_strategy_admin(current_user):
            return jsonify({'success': False, 'error': 'Administrator privilege required.'}), 403
        rows = (
            PortfolioStrategyOrder.query
            .filter_by(user_id=current_user.id)
            .order_by(PortfolioStrategyOrder.created_at.desc())
            .limit(500)
            .all()
        )
        open_orders = []
        history_orders = []
        for r in rows:
            acct_id, acct_name = _quant_account_mapping(r.instrument_type, r.module_name)
            status = str(r.status or 'FILLED').upper()
            payload = {
                'id': f'QUANT_{r.id}',
                'order_id': f'QUANT_{r.id}',
                'symbol': r.symbol,
                'instrument_type': r.instrument_type or 'EQUITY',
                'module_name': r.module_name,
                'side': str(r.side or 'BUY').upper(),
                'order_type': r.order_type or 'MARKET',
                'type': r.order_type or 'MARKET',
                'quantity': float(r.quantity or 0.0),
                'filled_quantity': float(r.quantity or 0.0) if status == 'FILLED' else 0.0,
                'price': float(r.price or 0.0),
                'status': status,
                'pnl': r.pnl,
                'source': 'webull',
                'origin': 'webull',
                'webull_account_id': acct_id,
                'account_id': acct_id,
                'webull_account_type': f'{acct_name} (QSE)',
                'is_paper': True,
                'is_quant': True,
                'read_only': True,
                'created_at': r.created_at.isoformat() + 'Z' if r.created_at else None,
            }
            if status in OPEN_QUANT_ORDER_STATUSES:
                open_orders.append(payload)
            else:
                history_orders.append(payload)
        return jsonify({
            'success': True,
            'mode': 'qse',
            'read_only': True,
            'open_orders': open_orders,
            'history_orders': history_orders,
        })

    # mode == 'paper': merge Webull Test orders + Binance Paper TestOrders
    open_orders = []
    history_orders = []
    try:
        from services.webull_paper_trading_service import get_webull_test_orders
        for o in get_webull_test_orders(current_user.id) or []:
            if not isinstance(o, dict):
                continue
            status = str(o.get('status') or '')
            acct_id = o.get('account_id') or 'TEST_ACC_INDIVIDUAL_CASH'
            acct_name = o.get('account_name') or 'Webull Paper'
            payload = {
                'id': o.get('order_id') or o.get('id'),
                'order_id': o.get('order_id') or o.get('id'),
                'symbol': o.get('symbol'),
                'instrument_type': o.get('instrument_type') or 'EQUITY',
                'side': str(o.get('side') or 'BUY').upper(),
                'order_type': o.get('order_type') or 'LIMIT',
                'type': o.get('order_type') or 'LIMIT',
                'quantity': float(o.get('quantity') or 0.0),
                'filled_quantity': float(o.get('filled_quantity') or 0.0),
                'price': float(o.get('filled_price') or o.get('limit_price') or o.get('stop_price') or 0.0),
                'status': status,
                'source': 'webull',
                'origin': 'webull',
                'webull_account_id': acct_id,
                'account_id': acct_id,
                'webull_account_type': f'{acct_name} (Paper)',
                'is_paper': True,
                'is_simulated': True,
                'created_at': o.get('created_at'),
            }
            if status in OPEN_WEBULL_TEST_STATUSES:
                open_orders.append(payload)
            else:
                history_orders.append(payload)
    except Exception as exc:
        logger.warning('Paper orders Webull read failed: %s', exc, exc_info=True)

    try:
        b_orders = (
            TestOrder.query
            .filter_by(user_id=current_user.id)
            .order_by(TestOrder.created_at.desc())
            .limit(500)
            .all()
        )
        for o in b_orders:
            status = str(o.status or 'NEW').upper()
            payload = {
                'id': f'test_{o.id}',
                'order_id': f'test_{o.id}',
                'symbol': o.symbol,
                'instrument_type': 'CRYPTO',
                'side': str(o.side or 'BUY').upper(),
                'order_type': o.type or 'LIMIT',
                'type': o.type or 'LIMIT',
                'quantity': float(o.quantity or 0.0),
                'filled_quantity': float(o.quantity or 0.0) if status == 'FILLED' else 0.0,
                'price': float(o.simulated_fill_price or o.price or o.stop_price or 0.0),
                'status': 'ACTIVE' if status in {'NEW', 'ACTIVE', 'PARTIALLY_FILLED'} else status,
                'source': 'binance',
                'origin': 'binance',
                'account_id': 'BINANCE_PAPER',
                'webull_account_type': 'Binance.US Paper',
                'is_paper': True,
                'is_simulated': True,
                'test_mode': True,
                'created_at': o.created_at.isoformat() + 'Z' if o.created_at else None,
            }
            if status in OPEN_TEST_ORDER_STATUSES:
                open_orders.append(payload)
            else:
                history_orders.append(payload)
    except Exception as exc:
        logger.warning('Paper orders Binance read failed: %s', exc, exc_info=True)

    return jsonify({
        'success': True,
        'mode': 'paper',
        'read_only': False,
        'open_orders': open_orders,
        'history_orders': history_orders,
    })
