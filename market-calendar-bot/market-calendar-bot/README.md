# 텔레그램 증시 일정봇

한국시간 오전 8시와 오후 9시에 시장 상태를 보내고, 해당 날짜에 확정된
옵션 만기·금리 결정·리밸런싱·서머타임 이벤트만 함께 보냅니다.
기존 공시봇과 토큰·프로세스·DB를 공유하지 않습니다.

## 알림 범위

- 오전 08:00 KST: 한국·일본 현물시장과 오늘 밤 미국 현물시장 상태
- 오후 21:00 KST: 오늘 밤 미국 현물시장 상태 재확인
- KOSPI 200 월간 옵션 최종거래일
- 미국 SPX·NDX 표준 월간 AM 결제와 개별주식 표준 월간 옵션
- MSCI, Nasdaq-100, S&P 500 공식 반영 일정
- 한국은행 통화정책방향 결정회의와 FOMC 결정
- 미국 서머타임 시작·종료

미국 옵션 알림은 SPX·NDX 표준 월물의 **구성종목 개장가격 기준 AM 결제**와
개별주식옵션의 **장 마감 종가 기준 자동행사 판단**을 별도 줄로 표시합니다.
SPXW·NDXP 등 PM 결제 지수옵션과 위클리·일일·월말 만기는 기본 범위에서
제외됩니다.

## 1. 새 텔레그램봇 만들기

1. 텔레그램에서 `@BotFather`를 열고 `/newbot`을 보냅니다.
2. 안내에 따라 이름과 username을 정하고 새 토큰을 받습니다.
3. 이 토큰은 새 일정봇 전용으로 사용합니다. 기존 공시봇 토큰은 사용하지 않습니다.

## 2. Windows 설치

이 폴더에는 설치가 완료되어 있습니다. 새 봇과 처음 연결할 때는
`CONNECT-BOT.cmd`를 더블클릭하면 토큰 입력, CHAT_ID 확인, 시험 발송을 순서대로
안내합니다. 토큰은 입력 중 화면에 표시되지 않으며 이 PC의 `.env`에만 저장됩니다.

연결 시험이 끝난 뒤 `INSTALL-AUTORUN.cmd`를 더블클릭하면 Windows 관리자 확인창이
나오고, 승인하면 로그인 시 일정봇이 자동으로 시작됩니다.

다른 PC에 복사해서 처음부터 설치하는 경우에만 아래 설치 명령을 사용하세요.

PowerShell에서 프로젝트 폴더로 이동해 다음을 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

생성된 `.env`를 메모장으로 열어 `MARKET_BOT_TOKEN`에 새 토큰을 넣습니다.
그 뒤 텔레그램에서 새 봇에게 `/start`를 한 번 보내고 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m marketbot chat-id
```

표시된 숫자를 `.env`의 `MARKET_BOT_CHAT_ID`에 넣습니다. 토큰과 CHAT_ID는
채팅이나 Git 저장소에 올리지 마세요.

## 3. 실제 발송 전 확인

공식 자료를 갱신합니다.

```powershell
.\.venv\Scripts\python.exe -m marketbot refresh
```

특정 날짜 메시지를 발송 없이 확인할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m marketbot render --date 2026-09-10 --slot morning
.\.venv\Scripts\python.exe -m marketbot render --date 2026-09-18 --slot evening
```

첫 예시는 KOSPI 200 월간 옵션, 두 번째 예시는 미국 월간 옵션의 장 시작·장
마감 구분을 확인하기 좋습니다. 실제 시험 발송은 다음과 같습니다.

```powershell
.\.venv\Scripts\python.exe -m marketbot send --date 2026-09-18 --slot evening
```

같은 날짜·슬롯은 DB에 기록되어 재시작해도 중복 발송되지 않습니다.

## 4. 계속 실행하기

직접 실행:

```powershell
.\.venv\Scripts\python.exe -m marketbot run
```

Windows 로그인 때 자동으로 시작하려면 관리자 PowerShell에서 실행합니다.

```powershell
.\scripts\install-windows-task.ps1
```

PC가 꺼져 있거나 절전 상태면 알림을 보낼 수 없습니다. 24시간 서버가 있다면
Docker 방식이 더 안정적입니다.

```bash
docker compose up -d --build
```

## 일정 갱신과 안전장치

07:30과 20:30 KST에 공식 자료를 갱신한 뒤 08:00과 21:00에 발송합니다.
공식 연도 일정이 아직 발표되지 않았거나 페이지 해석에 실패하면 날짜를 만들지
않고 `확인 불가` 또는 미확정 일정으로 저장합니다. 미확정 이벤트는 자동 발송하지
않습니다. 이전에 공식 확인된 값이 있고 일시적 수집 장애가 발생하면 마지막 확인값을
유지합니다.

리밸런싱은 발표일·종가 반영일·효력일을 따로 저장합니다. 방법론으로 계산한
예정일은 공식 회차 공지가 확인될 때까지 발송하지 않습니다. 이미 보낸 일정의 같은
이벤트가 변경되면 `[일정 정정]` 메시지를 한 번 보냅니다.

주요 공식 출처는 KRX, NYSE, Nasdaq, JPX, MSCI, Nasdaq Indexes, S&P DJI,
OCC/OIC, Cboe, 한국은행, Federal Reserve, NIST입니다. 현재 상태와 수집 경고는
다음 명령으로 확인합니다.

```powershell
.\.venv\Scripts\python.exe -m marketbot status
Get-Content .\data\marketbot.log -Tail 100
```

## 테스트

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

이 봇의 메시지는 일정 확인용이며 투자 판단이나 주문 기능을 포함하지 않습니다.
