"""autotrader: 개인용 한국 주식 자동매매 봇의 '커스텀 로직' 모듈 모음.

지표 계산·API 연동·백테스트 엔진은 검증된 라이브러리를 쓰고,
여기서는 결정·안전 로직만 직접 구현한다. (모의투자 기본)
"""
from .config import AppConfig, CostConfig, RiskConfig, StrategyConfig
from .kill_switch import KillSwitch
from .models import AccountSnapshot, Environment, OrderRequest, Position, Side
from .position_sizing import calc_position_size
from .risk_gate import Decision, RiskGate

__all__ = [
    "AppConfig", "RiskConfig", "CostConfig", "StrategyConfig",
    "KillSwitch", "RiskGate", "Decision",
    "AccountSnapshot", "OrderRequest", "Position", "Side", "Environment",
    "calc_position_size",
]
