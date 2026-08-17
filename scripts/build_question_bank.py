from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
EXTRACTED_ROOT = ROOT / "tmp" / "past_exam_extracted_cp949"
SOURCE_ROOT = ROOT / "tmp" / "past_exam_sources"
OUTPUT = ROOT / "data" / "question-bank.js"

SUBJECTS = {
    1: "정보시스템 기반 기술",
    2: "프로그래밍언어 활용",
    3: "데이터베이스 활용",
}
LETTERS = ["①", "②", "③", "④"]
ANSWER_INDEX = {letter: index for index, letter in enumerate(LETTERS)}


def discover_sources() -> list[tuple[int, int, Path]]:
    found: list[tuple[int, int, Path]] = []
    for year_dir in sorted(EXTRACTED_ROOT.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = int(year_dir.name)
        for path in sorted(year_dir.glob("*.pdf")):
            match = re.search(r"(?:^|[^0-9])([123])회", path.stem)
            if match:
                found.append((year, int(match.group(1)), path))

    found.append((2026, 1, SOURCE_ROOT / "2026_source.pdf"))
    return sorted(found)


def extract_pages(path: Path) -> list[str]:
    # The source PDFs use two columns. pdfplumber lets us read the left column
    # completely before the right column, which avoids the text-layer order
    # problems seen with a plain pypdf extraction.
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            midpoint = page.width / 2
            left = page.crop((0, 55, midpoint, page.height - 35)).extract_text(
                x_tolerance=1, y_tolerance=3
            ) or ""
            right = page.crop((midpoint, 55, page.width, page.height - 35)).extract_text(
                x_tolerance=1, y_tolerance=3
            ) or ""
            pages.append(f"{left}\n{right}")
    return pages


def extract_answer_pages(path: Path) -> list[str]:
    return [(page.extract_text() or "") for page in PdfReader(str(path)).pages]


def find_marker(text: str, number: int, year: int, start: int) -> re.Match[str] | None:
    # Some source PDFs place the next question number immediately after a
    # numeric option (for example, "7.25 11."). Do not require whitespace or
    # a non-digit before the marker; the expected question sequence disambiguates
    # it while walking forward through the document.
    scoped = text[start:]
    dotted = re.search(rf"(?<!\d){number}[.]\s*", scoped)
    # A small number of source pages omit the dot after the question number
    # (for example, "48 다음 ..."). Only accept that form at the beginning of
    # a line, so decimal values such as "7.25" are not mistaken for question 5.
    undotted = re.search(
        rf"(?m)^\s*{number}(?!\s*저작권)(?=\s+[^\d])\s*", scoped
    )
    if dotted and undotted:
        return dotted if dotted.start() <= undotted.start() else undotted
    if dotted:
        return dotted
    if undotted:
        return undotted
    # Last-resort handling for a marker emitted directly after a numeric value,
    # such as "7.25 11." in a few older text layers.
    return re.search(rf"{number}[.]\s*", scoped)


def find_markers(text: str, year: int) -> list[tuple[int, int, int]]:
    markers: list[tuple[int, int, int]] = []
    cursor = 0
    for number in range(1, 61):
        match = find_marker(text, number, year, cursor)
        if not match:
            raise ValueError(f"{year}: question marker {number} not found")
        start = cursor + match.start()
        end = cursor + match.end()
        markers.append((number, start, end))
        cursor = end
    return markers


def clean_block(block: str) -> str:
    block = re.sub(r"회\s*\d+\s*-\s*\d+\s*-", " ", block)
    block = re.sub(r"저작권 안내.*", " ", block, flags=re.S)
    block = re.sub(r"기출문제\s*(?:정답\s*및\s*해설)?", " ", block)
    block = re.sub(r"\d{4}년\s*\d*회?\s*정보처리산업기사\s*필기", " ", block)
    block = re.sub(r"\d+\s+\d+회\s+정보처리산업기사.*$", " ", block, flags=re.S)
    block = re.sub(r"\d+회\s+정보처리산업기사.*$", " ", block, flags=re.S)
    block = re.sub(r"제\s*[123]과목[^0-9]*$", " ", block)
    block = re.sub(r"\s*-\s*\d+(?:\s+\d+)?\s*-?\s*$", " ", block)
    block = re.sub(r"[ \t\f\r]+", " ", block)
    return block.strip()


def normalize(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" -")


def recover_first_question_prefix(text: str, marker_start: int, year: int) -> str:
    if year not in (2024, 2026):
        return ""
    before = text[max(0, marker_start - 120) : marker_start]
    match = re.search(r"기술\s*1(.*)$", before)
    if not match:
        return ""
    candidate = normalize(match.group(1))
    if len(candidate) >= 5 and "저작권" not in candidate:
        return candidate
    return ""


def split_choices(block: str, year: int) -> tuple[str, list[str]]:
    labels = list(re.finditer(r"[①②③④]", block))
    if not labels:
        return normalize(block), ["보기 이미지 참조"] * 4

    # With column-aware extraction, the source order is question -> ① text ->
    # ② text -> ③ text -> ④ text. A few image-only choices are intentionally
    # kept empty and replaced by a visible placeholder later.
    prompt = block[: labels[0].start()]
    choices = []
    for index, label in enumerate(labels[:4]):
        end = labels[index + 1].start() if index + 1 < len(labels) else len(block)
        choices.append(normalize(block[label.end() : end]))
    return normalize(prompt), (choices + [""] * 4)[:4]


def parse_answers(pages: list[str], year: int) -> dict[int, int]:
    # Answer keys are the page containing at least 50 numbered circled answers.
    for page in reversed(pages):
        pairs = re.findall(r"(?<!\d)(\d{1,2})\s*[.]\s*([①②③④])", page)
        if len(pairs) < 50:
            continue
        answers: dict[int, int] = {}
        for number, letter in pairs:
            number_int = int(number)
            if 1 <= number_int <= 60:
                answers[number_int] = ANSWER_INDEX[letter]
        if len(answers) == 60:
            return answers
    raise ValueError(f"{year}: answer key not found")


def generic_explanation(subject: str, choices: list[str], answer: int) -> dict[str, object]:
    answer_text = choices[answer]
    return {
        "kind": "basic",
        "summary": (
            f"이 문제는 {subject}의 핵심 개념을 확인하는 문제입니다. "
            "지문에서 요구하는 조건을 먼저 찾고 각 선택지의 정의와 대조하면 됩니다."
        ),
        "steps": [
            "문제에서 묻는 대상과 핵심 조건을 먼저 표시합니다.",
            f"정답 키에 해당하는 선택지는 {LETTERS[answer]} {answer_text}입니다.",
            "다른 선택지는 지문이 요구한 조건이나 용어의 정의와 일치하지 않으므로 제외합니다.",
        ],
        "choiceNotes": [
            "지문의 조건과 일치하지 않는 선택지입니다." if index != answer else "지문의 조건과 일치하는 정답 선택지입니다."
            for index in range(4)
        ],
        "memory": f"{subject} · 정답 키워드: {answer_text}",
    }


CURATED = {
    (2026, 1, 1): {
        "kind": "detailed",
        "summary": "프로토콜의 역할을 먼저 분류하면, 경로를 계산하는 프로토콜과 메시지를 전달하는 프로토콜을 구분할 수 있습니다.",
        "steps": [
            "BGP는 서로 다른 자율 시스템(AS) 사이에서 경로 정보를 교환합니다.",
            "OSPF는 하나의 자율 시스템 내부에서 링크 상태 정보를 이용해 최적 경로를 계산하고, RIP는 홉 수를 기준으로 경로를 선택합니다.",
            "SMTP는 네트워크 경로를 계산하지 않고 메일 서버 사이에서 전자우편을 전송합니다. 따라서 정답은 ③ SMTP입니다.",
        ],
        "choiceNotes": [
            "AS 간 라우팅에 사용하는 경로 벡터 계열 프로토콜입니다.",
            "내부 게이트웨이 프로토콜이며 링크 상태 방식으로 동작합니다.",
            "전자우편 전송 프로토콜입니다. 라우팅 프로토콜이 아닙니다.",
            "거리 벡터 방식이며 홉 수가 작은 경로를 우선합니다.",
        ],
        "memory": "라우팅 = BGP · OSPF · RIP / 메일 전송 = SMTP",
    },
    (2026, 1, 2): {
        "kind": "detailed",
        "summary": "FCFS는 대기 큐의 순서를 바꾸지 않습니다. 현재 헤드 위치에서 첫 요청으로 이동한 뒤, 큐에 적힌 순서대로 다음 요청까지의 절댓값을 더합니다.",
        "steps": [
            "첫 이동: |50 - 10| = 40",
            "두 번째 이동: |10 - 40| = 30, 세 번째 이동: |40 - 55| = 15",
            "마지막 이동: |55 - 35| = 20",
            "전체 헤드 이동: 40 + 30 + 15 + 20 = 105이므로 정답은 ③입니다.",
        ],
        "choiceNotes": [
            "요청 간 차이를 모두 더하지 않은 값입니다.",
            "일부 이동 구간만 반영한 값입니다.",
            "FCFS 순서의 모든 이동을 더한 정확한 값입니다.",
            "이동 거리를 반올림하거나 중복 계산한 값입니다.",
        ],
        "memory": "FCFS 디스크 스케줄링 = 큐 순서 고정 + 구간별 절댓값 합",
    },
    (2026, 1, 3): {
        "kind": "detailed",
        "summary": "통합 테스트는 모듈을 합친 뒤 연결부에서 문제가 생기는지 확인하는 단계입니다. 테스트 대상의 범위를 단위 테스트와 혼동하지 않는 것이 핵심입니다.",
        "steps": [
            "상향식 통합은 하위 모듈부터 결합하므로, 상위 모듈 역할을 대신하는 드라이버가 필요합니다.",
            "하향식 통합은 상위 모듈부터 결합하므로, 아직 구현되지 않은 하위 모듈을 대신하는 스텁을 사용합니다.",
            "통합 테스트는 모듈 간 인터페이스와 상호 작용 오류를 찾습니다. 개별 모듈의 기능성 검증을 최우선으로 한다는 ④는 단위 테스트에 가까운 설명이므로 틀렸습니다.",
        ],
        "choiceNotes": [
            "상향식 테스트에서 상위 모듈을 대신하는 드라이버를 사용합니다.",
            "하향식 테스트에서 하위 모듈을 대신하는 스텁을 사용합니다.",
            "통합 테스트가 확인하는 대표적인 대상입니다.",
            "개별 모듈의 기능성 중심 검증은 단위 테스트의 역할입니다.",
        ],
        "memory": "드라이버 = 상향식 / 스텁 = 하향식 / 통합 = 연결부 검증",
    },
    (2026, 1, 4): {
        "kind": "detailed",
        "summary": "문제의 핵심 표현은 ‘오류를 검색하고 정정’입니다. 단순히 오류를 발견하는 코드가 아니라, 오류가 난 위치까지 알아내 수정할 수 있는 코드를 골라야 합니다.",
        "steps": [
            "해밍 코드는 데이터 비트 사이에 패리티 비트를 추가합니다.",
            "수신 측은 패리티 검사 결과를 조합해 오류 위치를 나타내는 신드롬을 계산합니다.",
            "일반적인 해밍 코드는 단일 비트 오류를 검출하고 정정할 수 있으므로 정답은 ② Hamming code입니다.",
        ],
        "choiceNotes": [
            "10진수 표현을 위한 코드로, 오류 정정 코드가 아닙니다.",
            "패리티 비트로 오류 위치를 찾아 단일 비트 오류를 정정합니다.",
            "인접한 값의 비트 변화가 한 비트가 되도록 만든 코드입니다.",
            "십진 숫자를 표현하는 코드이며 해밍 코드처럼 오류 정정을 수행하지 않습니다.",
        ],
        "memory": "Hamming = 패리티 비트 + 신드롬 + 단일 비트 오류 정정",
    },
    (2026, 1, 5): {
        "kind": "detailed",
        "summary": "인간공학적 UI 원리는 사용자의 기억 부담과 실수를 줄이고, 숙련도와 관계없이 작업을 완수할 수 있도록 돕는 데 초점을 둡니다.",
        "steps": [
            "반복 작업을 줄이는 지름길은 숙련 사용자의 효율을 높입니다.",
            "작업 진행 상황을 알려주면 사용자는 시스템이 멈췄는지, 얼마나 남았는지 판단할 수 있습니다.",
            "화면과 조작의 일관성은 학습 비용을 낮춥니다. 반대로 비전문 사용자를 고려하지 않는 것은 사용자 중심 설계에 어긋나므로 정답은 ④입니다.",
        ],
        "choiceNotes": [
            "효율성을 높이는 대표적인 사용자 인터페이스 원리입니다.",
            "시스템 상태를 가시적으로 알려주는 원리입니다.",
            "사용자의 예측 가능성과 학습성을 높입니다.",
            "비전문 사용자도 사용할 수 있게 해야 하므로 인간공학 원리에 포함되지 않습니다.",
        ],
        "memory": "좋은 UI = 효율성 + 상태 가시성 + 일관성 + 사용자 수준 고려",
    },
}


def build() -> list[dict[str, object]]:
    questions: list[dict[str, object]] = []
    for year, session, path in discover_sources():
        pages = extract_pages(path)
        answer_pages = extract_answer_pages(path)
        text = "\n".join(pages)
        markers = find_markers(text, year)
        answers = parse_answers(answer_pages, year)
        for index, (number, start, end) in enumerate(markers):
            stop = markers[index + 1][1] if index + 1 < len(markers) else len(text)
            block = text[end:stop]
            if index == 0:
                recovered = recover_first_question_prefix(text, start, year)
                if recovered:
                    block = recovered + " " + block
            # The 2024/2026 explanation pages start after question 60. Keep
            # the actual options and exclude those later pages from the block.
            if index == 59:
                page_break = re.search(r"회\s*\d+\s*-\s*\d+\s*-", block)
                if page_break:
                    block = block[: page_break.start()]
                answer_heading = re.search(r"(?:정답\s*(?:및\s*해설)?|정답)\b", block)
                if answer_heading:
                    block = block[: answer_heading.start()]
            prompt, choices = split_choices(clean_block(block), year)
            choices = [choice or "보기 이미지 참조" for choice in choices]
            answer = answers[number]
            explanation = CURATED.get((year, session, number)) or generic_explanation(
                SUBJECTS[(number - 1) // 20 + 1], choices, answer
            )
            questions.append(
                {
                    "id": f"{year}-{session}-{number}",
                    "year": year,
                    "session": session,
                    "number": number,
                    "subject": SUBJECTS[(number - 1) // 20 + 1],
                    "prompt": prompt,
                    "choices": choices,
                    "answer": answer,
                    "explanation": explanation,
                }
            )
    return questions


if __name__ == "__main__":
    data = build()
    if len(data) != 780:
        raise SystemExit(f"Expected 780 questions, got {len(data)}")
    payload = "window.QUESTION_BANK = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    empty_prompts = sum(not item["prompt"] for item in data)
    placeholder_choices = sum(
        choice == "보기 이미지 참조" for item in data for choice in item["choices"]
    )
    print(f"wrote {OUTPUT} ({len(data)} questions)")
    print(f"empty prompts: {empty_prompts}; image/placeholders: {placeholder_choices}")
