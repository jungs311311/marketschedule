# 증시 일정 텔레그램봇 (GitHub Actions 버전)

한국·일본·미국 증시의 개장/휴장, 옵션 만기, 금리 결정, 지수 리밸런싱, 미국 서머타임을
공식 사이트에서 수집해 텔레그램으로 보내는 봇입니다.

기존 DART 공시봇(`stock_prototype`)과 **완전히 별개**입니다.
봇도 다르고, 저장소도 다르고, 토큰도 다릅니다. 공시봇은 건드리지 않습니다.

## PC를 켜둘 필요가 없습니다

원래 이 프로그램은 "내 PC에서 24시간 켜두는" 방식이었습니다.
이 버전은 공시봇과 똑같이 **GitHub Actions**에서 돌아갑니다.
컴퓨터를 꺼도, 노트북을 들고 나가도 알림은 옵니다.

| | 예전 방식 | 지금 방식 |
|---|---|---|
| 실행 위치 | 내 Windows PC | GitHub 서버 |
| PC 꺼도 되나 | ❌ | ✅ |
| 설치할 것 | Python, 자동실행 등록 | 없음 |
| 설정하는 곳 | `.env` 파일 | 저장소 Secrets |

## 알림 시간

| 한국시간 | 내용 |
|---|---|
| 매일 08:00 | 한국·일본 증시, 오늘 밤 미국 증시의 개장/휴장 + 그날 해당하는 국내 이벤트 |
| 매일 21:00 | 오늘 밤 미국장 상태 재확인 + 그날 해당하는 미국 이벤트 |
| 08:20 / 21:20 | 앞 실행이 건너뛰어졌을 때만 대신 발송 (이미 보냈으면 아무것도 안 함) |

이벤트가 없는 날은 이벤트 칸이 통째로 빠집니다. "오늘은 만기 아님" 같은 알림은 안 옵니다.

- 오전에 붙는 것: 국장 옵션 만기, 한국은행 금리 결정, MSCI(한국 관련), 미국 서머타임 전환
- 오후에 붙는 것: 미장 옵션 만기, FOMC, Nasdaq-100·S&P 500 리밸런싱

> GitHub의 무료 스케줄러는 정시에 딱 맞춰 실행되지 않고 보통 몇 분~수십 분 늦습니다.
> 공시봇과 같은 성질이라 이미 아실 거예요. 08:20/21:20 재시도가 그래서 있습니다.

## 설치 순서

### 1. 새 저장소 만들기

GitHub에서 **새 저장소**를 만듭니다 (예: `market-calendar-bot`).
`stock_prototype`에 섞지 마세요. 공시봇 워크플로와 충돌합니다.

이 폴더의 파일을 전부 그 저장소에 올립니다.

### 2. 봇 토큰 준비

텔레그램 `@BotFather`에서 만든 **일정봇** 토큰을 준비합니다.
(공시봇 토큰이 아닙니다. 이미 만드셨다면 그걸 씁니다.)

그 봇 채팅방을 열어 `/start`를 한 번 보냅니다. 이걸 안 하면 CHAT_ID를 못 가져옵니다.

### 3. Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| 이름 | 값 |
|---|---|
| `MARKET_BOT_TOKEN` | BotFather가 준 토큰 |
| `MARKET_BOT_CHAT_ID` | 4단계에서 확인 (일단 비워두고 진행) |

### 4. CHAT_ID 확인

저장소 → **Actions → market-calendar-bot → Run workflow**
→ 작업 선택에서 **`chat-id`** → 실행

실행이 끝나면 로그의 `실행` 단계에 숫자가 하나 찍힙니다. 그게 CHAT_ID입니다.
그 값을 `MARKET_BOT_CHAT_ID` Secret에 등록합니다.

> 숫자가 안 나오면 봇에게 `/start`를 아직 안 보낸 겁니다.

### 5. 쓰기 권한 켜기

저장소 → **Settings → Actions → General → Workflow permissions**
→ **Read and write permissions** 선택 → Save

봇이 수집한 일정을 `state/state.json`에 저장하려면 필요합니다.
(공시봇 때 하셨던 것과 같은 설정입니다.)

### 6. 연결 확인

**Actions → Run workflow → `test-message`** 실행.
텔레그램에 `[연결 확인]` 메시지가 오면 끝입니다.

이후로는 아무것도 안 해도 매일 08:00과 21:00에 알림이 옵니다.

## 확인하고 싶을 때

**Actions → Run workflow**에서 골라 실행합니다. 전부 수동입니다.

| 작업 | 하는 일 |
|---|---|
| `once` | 지금 갱신하고 지금 시간대 알림을 보냄 |
| `render-morning` | 오늘 오전 메시지를 **보내지 않고** 로그에만 출력 |
| `render-evening` | 오늘 오후 메시지를 보내지 않고 로그에만 출력 |
| `refresh` | 공식 일정만 다시 수집 (발송 안 함) |
| `status` | 저장된 일정 개수와 수집 경고 확인 |
| `chat-id` / `bot-info` / `test-message` | 연결 관련 |

`status`의 WARNING은 고장이 아니라 **"아직 공식 발표가 없다"** 는 기록인 경우가 많습니다.
예: 2027년 한국은행 일정, 2027년 Cboe 만기 캘린더는 아직 발표 전이라
없는 일정을 지어내지 않고 매번 다시 확인합니다.

## 폴더 설명

```
.github/workflows/market-calendar.yml   실행 시간표 (여기만 고치면 알림 시간이 바뀜)
marketbot/                              프로그램 본체
  providers/markets.py                  KRX·NYSE·JPX 휴장일
  providers/monetary.py                 한국은행·FOMC·서머타임
  providers/options.py                  국장/미장 옵션 만기
  providers/rebalances.py               MSCI·Nasdaq-100·S&P 500
  render.py                             텔레그램 메시지 문구
  snapshot.py                           수집 결과를 state.json에 보관
state/state.json                        수집해둔 일정 + 발송 이력 (봇이 자동으로 커밋)
tests/                                  검사 13개
```

`state/state.json`에는 이미 실제로 수집된 일정이 들어 있습니다.
그래서 공식 사이트가 잠깐 안 열려도 "확인 불가"로 무너지지 않고 마지막 확인값을 씁니다.

## 알림 시간을 바꾸고 싶으면

`.github/workflows/market-calendar.yml`의 `cron`만 고칩니다. **UTC 기준**입니다.

```
한국시간 = UTC + 9시간
08:00 KST → '0 23 * * *'   (전날 23:00 UTC)
21:00 KST → '0 12 * * *'
```

## 로컬 PC에서 돌리고 싶다면

GitHub Actions 없이 PC에서도 돌아갑니다.

```bash
pip install -r requirements.txt
cp .env.example .env          # 토큰과 CHAT_ID 입력
python -m marketbot chat-id
python -m marketbot test-message
python -m marketbot run       # 상시 실행 스케줄러
```

## 아직 확인 못 한 것

- **GitHub 서버(미국)에서 KRX 접속이 되는지.** 국내 사이트가 해외 IP를 막는 경우가 있습니다.
  첫 `refresh` 실행 후 `status`에서 `한국시장 ... 수집 실패`가 뜨면 알려주세요. 우회 방법이 있습니다.
- 실제 알림이 08:00/21:00에 도착하는 타이밍. 며칠 받아보고 조정하면 됩니다.
- 옵션 만기·리밸런싱 상세 문구는 실제 해당일이 와야 최종 확인됩니다.
  가장 가까운 검증 기회는 **9/10(국장 옵션 만기)**, **9/16(FOMC)**, **9/18(미장 만기 + S&P 리밸런싱)** 입니다.

## 안 하는 것

투자 전망, 매매 추천, 예상 금리는 넣지 않습니다. 일정만 알려줍니다.
