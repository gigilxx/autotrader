# KIS 연동 레퍼런스 (공식 저장소 기준)

출처: 한국투자증권 공식 저장소 `koreainvestment/open-trading-api`
(2025~2026 샘플 기준). **KIS는 예고 없이 사양을 바꿀 수 있으니 운영 전 재확인할 것.**

## 도메인
| 환경 | Base URL | 호출 최소 간격 |
|---|---|---|
| 실전(real/prod) | `https://openapi.koreainvestment.com:9443` | 0.05초 |
| 모의(demo/vps)  | `https://openapivts.koreainvestment.com:29443` | 0.5초 |

## 인증
- 토큰 발급: `POST /oauth2/tokenP`
  body: `{grant_type:"client_credentials", appkey, appsecret}` → `access_token`, `expires_in`
- 요청 공통 헤더: `authorization: Bearer {token}`, `appkey`, `appsecret`, `tr_id`, `custtype:"P"`
- hashkey(`/uapi/hashkey`)는 현재 **선택**(변조 우려 시 사용).

## 엔드포인트 / tr_id
| 기능 | Method · Path | 실전 tr_id | 모의 tr_id |
|---|---|---|---|
| 현금 매수 | POST `/uapi/domestic-stock/v1/trading/order-cash` | `TTTC0012U` | `VTTC0012U` |
| 현금 매도 | POST `/uapi/domestic-stock/v1/trading/order-cash` | `TTTC0011U` | `VTTC0011U` |
| 주식 잔고조회 | GET `/uapi/domestic-stock/v1/trading/inquire-balance` | `TTTC8434R` | `VTTC8434R` |
| 현재가 | GET `/uapi/domestic-stock/v1/quotations/inquire-price` | `FHKST01010100` | (동일) |

> ⚠️ 정정: 과거에 흔히 쓰이던 `TTTC0802U`(매수)·`TTTC0801U`(매도)는 **구버전**.
> 현재 공식 샘플은 `TTTC0012U`/`TTTC0011U`를 사용한다.

## 주문 바디 (order-cash, 키 대문자)
`CANO`, `ACNT_PRDT_CD`, `PDNO`(종목코드), `ORD_DVSN`(00:지정가, 01:시장가 # VERIFY),
`ORD_QTY`(문자열), `ORD_UNPR`(문자열, 지정가일 때 가격), `EXCG_ID_DVSN_CD`("KRX"),
`SLL_TYPE`(매도 시 "01":일반매도), `CNDT_PRIC`("")

## 응답 필드 (# VERIFY: 모의계좌 실응답으로 1회 확인 권장)
- 현재가: `output.stck_prpr`
- 잔고요약: `output2[0].dnca_tot_amt` (예수금총금액)
- 보유종목: `output1[].pdno / hldg_qty / pchs_avg_pric`
- 주문성공: `rt_cd == "0"`

## 설정(환경변수)
`KIS_APPKEY`, `KIS_APPSECRET`, `KIS_CANO`, `KIS_ACNT_PRDT_CD`, `KIS_ENV`(mock|real)
→ `kis_broker.credentials_from_env()`로 로드. **키를 코드/깃에 절대 넣지 말 것.**
