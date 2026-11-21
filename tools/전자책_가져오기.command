#!/bin/bash
# 맥: 더블클릭하면 최신 전자책을 받아 코딩/전자책/날짜_제목 폴더로 정리합니다.
cd "$(dirname "$0")/.." || exit 1
git pull --quiet
python3 app/daily_ebook.py --export "../전자책"
echo
echo "완료: $(cd .. && pwd)/전자책 폴더를 확인하세요."
read -n 1 -s -r -p "아무 키나 누르면 닫힙니다."
