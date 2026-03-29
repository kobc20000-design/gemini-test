@echo off
chcp 65001 > nul
setlocal
echo ======================================================
echo   Raton AI 블로그 작가 자동 설치 및 실행기
echo ======================================================
echo.

:: 1. 파이썬 명령어 확인 (python 또는 py)
set PY_CMD=
where python >nul 2>nul
if %errorlevel% equ 0 (
    set PY_CMD=python
) else (
    where py >nul 2>nul
    if %errorlevel% equ 0 (
        set PY_CMD=py
    )
)

if "%PY_CMD%"=="" (
    echo [오류] 파이썬(Python)이 설치되어 있지 않거나 경로 설정이 되어 있지 않습니다.
    echo.
    echo ------------------------------------------------------
    echo 해결 방법:
    echo 1. https://www.python.org/ 에서 파이썬을 다운로드하여 설치하세요.
    echo 2. 설치 과정에서 [Add Python to PATH] 체크박스를 반드시 선택하세요!
    echo 3. 이미 설치했다면, 컴퓨터를 다시 시작한 후 이 파일을 실행해 보세요.
    echo ------------------------------------------------------
    pause
    exit /b
)

echo [확인] 파이썬 명령어를 찾았습니다: %PY_CMD%
echo.

echo 1. 필수 라이브러리 설치 확인 중 (시간이 조금 걸릴 수 있습니다)...
%PY_CMD% -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [오류] 라이브러리 설치 중 에러가 발생했습니다. 인터넷 연결을 확인해 주세요.
    pause
    exit /b
)

echo.
echo 2. 프로그램을 실행합니다...
echo 브라우저 창이 자동으로 열리면 사용해 주세요.
echo (만약 열리지 않으면 http://localhost:8501 주소를 브라우저에 입력하세요.)
echo.
%PY_CMD% -m streamlit run app.py

if %errorlevel% neq 0 (
    echo.
    echo [오류] 프로그램 실행 중 문제가 발생했습니다.
    pause
)
endlocal
