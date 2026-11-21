# 매일 전자책 1권 — 제작·업로드 절차

매일 한 권씩 "AI·부업 실전 가이드" 시리즈를 만들어 그로블·크몽·래피드에 올리기 위한 작업 폴더입니다.
주제 순서는 `queue.json`에 있고, 날마다 `daily/<날짜>-<주제id>/` 폴더에 결과물이 쌓입니다.

## 하루 작업 순서 (예약 작업이 이 순서로 진행)

1. **주제 고르기**: `python -m app.daily_ebook --next` 가 돌려준 다음 주제를 쓴다.
2. **원고 쓰기**: 그 주제로 `daily/<YYYY-MM-DD>-<id>/spec.json` 을 쓴다 (형식은 아래).
   - 분량: 프롤로그 + 6~8장, 약 25~35쪽(장당 1,800~2,500자).
   - 말투: 정리된 실용 매뉴얼체 존댓말. 장마다 따라 하는 단계·예시 프롬프트·체크리스트를 넣는다.
   - 하지 말 것: 지어낸 수익 인증·후기·통계, 저자가 겪지 않은 경험담, 수익 보장 표현.
     도구 이름·가격·정책처럼 바뀌는 정보는 "작성일 기준"으로 적고 확인을 권한다.
3. **파일 만들기**: `python -m app.daily_ebook daily/<폴더>/spec.json`
   - PDF, 표지, 3D 목업, 썸네일(4:3·1:1), 상세 이미지, 그로블 값, 크몽·래피드 등록 문구, zip 이 만들어진다.
   - PDF 1~3쪽과 표지·썸네일을 이미지로 열어 글자 깨짐·넘침을 확인한다.
4. **그로블 초안 올리기** (판매 시작은 하지 않음)
   - `create_upload_url` 로 ebook.pdf(document), thumb_4x3.png(thumbnail)를 올린다.
     PUT 이 막히면 `request_file_upload` 링크를 만들어 판매자에게 보여 준다.
   - `groble.json` 값 + 받은 fileUrl(documentFileUrl, thumbnailUrl)로 `save_product_draft` 를 호출한다.
5. **기록·보관**: `python -m app.daily_ebook --done <id> <폴더> <그로블상품ID>` 후 커밋·푸시한다.
6. **판매자에게 보고**: 제목·가격·목차·표지와 그로블 미리보기 링크를 보여 주고
   "판매 시작"이라고 답하면 `start_product_sale` 을 호출한다. 승인 없이 판매를 시작하지 않는다.
   크몽·래피드는 폴더의 `kmong.md`, `latpeed.md`, 썸네일, PDF로 판매자가 직접 올린다 (공식 업로드 API 없음).

## spec.json 형식

```json
{
  "title": "AI로 블로그 글 1시간에 3개 쓰기",          // 30자 이하 (그로블 제한)
  "subtitle": "주제 선정부터 발행까지, 초보를 위한 실전 루틴",
  "target": "블로그 부업을 시작한 직장인·주부",
  "pain": "글 하나 쓰는 데 반나절이 걸려 블로그를 포기하게 된다",
  "keywords": ["블로그 부업", "AI 글쓰기", "챗GPT 블로그"],
  "category": "부업·N잡",
  "price": 10000,
  "pages": 30,
  "author": "",                       // 표지 저자명 (비우면 표시 안 함)
  "author_intro": "",                 // 저자 소개 (비우면 생략)
  "palette": "ocean",                 // midnight | sunrise | forest | paper | ocean
  "cover_style": "bold",              // bold | poster | minimal | classic
  "badge": "AI 부업 시리즈",          // 썸네일 왼쪽 위 배지 (선택)
  "prologue": "마크다운 본문",
  "chapters": [
    {"title": "장 제목", "claim": "이 장의 결론 한 문장", "points": ["소주제"], "body": "마크다운 본문"}
  ],
  "sales": {
    "headline": "판매 페이지 첫 문장",
    "subhead": "한 줄 설명",
    "pains": ["독자의 고민 4개"],
    "benefits": ["얻는 것 5개"],
    "for_whom": ["이런 분께 추천 4개"]
  }
}
```

## 플랫폼 메모

| 플랫폼 | 방법 | 비고 |
|---|---|---|
| 그로블 | 연결 도구로 초안 자동 저장 → 판매자 승인 후 판매 시작 | 수수료 5%(Pro 기본형). 리뷰·구매자 수 공개, 검색 노출: 예 |
| 크몽 | `kmong.md` 복사 + `thumb_4x3.png` + `ebook.pdf` 직접 등록 | 등록 후 크몽 검수를 거침 |
| 래피드(latpeed.com) | `latpeed.md` 복사 + 썸네일 + PDF 직접 등록, PDF 자동 판매 켜기 | |
