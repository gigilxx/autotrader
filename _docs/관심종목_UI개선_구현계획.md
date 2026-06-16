# 관심종목 UI 개선 구현 계획

> 작성일: 2026-06-16  
> 범위: watchlist 관리 방식 전환 + UI 기능 추가 2종

---

## 배경 및 목적

현재 관심종목은 `.env`의 `WATCHLIST` 환경변수로 관리된다.  
목표: **UI(대시보드) 또는 텔레그램봇에서 종목명/코드로 검색해 추가·제거**하는 방식으로 전환.  
환경변수는 완전히 제거하고 DB(`control_flags.watchlist_override`)를 단일 진실 원천으로 사용한다.

---

## Part 1 — Watchlist 관리 주체 전환 (DB 우선)

### 현재 구조의 문제

```
봇 시작
  └─ run.py:127 → WATCHLIST 환경변수 읽어 초기 watchlist 확정

08:55 prepare_day()
  └─ self.watchlist (= 환경변수에서 읽은 값) 로 목표가 계산

09:00~ on_tick() 내부
  └─ apply_runtime_flags() → DB의 watchlist_override 감지 → watchlist 갱신
```

**문제**: DB의 `watchlist_override`는 `on_tick()` 이후에야 반영된다.  
UI에서 밤새 추가한 종목이 `prepare_day()`(08:55)에 반영되지 않아 목표가 계산이 누락된다.

---

### 변경 내용

#### ① `autotrader/run.py` — 시작 시 DB 우선 조회

```python
# 현재 (run.py:127)
watchlist_env = os.getenv("WATCHLIST", "005930")
watchlist = [s.strip() for s in watchlist_env.split(",") if s.strip()]

# 변경 후
def _load_initial_watchlist() -> list[str]:
    """DB watchlist_override 우선, 없으면 env var(선택), 없으면 빈 목록."""
    try:
        import sqlite3
        cx = sqlite3.connect(os.getenv("STATE_DB", "state.db"), timeout=3)
        row = cx.execute(
            "SELECT value FROM control_flags WHERE key='watchlist_override'"
        ).fetchone()
        cx.close()
        if row and row[0].strip():
            return [s.strip() for s in row[0].split(",") if s.strip()]
    except Exception:
        pass
    wl = os.getenv("WATCHLIST", "")   # 기본값: 빈 목록
    return [s.strip() for s in wl.split(",") if s.strip()]
```

#### ② `autotrader/run.py` — `prepare_day_job()`에 DB 동기화 추가

```python
# 변경 후
def prepare_day_job():
    if not _is_trading_day():
        return
    engine.apply_runtime_flags()   # ← 추가: 08:55 직전 DB watchlist 최신화
    engine.prepare_day()
```

`apply_runtime_flags()`를 먼저 호출해 UI에서 추가한 종목이 `prepare_day()`에 반영되도록 보장한다.

#### ③ `"005930"` fallback 제거 — 3곳

| 파일 | 변경 전 | 변경 후 |
|---|---|---|
| `autotrader/telegram_control.py:54` | `os.getenv("WATCHLIST", "005930")` | `os.getenv("WATCHLIST", "")` |
| `ui/api/main.py:256` | `os.getenv("WATCHLIST", "005930")` | `os.getenv("WATCHLIST", "")` |
| `autotrader/run.py:127` | (위 ①로 대체) | — |

#### ④ `.env.example` — WATCHLIST 항목 주석 처리

```ini
# 관심종목은 UI 대시보드 또는 텔레그램 /watch_add 로 관리합니다
# WATCHLIST=005930
```

---

### 변경 후 흐름

```
봇 시작
  └─ _load_initial_watchlist()
       ├─ DB watchlist_override 조회 → 있으면 사용
       └─ 없으면 WATCHLIST 환경변수 → 없으면 빈 목록

08:55 prepare_day_job()
  ├─ apply_runtime_flags()  → DB 최신 watchlist 동기화 (밤새 UI 추가분 반영)
  └─ prepare_day()          → 동기화된 watchlist 로 목표가 계산

장 중 on_tick() (매 POLL_SEC)
  └─ apply_runtime_flags()  → 실시간 추가·제거 반영 (기존과 동일)
```

---

## Part 2 — UI 기능 추가 2종

---

### 기능 A — 모의투자 종목 수 제한 (최대 4개)

#### 근거

`POLL_SEC=2`, 모의투자 rate limit `0.5초/콜`, `max_workers=2`이지만 `_throttle()` 내부에서 `sleep`이 lock 안에서 실행되어 사실상 직렬.

```
2초(폴링 간격) ÷ 0.5초(콜당 rate limit) = 4종목 상한
```

실전(`KIS_ENV=real`)은 `0.05초/콜` → HTTP 레이턴시 포함 약 10~15종목 허용.

#### 변경 파일

**`ui/api/main.py`**
- 상단에 환경 기반 상수 추가
- `GET /config/env` 엔드포인트 신설
- `POST /watchlist`에 한도 초과 시 HTTP 400

```python
_KIS_ENV = os.getenv("KIS_ENV", "mock").lower()
_MAX_WATCHLIST = 4 if _KIS_ENV != "real" else 40

@app.get("/config/env")
def get_env_config() -> dict:
    return {"env": _KIS_ENV, "max_watchlist": _MAX_WATCHLIST}

@app.post("/watchlist")
def set_watchlist(body: WatchlistBody, _auth=Depends(_require_auth)) -> dict:
    symbols = [s.strip() for s in body.symbols if re.match(r"^\d{6}$", s.strip())]
    if len(symbols) > _MAX_WATCHLIST:
        raise HTTPException(
            400,
            f"{'모의투자' if _KIS_ENV != 'real' else '실전'} 최대 {_MAX_WATCHLIST}종목 "
            f"(요청: {len(symbols)}개)"
        )
    ...
```

**`ui/dashboard/lib/api.ts`**
- `EnvConfig` 인터페이스 추가
- `getEnvConfig()` 메서드 추가

**`ui/dashboard/app/watchlist/page.tsx`**
- 마운트 시 `/config/env` 호출 → `maxWatchlist` 상태 저장
- 헤더에 배지: `모의투자 — 2 / 4`
- `symbols.length >= maxWatchlist` 이면 추가 버튼 `disabled` + 안내 문구 표시

```tsx
// 배지 예시
<span className="text-xs text-yellow-500 bg-yellow-900/30 px-2 py-0.5 rounded">
  {env === "mock" ? "모의투자" : "실전"} — {symbols.length} / {maxWatchlist}
</span>

// 추가 버튼
<button
  onClick={add}
  disabled={loading || symbols.length >= maxWatchlist}
  title={symbols.length >= maxWatchlist ? `최대 ${maxWatchlist}종목 도달` : ""}
>추가</button>
```

#### 종목 제거 시 포지션 보유 확인 (인라인 확인 UI)

브라우저 기본 `confirm()` 대신 **인라인 확인 상태**를 사용한다.  
제거 버튼 클릭 시 해당 종목 카드가 확인 모드로 전환되고,  
사용자가 명시적으로 확인해야만 제거가 진행된다.

**포지션 없는 종목 제거 흐름:**
```
[제거] 클릭 → 즉시 제거 (확인 불필요)
```

**포지션 있는 종목 제거 흐름:**
```
[제거] 클릭
  → 카드가 경고 모드로 전환
  → "⚠️ 보유 포지션이 있습니다. 제거 시 즉시 청산됩니다."
  → [취소]  [청산 후 제거] 버튼 표시
  → [청산 후 제거] 클릭 시만 제거 진행
  → [취소] 또는 외부 클릭 시 원래 상태로 복귀
```

```tsx
// 확인 대기 중인 종목 코드를 저장하는 state
const [pendingRemove, setPendingRemove] = useState<string | null>(null);

function remove(sym: string) {
  const hasPos = positions.some((p) => p.symbol === sym);
  if (hasPos) {
    setPendingRemove(sym);   // 확인 모드 진입
  } else {
    doRemove(sym);           // 포지션 없으면 즉시 제거
  }
}

async function doRemove(sym: string) {
  setPendingRemove(null);
  // POST /watchlist (sym 제외한 목록)
}
```

**`autotrader/telegram_control.py`**
- `/watch_add` 핸들러에서 한도 체크

```python
if cmd == "/watch_add":
    ...
    max_wl = 4 if os.getenv("KIS_ENV", "mock").lower() != "real" else 40
    if len(wl) >= max_wl:
        return f"⛔ 최대 {max_wl}종목 한도 초과 (현재 {len(wl)}개)"
    ...
```

- `/watch_del` 핸들러에서 포지션 보유 여부 안내

텔레그램은 인라인 UI가 없으므로 안내 메시지 → 별도 확인 명령어(`/watch_del_confirm`) 2단계로 처리한다.

```python
_PENDING_WATCH_DEL: dict[int, str] = {}  # chat_id → symbol

if cmd == "/watch_del":
    ...
    # 보유 포지션 확인
    pos_rows = cx.execute(
        "SELECT symbol FROM positions WHERE date=? AND symbol=?", (today, sym)
    ).fetchone()
    if pos_rows:
        _PENDING_WATCH_DEL[chat_id] = sym
        return (
            f"⚠️ {sym} 보유 포지션이 있습니다. 제거 시 즉시 청산됩니다.\n"
            f"/watch_del_confirm {sym}  으로 최종 확인하세요."
        )
    # 포지션 없으면 즉시 제거
    ...

if cmd == "/watch_del_confirm":
    pending = _PENDING_WATCH_DEL.pop(chat_id, None)
    if pending != sym:
        return "먼저 /watch_del {sym} 을 입력하세요."
    # 제거 진행
    ...
```

---

### 기능 B — 종목 검색 자동완성 + 종목명 표시

#### 종목 마스터 데이터 전략

**정적 JSON 번들** (`data/stock_master.json`)을 채택한다.

| 항목 | 내용 |
|---|---|
| 포함 종목 | KOSPI + KOSDAQ 전체 (~2,400개) |
| 파일 크기 | 약 50~60KB |
| 갱신 방법 | `scripts/build_stock_master.py` 실행 (pykrx 사용, 주 1회 권장) |
| FastAPI 처리 | 시작 시 메모리 로드, 이후 인메모리 검색 (API 호출 없음) |

JSON 구조:
```json
[
  {"code": "005930", "name": "삼성전자",  "market": "KOSPI"},
  {"code": "000660", "name": "SK하이닉스","market": "KOSPI"},
  ...
]
```

목록에 없는 코드는 6자리 직접 입력으로 항상 추가 가능 (fallback 유지).

---

#### 변경 파일 목록

| 파일 | 유형 | 주요 변경 |
|---|---|---|
| `data/stock_master.json` | 신규 | KOSPI+KOSDAQ 종목 마스터 |
| `scripts/build_stock_master.py` | 신규 | pykrx로 마스터 생성 스크립트 |
| `ui/api/main.py` | 수정 | JSON 로드 + `/stocks/search` + watchlist name 반환 |
| `ui/dashboard/lib/api.ts` | 수정 | `StockSuggestion` 타입 + `searchStocks()` |
| `ui/dashboard/components/StockAutocomplete.tsx` | 신규 | 재사용 자동완성 컴포넌트 |
| `ui/dashboard/app/watchlist/page.tsx` | 수정 | 자동완성 적용 + 목록에 종목명 표시 |

---

#### `ui/api/main.py` 추가 내용

```python
import json

# 시작 시 로드
_MASTER_PATH = Path(__file__).parent.parent.parent / "data" / "stock_master.json"
try:
    _STOCK_MASTER: list[dict] = json.loads(_MASTER_PATH.read_text(encoding="utf-8"))
except Exception:
    _STOCK_MASTER = []

@app.get("/stocks/search")
def search_stocks(q: str = "") -> dict:
    q = q.strip()
    if not q:
        return {"results": []}
    if q.isdigit():
        results = [s for s in _STOCK_MASTER if s["code"].startswith(q)]
    else:
        results = [s for s in _STOCK_MASTER if q in s["name"]]
    return {"results": results[:10]}
```

`GET /watchlist` 응답에 name 추가:

```python
@app.get("/watchlist")
def get_watchlist() -> dict:
    ...
    name_map = {s["code"]: s["name"] for s in _STOCK_MASTER}
    return {
        "symbols": [
            {"code": sym, "name": name_map.get(sym, sym)}
            for sym in symbols
        ]
    }
```

---

#### `ui/dashboard/components/StockAutocomplete.tsx` 기능

- 입력값이 숫자 → 코드 prefix 검색
- 입력값이 한글/영문 → 이름 substring 검색
- 300ms 디바운스 후 `GET /stocks/search?q=` 호출
- 드롭다운 항목: `삼성전자 (005930) KOSPI`
- 선택 시 `onSelect(code, name)` 콜백 호출
- ESC / 외부 클릭 시 드롭다운 닫힘
- 키보드 ↑↓ 탐색, Enter 선택 지원

```tsx
interface StockSuggestion { code: string; name: string; market: string; }
interface Props {
  onSelect: (code: string, name: string) => void;
  disabled?: boolean;
}
```

---

#### `ui/dashboard/app/watchlist/page.tsx` 변경 후 UI

**평상시:**
```
┌─────────────────────────────────────────────────────┐
│ 관심종목                      모의투자 — 2 / 4       │
├─────────────────────────────────────────────────────┤
│ 종목 추가                                            │
│ ┌──────────────────────────────────────┐ [추가]     │
│ │ 삼성전자 또는 005930 입력            │            │
│ └──────────────────────────────────────┘            │
│   ┌────────────────────────────────┐                │
│   │ 삼성전자    (005930)  KOSPI    │                │
│   │ 삼성물산    (028260)  KOSPI    │                │
│   │ 삼성SDI    (006400)  KOSPI    │                │
│   └────────────────────────────────┘                │
├─────────────────────────────────────────────────────┤
│ 목록 (2개)                                           │
│  삼성전자 005930                  [강제 진입] [제거] │
│  SK하이닉스 000660  보유 10주 @ 180,000원  [청산] [제거] │
└─────────────────────────────────────────────────────┘
```

**SK하이닉스 [제거] 클릭 후 — 인라인 확인 모드:**
```
┌─────────────────────────────────────────────────────┐
│ 목록 (2개)                                           │
│  삼성전자 005930                  [강제 진입] [제거] │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ⚠️  SK하이닉스 000660                           │ │
│ │    보유 포지션이 있습니다. 제거 시 즉시 청산됩니다. │ │
│ │                          [취소]  [청산 후 제거]  │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 구현 순서

| 순서 | 작업 | 파일 |
|---|---|---|
| 1 | Part 1 전체 (DB 우선 전환 + fallback 제거) | `run.py`, `telegram_control.py`, `api/main.py`, `.env.example` |
| 2 | 기능 A (종목 수 제한) | `api/main.py`, `api.ts`, `watchlist/page.tsx`, `telegram_control.py` |
| 3 | `scripts/build_stock_master.py` 작성 + `data/stock_master.json` 생성 | 별도 실행 필요 (`pip install pykrx`) |
| 4 | `GET /stocks/search` + watchlist name 반환 | `api/main.py` |
| 5 | `StockAutocomplete.tsx` 컴포넌트 | 신규 |
| 6 | `watchlist/page.tsx` 자동완성 적용 + 종목명 표시 | `page.tsx`, `api.ts` |

---

## 영향 범위 체크리스트

- [ ] `GET /watchlist` 응답 타입 변경 (`string[]` → `{code, name}[]`) — `api.ts` 타입 및 `page.tsx` 사용처 모두 수정 필요
- [ ] 텔레그램 `/watchlist` 명령은 이름 표시 없음 (state.db에 이름 미저장) — 우선 범위 제외
- [ ] `data/stock_master.json` 미존재 시 FastAPI 정상 기동 보장 (`_STOCK_MASTER = []` fallback 처리)
- [ ] 직접 6자리 코드 입력 → 목록에 없으면 name은 코드 그대로 표시 (fallback)
- [ ] `WATCHLIST` 환경변수는 optional로 유지 (기존 배포 환경 하위호환)
- [ ] 종목 제거 시 포지션 보유 여부 확인 후 인라인 확인(UI) / 2단계 명령어(텔레그램) 처리
- [ ] 텔레그램 `/watch_del_confirm` 명령어 추가 및 `_HELP_TEXT` 업데이트 필요
