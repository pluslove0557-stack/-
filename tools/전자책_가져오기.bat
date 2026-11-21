@echo off
chcp 65001 > nul
set PYTHONUTF8=1
rem 이 파일은 저장소 폴더(코딩\-) 안의 tools 폴더에 있습니다.
rem 더블클릭하면 최신 전자책을 받아 코딩\전자책\날짜_제목 폴더로 정리합니다.
cd /d "%~dp0.."
git pull --quiet
where py > nul 2>&1 && (py -3 app\daily_ebook.py --export "..\전자책") || (python app\daily_ebook.py --export "..\전자책")
echo.
echo 완료: %~dp0..\..\전자책 폴더를 확인하세요.
pause
