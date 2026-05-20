@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   Reverie Studio - 설치 도우미 v1.0
echo   AI 유튜브 라디오드라마 자동 제작 시스템
echo ============================================================
echo.

:: 관리자 권한 확인
net session >nul 2>&1
if errorlevel 1 (
    echo [경고] 관리자 권한으로 실행하는 것을 권장합니다.
    echo       그래도 계속하려면 아무 키나 누르세요.
    pause >nul
)

:: 시스템 요구사항 안내
echo [1단계] 시스템 요구사항 확인
echo ────────────────────────────────────────────────────────────
echo   OS      : Windows 11 (필수)
echo   GPU     : NVIDIA RTX 4060Ti 8GB 이상
echo   RAM     : 16GB 이상 권장
echo   저장공간 : 30GB 이상 여유 공간
echo   인터넷  : Gemini API 사용 시 필요
echo ────────────────────────────────────────────────────────────
echo.

:: Python 확인
echo [2단계] Python 환경 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo   [오류] Python이 설치되지 않았습니다.
    echo   https://www.python.org/downloads/ 에서 Python 3.11 설치 후 재실행하세요.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   [OK] Python %PYVER% 감지됨
echo.

:: pip 패키지 설치
echo [3단계] Python 패키지 설치 (requirements.txt)
echo   약 2-5분 소요됩니다...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo   [경고] 일부 패키지 설치 실패. 수동으로 확인이 필요할 수 있습니다.
) else (
    echo   [OK] 패키지 설치 완료
)
echo.

:: Node.js 확인 (Remotion 영상 렌더링용)
echo [4단계] Node.js 확인 (영상 렌더링용)
node --version >nul 2>&1
if errorlevel 1 (
    echo   [경고] Node.js가 없습니다. 영상 렌더링이 작동하지 않습니다.
    echo   https://nodejs.org 에서 Node.js 20 LTS 설치를 권장합니다.
) else (
    for /f %%v in ('node --version 2^>^&1') do set NODEVER=%%v
    echo   [OK] Node.js %NODEVER% 감지됨

    :: Remotion 패키지 설치
    if exist "remotion-poc\package.json" (
        echo   Remotion 패키지 설치 중...
        cd remotion-poc && npm install --legacy-peer-deps -q && cd ..
        echo   [OK] Remotion 패키지 설치 완료
    )
)
echo.

:: FFmpeg 확인
echo [5단계] FFmpeg 확인
set FFMPEG_FOUND=0
if exist "C:\ffmpeg8\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe" (
    echo   [OK] FFmpeg 8.0.1 발견: C:\ffmpeg8\...
    set FFMPEG_PATH=C:\ffmpeg8\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe
    set FFMPEG_FOUND=1
)
if exist "C:\ffmpeg\bin\ffmpeg.exe" (
    echo   [OK] FFmpeg 발견: C:\ffmpeg\bin\ffmpeg.exe
    set FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
    set FFMPEG_FOUND=1
)
if !FFMPEG_FOUND!==0 (
    echo   [경고] FFmpeg를 찾을 수 없습니다.
    echo   https://www.gyan.dev/ffmpeg/builds/ 에서 full_build 버전 다운로드 후
    echo   C:\ffmpeg\bin\ 에 압축 해제하세요.
)
echo.

:: .env 파일 설정
echo [6단계] 환경 설정 파일 (.env) 구성
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo   [OK] .env.example → .env 복사 완료
        echo   ────────────────────────────────────────────────────────
        echo   [필수 설정] .env 파일을 메모장으로 열어 아래 항목을 입력하세요:
        echo.
        echo     GEMINI_API_KEY=여기에_Gemini_API_키_입력
        echo     (발급: https://aistudio.google.com/apikey)
        echo.
        echo     REVERIE_PACK_PASSWORD=관리자가_전달한_팩_암호
        echo     REVERIE_PACK_SALT=관리자가_전달한_솔트값
        echo   ────────────────────────────────────────────────────────
        echo.
        set /p OPEN_ENV="지금 .env 파일을 메모장으로 여시겠습니까? (y/n): "
        if /i "!OPEN_ENV!"=="y" (
            notepad .env
        )
    ) else (
        echo   [경고] .env.example 파일이 없습니다.
    )
) else (
    echo   [OK] .env 파일 이미 존재합니다.
)
echo.

:: data 폴더 생성
echo [7단계] 필수 폴더 생성
if not exist "data" mkdir data
if not exist "data\channels" mkdir data\channels
if not exist "data\queue" mkdir data\queue
if not exist "release" mkdir release
echo   [OK] 폴더 구조 생성 완료
echo.

:: Docker 확인 (선택사항)
echo [8단계] Docker 확인 (선택사항 - SD WebUI + TTS 자동화용)
docker --version >nul 2>&1
if errorlevel 1 (
    echo   [정보] Docker가 없습니다. 수동으로 SD WebUI와 GPT-SoVITS를 설치하세요.
    echo          또는 Docker Desktop 설치 후 docker-compose up -d 실행
) else (
    for /f "tokens=3" %%v in ('docker --version 2^>^&1') do set DOCKERVER=%%v
    echo   [OK] Docker 감지됨
    set /p USE_DOCKER="Docker로 SD WebUI + GPT-SoVITS를 시작하시겠습니까? (y/n): "
    if /i "!USE_DOCKER!"=="y" (
        echo   Docker 컨테이너 시작 중... (처음 실행 시 이미지 다운로드로 30분+ 소요)
        docker-compose up -d
        if errorlevel 1 (
            echo   [경고] Docker 시작 실패. docker\README_DOCKER.md를 확인하세요.
        ) else (
            echo   [OK] Docker 컨테이너 시작됨
            echo        SD WebUI: http://localhost:7860
            echo        GPT-SoVITS: http://localhost:9880
        )
    )
)
echo.

:: 설치 완료
echo ============================================================
echo   설치 완료!
echo ============================================================
echo.
echo 다음 단계:
echo   1. .env 파일에 Gemini API 키 입력 (필수)
echo   2. SD WebUI + GPT-SoVITS 서버 시작
echo   3. ReverieStudio.exe 실행
echo.
echo 문의 / 구매: 크몽에서 'Reverie Studio' 검색
echo.
pause
