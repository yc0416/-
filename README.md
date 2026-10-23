# 우리끼리 갤러리

친구들끼리 사용하는 초대제 커뮤니티 웹 MVP입니다. 첨부된 React 초안에서 확장했습니다.

## 구현된 기능

- 초대 코드 회원가입, 로그인/로그아웃, 7일 세션
- 로그인한 회원만 갤러리와 게시글 열람
- 자유·게임·유머 갤러리, 게시글 검색 및 추천순 정렬
- 게시글 작성, 작성자만 삭제, 익명 표시
- 계정당 하나의 추천/비추천, 반응 변경·취소
- 댓글 작성, 반응과 댓글의 SQLite 영구 저장
- 모바일/데스크톱 반응형 화면

사진은 글당 최대 3장, 한 장당 4MB 이하의 JPG/PNG/WebP를 첨부할 수 있습니다. 서버에서 20MP 이하 이미지만 받아 JPEG로 변환하고 위치 정보를 제거합니다. 사진 열람에도 로그인이 필요합니다. 작성자는 글 수정 및 사진 교체·제거가 가능하고, 댓글 작성자는 자신의 댓글을 삭제할 수 있습니다.

## VS Code에서 시작하기 (Windows / macOS / Linux)

1. Node.js 22.12 이상(권장: 24 LTS), Python 3.12 이상, VS Code를 설치합니다. Windows에서는 Python 설치 시 PATH 추가를 선택합니다. 설치 후 VS Code를 다시 실행하세요.
2. ZIP 파일을 받았다면 먼저 압축을 풉니다. `package.json`이 있는 폴더를 VS Code의 **파일 → 폴더 열기**로 열거나 `our-gallery.code-workspace`를 엽니다. ZIP 내부에서 직접 실행하지 마세요.
3. **터미널 → 작업 실행 → Gallery: Install**을 한 번 실행합니다. 패키지 다운로드에는 인터넷이 필요합니다.
4. **실행 및 디버그**에서 **Gallery: Web + API (Chrome)** 또는 **(Edge)**를 선택하고 **F5**를 누릅니다. 웹/API 서버가 실행되고 설치된 해당 브라우저가 열립니다.
5. 가입하려면 서버가 생성한 `.local/invite-code` 파일을 VS Code에서 직접 열고, 그 코드를 회원가입 화면에 입력하세요. 본인 PC에서는 처음부터 새 계정을 만들면 됩니다.

브라우저 디버깅 없이 실행하려면 **터미널 → 작업 실행 → Gallery: Start**를 선택하고 브라우저에서 `http://localhost:5173`을 엽니다. Live Server 확장은 사용하지 않습니다. 이 프로젝트는 Vite와 Python 서버가 모두 필요합니다.

- **빌드:** Ctrl+Shift+B (macOS: Cmd+Shift+B) 또는 `Gallery: Build`
- **테스트:** `Gallery: Test`. Python 확장 설치 후 **Python: Select Interpreter**에서 Python 3.12+를 고르면 VS Code 테스트 탐색기도 사용할 수 있습니다.
- **API 디버깅:** 실행 중인 `Gallery: API` 작업을 먼저 종료하고 `Gallery: Debug Python API`를 실행합니다. Python 확장이 필요하며 `Gallery: Web` 작업은 별도로 실행합니다.
- **종료:** 디버그 중지는 브라우저 디버깅만 종료합니다. 서버는 **터미널 → 작업 종료**에서 `Gallery: API`와 `Gallery: Web`을 각각 종료하세요. 재실행 시 같은 포트의 서버를 중복으로 띄우지 마세요.
- **포트 충돌:** 5173/8000 포트를 사용하는 기존 서버를 종료합니다. Vite는 다른 포트로 자동 이동하지 않도록 설정했습니다.
- **Windows PowerShell에서 npm.ps1 실행 정책 오류:** `Terminal: Select Default Profile`에서 **Command Prompt**를 선택하고 새 터미널을 엽니다. 직접 명령을 입력할 때는 `npm.cmd`도 사용할 수 있습니다.

아래 개발 명령도 모든 운영체제에서 사용할 수 있습니다. Python 실행기는 Windows의 `py -3`/`python`, macOS·Linux의 `python3`/`python`을 확인하여 3.12 이상을 선택합니다.

## 개발 실행

Node.js 22.12+와 Python 3.12+가 필요합니다. 사진 처리를 위한 Pillow가 필요하며 `npm run setup`으로 가상환경에 설치합니다.

```sh
# package.json이 있는 폴더에서 실행
npm ci
npm run setup
npm run server
```

다른 터미널에서:

```sh
# package.json이 있는 폴더에서 실행
npm run dev
```

Vite는 5173 포트에서 동작하며 `/api`를 8000 포트 서버로 전달합니다. 서버 기본 바인딩은 `127.0.0.1`입니다.

최초 서버 시작 시 `.local/invite-code`에 무작위 초대 코드가 생성됩니다. 운영자가 로컬에서 이 파일을 확인하여 친구들에게 안전하게 전달하세요. 코드와 데이터베이스는 Git에서 제외됩니다. 코드가 자동으로 화면이나 로그에 노출되지는 않습니다. `GALLERY_INVITE_CODE` 환경변수로 코드를 지정할 수도 있습니다. 별도 이메일이나 외부 인증 서비스는 필요하지 않습니다.

## 검증

```sh
npm run setup
npm test
npm run build
```

API 통합 테스트는 임시 데이터베이스와 별도 포트를 사용합니다. 가입 제한, 비회원 접근 제한, 로그인/로그아웃, 익명 표시, 작성, 반응 변경/취소, 댓글, 삭제 권한, 교차 출처 요청 차단을 확인합니다.

## 빌드 실행 및 배포

```sh
npm run build
HOST=0.0.0.0 PORT=8000 npm start
```

Python 서버가 `dist`와 API를 동일 출처로 제공합니다. `/api/health` 응답이 `{"ok": true}`인지 확인하세요. 개발 서버를 인터넷에 그대로 공개하지 마세요. 이 Python 기본 HTTP 서버는 소규모 개발·검증용이며 공개 운영 시 TLS 역방향 프록시와 적절한 서비스 프로세스 구성을 준비해야 합니다.

실제 배포는 HTTPS 환경에서 `GALLERY_SECURE_COOKIE=1`을 지정하세요. `GALLERY_DATA_DIR`에 영구 볼륨 경로를 설정하고 SQLite 데이터를 백업하세요. 기본 저장소는 `.local/gallery.sqlite3`입니다. 비밀번호는 개별 salt를 사용한 scrypt 해시, 세션은 HttpOnly/SameSite 쿠키 및 서버의 해시 토큰으로 저장됩니다. 로그인이 반복 실패하면 IP당 15분 동안 최대 30회의 인증 요청을 허용합니다. 현재 실제 접속 IP 기준이므로 프록시 뒤에서는 사용자가 같은 한도를 공유할 수 있습니다.

익명은 다른 회원에게 표시하는 이름만 숨깁니다. 서버에는 작성 계정이 남습니다. 계정 복구, 관리자 화면, 사용자 차단/탈퇴, 댓글 수정, 푸시 알림은 후속 작업입니다. 게시글 목록은 최근 200개까지 불러옵니다.

## 앱으로 확장하기

React 웹과 JSON API가 분리되어 있어 먼저 웹을 완성한 뒤 Capacitor 등의 WebView 컨테이너로 확장할 수 있습니다. 이번 작업에는 네이티브 앱 패키징은 포함되지 않습니다. 앱 배포 시 HTTPS 서버 주소, 허용 출처, 쿠키/인증 전달 방식, iOS/Android 프로젝트와 실제 기기 검증을 추가해야 합니다. 현재 API는 동일 출처 웹 요청을 위한 설정입니다.


## 기존 로컬 프로젝트 업데이트 (Windows)

기존 서버 터미널 두 개에서 Ctrl+C를 눌러 종료한 뒤, `package.json`이 있는 폴더에서 다음을 실행하세요. Git으로 복제한 폴더여야 합니다. 소스 파일을 직접 수정했다면 먼저 변경 사항을 확인하여 보존하세요.

```powershell
git pull --ff-only origin main
npm.cmd ci
npm.cmd run setup
npm.cmd run server
```

새 터미널에서 `npm.cmd run dev`를 실행하세요. Node.js 경로 문제가 있으면 각 터미널에서 `$env:Path = "C:\Program Files\nodejs;" + $env:Path`를 먼저 실행하세요. 기존 `.local` 계정과 글은 그대로 유지되며 시작 시 사진 테이블만 추가됩니다. ZIP으로 받은 폴더에는 Git 이력이 없으므로 `git pull`을 실행할 수 없습니다. 새 버전을 별도 폴더에 복제하고, 모든 서버를 종료한 상태에서 기존 `.local` 폴더를 새 폴더로 복사한 뒤 실행하세요.

## Render에 배포하기

이 저장소의 `render.yaml`은 Docker 웹 서비스 1개와 1GB 영구 디스크를 선언합니다. **무료 구성이 아닙니다.** Render에서 표시하는 서비스·디스크 월 비용을 확인하고 진행하세요. 자동 확장은 사용하지 않으며 SQLite 파일을 여러 인스턴스가 공유하는 구조는 지원하지 않습니다.

1. https://dashboard.render.com 에서 GitHub 계정으로 가입/로그인합니다. 비밀번호나 결제 정보는 이 채팅에 보내지 마세요.
2. **New → Blueprint**를 선택하고 GitHub 저장소 `yc0416/-`를 연결합니다. 저장소가 보이지 않으면 Render GitHub 연동에서 해당 저장소 접근을 허용합니다.
3. 브랜치를 `main`으로 선택하고 Blueprint를 불러옵니다. `render.yaml`의 서비스와 영구 디스크를 확인합니다.
4. `GALLERY_INVITE_CODE`에 친구들에게만 전달할 충분히 긴 무작위 초대 코드를 Render 화면에서 직접 입력합니다. `GALLERY_SECURE_COOKIE=1`, `GALLERY_DATA_DIR=/data`는 설정에 포함됩니다. 원치 않는 유료 플랜이면 생성하지 마세요.
5. 비용과 설정을 확인한 뒤 배포합니다. Render가 제공하는 **HTTPS 주소**를 사용합니다. GitHub Pages는 Python API와 SQLite 서버를 실행하지 못하므로 사용할 수 없습니다.
6. 배포 주소의 `/api/health`가 `{"ok":true}`인지 확인한 뒤 회원가입 → 사진 글 작성 → 수정 → 댓글 삭제를 확인합니다. 로그인하지 않은 시크릿 창에서는 글과 사진을 읽을 수 없어야 합니다.
7. Render에서 서비스를 재시작한 뒤 로그인하여 글·사진이 유지되는지 확인합니다. 이 확인 전에는 영구 저장 검증이 완료된 것이 아닙니다.

배포는 본인 PC와 별도 데이터베이스로 시작합니다. 로컬 계정과 글이 자동으로 옮겨지지 않으므로 배포 사이트에서 새로 가입하세요. 기존 데이터 이전을 원하면 별도 백업·이전 절차가 필요합니다.

운영에서는 Gunicorn WSGI 서버가 빌드된 웹과 API를 함께 제공합니다. Docker 이미지는 앱 소스와 빌드 결과만 포함하며 로컬 데이터/초대 코드/가상환경은 포함하지 않습니다. 이 작업 환경에서는 공개 사이트 생성이나 Render 계정 연결이 이루어지지 않았습니다. 실제 공개 주소, Render의 TLS·디스크 연결 및 재시작 후 보존은 배포 후 검증해야 합니다. 백업은 SQLite의 온라인 backup API로 생성하고 별도 위치에 보관하세요. 실행 중인 DB 파일 하나만 복사하면 WAL의 최신 데이터가 누락될 수 있습니다.

사내 프록시 등 별도 인증기관이 필요한 빌드 환경에서는 Docker BuildKit의 `build_ca` secret에 신뢰하는 PEM CA 묶음을 전달할 수 있습니다. 전달하지 않으면 기본 시스템 인증서 검증을 사용합니다. TLS 검증을 끄지 마세요.
