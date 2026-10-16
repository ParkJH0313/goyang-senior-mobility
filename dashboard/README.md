# 가좌·송포 의료이동 탄소 대시보드

`goyang-senior-mobility` 저장소의 `dashboard/`에서 관리하는 대시보드입니다. 카카오맵과 현재 선택 조건을 설명하는 AI 문답을 제공합니다. 기본 AI 제공자는 **Gemini**, 기본 모델은 **gemini-3.1-flash-lite**입니다. AI 키를 등록하기 전에는 ‘연결 준비 중’을 표시하며 지도와 탄소 계산은 독립적으로 작동합니다.

## 준비된 기능

- 실제 카카오 자동차 왕복거리와 기존 탄소 계산식, 지원 범위 472/496/902명 유지.
- 질문 당시 선택 조건을 서버에서 검증하고 같은 `dist/model.js`로 다시 계산.
- 조건 비교 질문에는 `calculate_scenario` 함수 호출. 비교 카드는 실제 함수의 반환값을 표시하며 화면 조건을 자동 변경하지 않음.
- 답변 스트리밍, 중지, 대화 지우기, 추천 질문, 근거 페이지의 [S1]~[S6] 출처 링크.
- API 키는 서버 환경변수로만 사용. 공개 `/config.js`에는 지도용 JavaScript 키만 전달.
- 세션별 대화 분리, 입력 1,200자 제한, 기본 세션당 10분 8회 / 서버 전체 UTC 하루 100문답 / 동시 2문답 제한.
- Render용 `PORT`, `0.0.0.0`, `/healthz`, `render.yaml`, 패키지 잠금 파일.

외부 AI 응답 품질과 계정별 이용 가능 여부는 실제 키 등록 후 확인해야 합니다. 현재 검증은 모의 API 응답을 이용한 연결·계산·오류 처리 검증입니다.

## 로컬 실행

Node.js 22.16 이상(권장 24)이 필요합니다. Python, GIS 프로그램, Streamlit, 별도 데이터베이스 설치는 필요하지 않습니다.

Windows PowerShell에서 저장소 루트의 `dashboard` 폴더로 이동한 뒤 실행합니다.

```powershell
cd dashboard
.\start-local.ps1
```

기존 환경변수에 없는 키만 화면에 보이지 않게 입력받습니다. 키를 파일에 저장하지 않습니다. Gemini 키 입력을 건너뛰면 지도·계산과 문답창의 연결 대기 상태를 확인할 수 있습니다. 실행 후 `http://localhost:8080`으로 접속합니다. 카카오 앱의 JavaScript SDK 도메인에도 이 주소를 등록해야 합니다.

이미 환경변수를 등록했다면 모든 OS에서 다음으로 실행할 수 있습니다.

```text
npm ci --omit=dev
npm start
```

`npm start`는 `dashboard/.env`가 있으면 읽을 수 있지만 실제 키 파일은 배포 소스에 포함하지 않습니다. 실행창을 닫으면 로컬 서버는 종료됩니다.

## Gemini 키 등록

1. [Google AI Studio API Keys](https://aistudio.google.com/apikey)에서 프로젝트를 선택하고 키를 발급합니다.
2. 로컬은 실행창의 키 입력 또는 환경변수 `GEMINI_API_KEY`를 사용합니다.
3. Render는 서비스의 **Environment → Add Environment Variable**에서 `GEMINI_API_KEY`를 등록하고 재배포합니다.
4. `AI_PROVIDER=gemini`, `GEMINI_MODEL=gemini-3.1-flash-lite`를 확인합니다.

기본 모델은 공식 문서에 공개된 stable 모델입니다. 계정의 모델 접근·무료 쿼터는 별도 확인해야 합니다. 화면이 ‘연결됨’이어도 실제 API 인증·과금·한도는 첫 문답으로 확인됩니다. 무료 한도 초과 시 자동으로 다른 공급자로 넘어가거나 유료 결제를 생성하지 않습니다.

OpenAI를 사용하려면 `AI_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-6-luna`로 바꿉니다. 두 제공자의 키는 서로 대체하지 않습니다.

## Render에 배포

배포 저장소는 **ParkJH0313/goyang-senior-mobility**, 실행 기준 폴더는 **dashboard**입니다. Blueprint 설정은 저장소 루트의 [`render.yaml`](../render.yaml)에 있습니다.

1. Render 서비스의 연결 저장소를 `ParkJH0313/goyang-senior-mobility`, 브랜치를 `main`, Root Directory를 `dashboard`로 설정합니다.
2. 기존 서비스는 아래 빌드·시작 명령을 유지합니다. Blueprint로 구성할 경우 저장소 루트의 `render.yaml`을 사용하며, 기존 서비스와 같은 이름과 무료 플랜을 지정합니다.
3. 생성 과정에서 `KAKAO_JAVASCRIPT_KEY`, `KAKAO_REST_API_KEY`를 입력합니다. Gemini 키는 발급 후 Environment에서 추가해도 됩니다.
4. 생성된 `https://서비스이름.onrender.com` 주소를 카카오 앱의 **JavaScript SDK 도메인**에 등록합니다.
5. `/healthz`가 `{"status":"ok"}`를 반환하는지 확인하고 실제 대시보드를 엽니다. 서비스 주소는 Render의 `RENDER_EXTERNAL_URL`에서 자동으로 읽습니다. 자체 도메인을 쓰면 `APP_ORIGIN=https://본인도메인`을 추가합니다(마지막 `/` 제외).
6. AI 키 등록 후 ‘왜 472명인가요?’, ‘재차인원 3명이면?’, ‘이 값은 전체 사업 감축인가요?’를 질문해 답변과 화면의 계산값을 비교합니다.

Blueprint 대신 **New → Web Service**로 만들 때는 아래 값을 사용합니다.

| 항목 | 값 |
|---|---|
| Runtime | Node |
| Root Directory | `dashboard` |
| Build Command | `npm ci --omit=dev` |
| Start Command | `npm start` |
| Health Check Path | `/healthz` |
| 환경변수 | `../render.yaml`의 목록 참고. 실제 배포에서는 `HOST=0.0.0.0`, `PORT`는 Render 제공값 |

웹사이트 주소를 공유하면 방문자는 설치나 API 키 입력 없이 이용합니다. API 호출 비용은 배포자의 계정에 발생합니다. 현재 구성은 단일 서버용이며 대화·횟수 제한·거리 캐시는 서버 재시작 때 초기화됩니다. 따라서 앱의 횟수 제한은 월 결제금액의 강제 상한이 아닙니다. 대규모 공개 운영에는 공유 저장소 기반 제한이 추가로 필요합니다.

## 자료·계산 범위

`dist/data.json`은 이 대시보드에서 확인한 Step7/8의 가좌·송포 41격자와 Step2의 121개 출발점을 담은 고정 스냅샷입니다. 본 분석을 다시 실행해도 자동으로 바뀌지 않습니다. 업데이트할 때 472/496/902명, 격자수24/26/41, 출발점66/73/121의 일치 여부를 먼저 확인합니다.

거리 응답은 서버 메모리에서만 재사용하며 배포 파일에 저장하지 않습니다. 서버 재시작 뒤 첫 조회에서 목적지별 10개의 카카오 배치 요청(121개 출발점 × 왕복)이 발생합니다. 슬라이더를 바꾸거나 지원 범위를 바꿀 때는 추가 요청하지 않습니다. 조회 실패 후 1분간 재시도를 늦춰 반복 호출을 줄입니다.

결과는 **택시·자가용에서 전환한 고령자의 의료 왕복통행에 배분된 탄소효과**입니다. DRT 전체 사업 감축, 실제 운행노선, 접근성 개선 실적이 아닙니다. AI 지식은 `knowledge.cjs`에 정리한 기준과 계산 도구로 제한합니다. 기준을 수정할 때 `dist/about.html`, `knowledge.cjs`, `dist/model.js`를 함께 점검합니다.

## 검증

```text
npm test
npm run check
```

서버 테스트는 외부 API를 호출하지 않습니다. Gemini/OpenAI 도구 호출, 서버 재계산, 대화 분리, 키 미등록·한도·잘못된 입력·연결 중지·SSE 처리 등을 모의 응답으로 검사합니다.

선택적인 브라우저 검증은 Playwright 설치 환경에서 `node test/ui-check.cjs`로 실행합니다. `PLAYWRIGHT_MODULE`, `CHROME_PATH`, `TEST_BASE_URL`로 실행 환경을 지정할 수 있습니다. AI 응답은 모의 응답이며 지도·거리의 로컬 서버는 실제 연결을 사용합니다. 검증 이미지와 JSON은 Git에서 제외한 `artifacts/`에 저장됩니다.

## 공식 문서

- [Gemini 모델](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [함수 호출](https://ai.google.dev/gemini-api/docs/generate-content/function-calling), [키 발급](https://ai.google.dev/gemini-api/docs/api-key)
- [OpenAI 함수 호출](https://developers.openai.com/api/docs/guides/function-calling)
- [Render 웹서비스](https://render.com/docs/web-services), [Blueprint 설정](https://render.com/docs/blueprint-spec)
- [카카오맵 앱 설정](https://developers.kakao.com/docs/ko/kakaomap/common)
