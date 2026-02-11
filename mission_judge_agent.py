# 설치: pip install -U streamlit langchain langchain-google-genai google-generativeai python-dotenv
# 실행: python mission_judge_agent_gemini.py

import os
import json
import base64
from typing import List, Dict, Any

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

# =========================================================
# (1) ENV 로드 + Gemini LLM (단일 모델 고정)
# =========================================================
load_dotenv("gemini_api.env")

# Gemini SDK는 GOOGLE_API_KEY만 인식
if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")

if not os.getenv("GOOGLE_API_KEY"):
    raise RuntimeError("GOOGLE_API_KEY가 필요합니다. gemini_api.env를 확인하세요.")

# ✅ 단일 모델 고정
MODEL_NAME = "gemini-2.5-flash"

llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0
)

print(f"[INFO] Gemini model in use: {MODEL_NAME}")

# =========================================================
# 유틸
# =========================================================
def safe_json_load(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {"_raw": s}

def image_to_data_url(path: str) -> str:
    """로컬 이미지 파일 → data URL(base64)"""
    ext = os.path.splitext(path)[1].lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime};base64,{b64}"

# =========================================================
# (2) Tools 정의
# =========================================================
@tool
def missionGet(category: str, details: str, policy: str) -> str:
    """
    미션 요약 + 체크리스트 + 업로드 지침 생성
    """
    prompt = f"""
너는 '미션 인증용 체크리스트/지침 생성기'다.

[카테고리]
{category}

[부모 세부사항]
{details}

[정책]
{policy}

조건:
- 사진으로 확인 가능한 기준만 작성
- checklist 3~10개
- evidence_hint 필수
- 출력은 JSON만

스키마:
{{
  "category": "...",
  "mission_summary": "...",
  "keywords": ["..."],
  "checklist": [
    {{"item": "...", "evidence_hint": "..."}}
  ],
  "upload_guidelines": {{
    "recommended_photos": number,
    "instructions": ["..."]
  }},
  "success_criteria": "..."
}}
""".strip()

    out = llm.invoke(prompt).content.strip()
    return json.dumps(safe_json_load(out), ensure_ascii=False)

@tool
def photoGet(category: str, mission_summary_json: str, photo_paths: List[str]) -> str:
    """
    증거 사진 분석 (관찰 기반)
    """
    if not photo_paths:
        return json.dumps({"error": "photo_paths is empty"}, ensure_ascii=False)

    photo_paths = photo_paths[:10]
    mission_obj = safe_json_load(mission_summary_json)

    mode = "before_after" if (category == "청소" and len(photo_paths) == 2) else "evidence_only"

    content = [{
        "type": "text",
        "text": f"""
너는 '미션 증거 사진 분석기'다.
추측 금지, 관찰 가능한 사실만 기술.

[모드] {mode}

[미션 요약(JSON)]
{json.dumps(mission_obj, ensure_ascii=False)}

출력(JSON):
{{
  "mode": "{mode}",
  "observations": ["..."],
  "per_photo_notes": [
    {{"photo_index": 1, "note": "..."}}
  ],
  "notable_changes": ["..."],
  "caveats": ["..."]
}}
""".strip()
    }]

    for i, path in enumerate(photo_paths, start=1):
        if not os.path.exists(path):
            return json.dumps({"error": f"file not found: {path}"}, ensure_ascii=False)

        content.append({"type": "text", "text": f"사진 {i}:"})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_url(path)}
        })

    msg = HumanMessage(content=content)
    out = llm.invoke([msg]).content.strip()
    return json.dumps(safe_json_load(out), ensure_ascii=False)

@tool
def missionComplete(mission_summary_json: str, photo_analysis_json: str) -> str:
    """
    완수율 계산 + pass/fail 판단
    """
    prompt = f"""
너는 '미션 채점관'이다.

[미션 요약]
{mission_summary_json}

[사진 분석]
{photo_analysis_json}

규칙:
- checklist 항목별 점수: 달성=1 / 부분=0.5 / 미달=0
- 완수율 = 평균 * 100
- 60% 이상이면 pass=true
- 출력은 JSON만

스키마:
{{
  "completion_percent": number,
  "pass": boolean,
  "reason_summary": ["..."],
  "item_grades": [
    {{"item": "...", "status": "...", "evidence": "..."}}
  ],
  "missing_or_unclear": ["..."],
  "next_request_to_child": ["..."]
}}
""".strip()

    out = llm.invoke(prompt).content.strip()
    obj = safe_json_load(out)

    cp = float(obj.get("completion_percent", 0))
    cp = max(0, min(100, cp))
    obj["completion_percent"] = cp
    obj["pass"] = cp >= 60

    return json.dumps(obj, ensure_ascii=False)

# =========================================================
# CLI 실행
# =========================================================
def main():
    category = input("미션 카테고리(청소/숙제/심부름/습관): ").strip()
    details = input("미션 세부사항: ").strip()

    policy = """
- 청소: before/after 2장 권장
- 숙제: 결과 사진만으로 평가 가능
- 습관: 증거 약하면 보수적 평가
- 통과 기준: 60%
""".strip()

    print("\n사진 경로 입력 (여러 장이면 줄바꿈, 종료는 빈 줄)")
    photo_paths = []
    while True:
        p = input("photo path> ").strip()
        if not p:
            break
        photo_paths.append(p)

    print("\n[1] 미션 요약 생성")
    mission_summary = missionGet.invoke({
        "category": category,
        "details": details,
        "policy": policy
    })
    print(mission_summary)

    print("\n[2] 사진 분석")
    photo_analysis = photoGet.invoke({
        "category": category,
        "mission_summary_json": mission_summary,
        "photo_paths": photo_paths
    })
    print(photo_analysis)

    print("\n[3] 최종 판정")
    result = missionComplete.invoke({
        "mission_summary_json": mission_summary,
        "photo_analysis_json": photo_analysis
    })
    print(result)

if __name__ == "__main__":
    main()
