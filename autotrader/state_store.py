"""상태 영속화 고수준 인터페이스.

gate / idem / engine 세 객체를 한 번에 저장·복원하는 편의 함수.
낮은 수준의 StateManager(state.py)를 직접 다루지 않아도 된다.

사용:
    from autotrader.state_store import save_state, load_state

    # 진입·청산 후 명시적 저장 (engine._exit 내부에서도 자동 저장됨)
    save_state(engine.gate, engine.idem, engine)

    # 재시작 시 복원 (engine.prepare_day() 전에 호출)
    load_state(engine.gate, engine.idem, engine, today=date.today())
"""
from __future__ import annotations

from datetime import date


def save_state(gate, idem, engine) -> None:
    """gate, idem, engine의 현재 상태를 state.db에 저장."""
    sm = engine.state
    today: date = engine._today or date.today()
    sm.save_daily_state(today, gate.trades_today, gate.realized_pnl_today)
    for oid in idem._sent:
        sm.add_sent_order(oid, today)
    for sym, loc in engine.local.items():
        sm.save_position(today, sym, loc.entry_price, loc.qty)


def load_state(gate, idem, engine, today: date) -> None:
    """state.db에서 gate, idem, engine 상태를 복원.

    engine.prepare_day() 전에 호출하면 재시작 후 카운터가 이어진다.
    engine.prepare_day()는 내부적으로 같은 복원 로직을 실행하므로,
    이 함수는 prepare_day 없이 상태만 복원해야 할 때(테스트·디버그) 사용한다.
    """
    from .engine import _Local

    sm = engine.state
    engine._today = today

    ds = sm.load_daily_state(today)
    gate.roll_day(today)
    gate._trades_today = ds.trades_today
    gate._realized_pnl_today = ds.realized_pnl_today

    sent = sm.load_sent_orders(today)
    idem._sent.update(sent)

    for pos in sm.load_positions(today):
        engine.local[pos.symbol] = _Local(entry_price=pos.entry_price, qty=pos.qty)
