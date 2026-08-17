# 정보처리산업기사 CBT Lab

정보처리산업기사 필기 기출문제를 연도·회차·과목별로 풀 수 있는 정적 웹앱입니다.

## 프로젝트 구조

```text
.
├── index.html                  # Vercel 진입점
├── data/
│   └── question-bank.js        # 현재 앱에서 사용하는 문제은행
├── scripts/
│   └── build_question_bank.py  # PDF에서 문제은행을 다시 생성하는 로컬 스크립트
├── requirements.txt             # 문제은행 생성용 Python 패키지
├── package.json                # 로컬 실행 명령
├── vercel.json                 # 정적 배포 헤더 설정
└── .gitignore                  # 원본 PDF·임시 파일 제외
```

원본 PDF, ZIP, 추출 파일은 현재 프로젝트에서 제거했고 `.gitignore`로 재추가되지 않게 했습니다. 앱 실행에는 `data/question-bank.js`만 필요합니다. 문제은행을 다시 생성할 때만 원본 파일을 `tmp/`에 임시로 넣어 사용하세요.

## 로컬 실행

```bash
npm run dev
```

브라우저에서 <http://localhost:3000>을 엽니다.

## 문제은행 다시 생성

현재 원본 파일을 `tmp/past_exam_sources/`와 `tmp/past_exam_extracted_cp949/`에 둔 뒤 실행합니다.

```bash
python3 -m pip install -r requirements.txt
npm run question-bank:build
```

생성 결과는 `data/question-bank.js`에 저장됩니다.

## GitHub·Vercel 배포

1. 이 폴더를 GitHub 저장소에 push합니다.
2. Vercel에서 해당 저장소를 Import합니다.
3. Framework Preset은 `Other`, Build Command는 비워 두고 배포합니다.
4. Output Directory는 프로젝트 루트(`.`)로 둡니다.

이 프로젝트는 별도 서버나 데이터베이스가 없는 정적 사이트이므로 Vercel에서 바로 서비스할 수 있습니다. 공개 저장소에 문제 원문을 배포하기 전에는 원본 시험문제의 이용·배포 권한을 확인하세요.
