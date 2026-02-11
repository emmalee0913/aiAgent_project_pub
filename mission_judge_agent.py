# 설치: pip install -U streamlit langchain langchain-google-genai google-generativeai python-dotenv
# 실행: streamlit run mission_judge_agent.py

import os
import json
import base64
from typing import List, Dict, Any

import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage


# =========================================================
# 유틸
# =========================================================
def safe_json_load(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s)
    except Exception:
        return {"_raw": s}


def image_to_data_url(path: str) -> str:
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


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_json(path: str, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# =========================================================
# LLM 생성
# =========================================================
def build_llm(api_key: str):
    os.environ["GOOGLE_API_KEY"] = api_key
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0
    )


# =========================================================
# Gemini Logic
# =========================================================
def mission_get(llm, category: str, details: str, policy: str) -> Dict[str, Any]:
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
- evidence_hint 포함
- JSON만 출력

스키마:
{{
  "category": "...",
  "mission_summary": "...",
  "checklist": [
    {{"item": "...", "evidence_hint": "..."}}
  ],
  "success_criteria": "..."
}}
"""
    out = llm.invoke(prompt).content.strip()
    return safe_json_load(out)


def photo_get(llm, category: str, mission_obj: Dict[str, Any], photo_paths: List[str]) -> Dict[str, Any]:
    mode = "before_after" if (category == "청소" and len(photo_paths) == 2) else "evidence_only"

    content = [{
        "type": "text",
        "text": f"""
너는 '미션 증거 사진 분석기'다.
추측하지 말고 관찰 가능한 사실만 작성해라.

[모드] {mode}
[미션 요약]
{json.dumps(mission_obj, ensure_ascii=False)}

출력(JSON):
{{
  "observations": ["..."],
  "notable_changes": ["..."],
  "caveats": ["..."]
}}
"""
    }]

    for i, p in enumerate(photo_paths, start=1):
        content.append({"type": "text", "text": f"사진 {i}"})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_url(p)}
        })

    msg = HumanMessage(content=content)
    out = llm.invoke([msg]).content.strip()
    return safe_json_load(out)


def mission_complete(llm, mission_obj: Dict[str, Any], photo_obj: Dict[str, Any]) -> Dict[str, Any]:
    prompt = f"""
너는 '미션 채점관'이다.

[체크리스트]
{json.dumps(mission_obj.get("checklist", []), ensure_ascii=False)}

[사진 분석]
{json.dumps(photo_obj, ensure_ascii=False)}

규칙:
- 달성=1 / 부분=0.5 / 미달=0
- 완수율 = 평균 * 100
- 60% 이상 통과
- JSON만 출력

스키마:
{{
  "completion_percent": number,
  "pass": boolean,
  "reason_summary": ["..."],
  "missing_or_unclear": ["..."],
  "next_request_to_child": ["..."]
}}
"""
    out = llm.invoke(prompt).content.strip()
    obj = safe_json_load(out)

    cp = float(obj.get("completion_percent", 0))
    cp = max(0, min(100, cp))
    obj["completion_percent"] = cp
    obj["pass"] = cp >= 60

    return obj


# =========================================================
# Streamlit UI (단계형 UX 반영 버전)
# 요구사항 반영:
# 1) API 키 검증 통과해야 다음 화면
# 2) 미션 입력 후 바로 요약 제공 + 확인 버튼
# 3) 사진은 경로 1개씩 추가 + 확인 버튼 + 다른 구역에서 목록 확인
# 4) 사진 요약은 작은 글씨
# 5) 최종 판정은 한 섹션, 통과=초록 아이콘 / 반려=빨강 아이콘
# =========================================================

import streamlit as st

st.set_page_config(page_title="미션 인증 판정기", layout="centered")
st.title("📸 미션 인증 확인")

# ---------- session_state 초기화 ----------
if "step" not in st.session_state:
    st.session_state.step = 0  # 0=API, 1=미션입력, 2=미션확인, 3=사진추가, 4=사진요약, 5=최종판정

if "api_key" not in st.session_state:
    st.session_state.api_key = ""

if "llm" not in st.session_state:
    st.session_state.llm = None

if "category" not in st.session_state:
    st.session_state.category = "청소"

if "details" not in st.session_state:
    st.session_state.details = ""

if "mission_obj" not in st.session_state:
    st.session_state.mission_obj = None

if "photo_paths" not in st.session_state:
    st.session_state.photo_paths = []

if "photo_obj" not in st.session_state:
    st.session_state.photo_obj = None

if "result_obj" not in st.session_state:
    st.session_state.result_obj = None


# ---------- 공통: 정책 ----------
policy = """
- 청소: before/after 2장 권장 (정확히 2장이면 비교모드)
- 숙제: 결과 사진만으로 평가
- 습관: 증거가 약하면 보수적 판정 + 부모 확인 권장
- 통과 기준: 60%
""".strip()


# ---------- 공통: 사이드바(현재 입력 확인) ----------
with st.sidebar:
    st.subheader("현재 입력 상태")
    st.write("STEP:", st.session_state.step)
    st.write("카테고리:", st.session_state.category)
    st.write("사진 수:", len(st.session_state.photo_paths))
    if st.session_state.photo_paths:
        st.caption("사진 목록")
        for i, p in enumerate(st.session_state.photo_paths[:10], start=1):
            st.caption(f"{i}. {p}")


# =========================================================
# STEP 0) API 키 입력 + 검증
# =========================================================
if st.session_state.step == 0:
    st.subheader("1) Gemini API Key 입력")

    api_key = st.text_input("Gemini API Key", type="password", placeholder="AIzaSy...")
    colA, colB = st.columns([1, 1])

    with colA:
        if st.button("API 키 확인", type="primary"):
            if not api_key.strip():
                st.error("API 키를 입력하세요.")
            else:
                try:
                    # build_llm은 기존에 정의된 함수 사용
                    llm = build_llm(api_key)

                    # 실제 호출로 키 검증 (가벼운 ping)
                    llm.invoke("ping")

                    st.session_state.api_key = api_key
                    st.session_state.llm = llm
                    st.success("API 키 확인 완료")
                    st.session_state.step = 1
                    st.rerun()
                except Exception:
                    st.error("API 키를 다시 확인해주세요.")

    with colB:
        st.caption("API 키가 올바르지 않으면 다음 단계로 넘어가지 않습니다.")

    st.stop()