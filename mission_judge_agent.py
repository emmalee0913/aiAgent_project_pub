import os
import json
import base64
from typing import List, Dict, Any

import streamlit as st
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage


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


# =========================================================
# STEP 1) 미션 입력
# =========================================================
if st.session_state.step == 1:
    st.subheader("2) 미션 입력")

    category = st.selectbox("미션 카테고리", ["청소", "숙제", "심부름", "습관"], index=["청소", "숙제", "심부름", "습관"].index(st.session_state.category))
    details = st.text_area("미션 세부사항 (부모 입력)", height=140, value=st.session_state.details)

    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("미션 요약 생성", type="primary"):
            if not details.strip():
                st.error("미션 세부사항을 입력해주세요.")
            else:
                with st.spinner("미션 요약 생성 중..."):
                    mission_obj = mission_get(st.session_state.llm, category, details, policy)

                st.session_state.category = category
                st.session_state.details = details
                st.session_state.mission_obj = mission_obj

                # 저장 (JSON)
                ensure_dir("outputs")
                save_json("outputs/mission_summary.json", mission_obj)

                st.session_state.step = 2
                st.rerun()

    with col2:
        if st.button("초기화"):
            st.session_state.category = "청소"
            st.session_state.details = ""
            st.session_state.mission_obj = None
            st.session_state.photo_paths = []
            st.session_state.photo_obj = None
            st.session_state.result_obj = None
            st.session_state.step = 1
            st.rerun()

    st.stop()


# =========================================================
# STEP 2) 미션 요약 확인 + 확인 버튼
# =========================================================
if st.session_state.step == 2:
    st.subheader("[1] 미션 요약 (확인 후 다음 단계로 이동)")

    mission_obj = st.session_state.mission_obj or {}
    st.write("카테고리:", mission_obj.get("category", st.session_state.category))

    st.write("체크리스트(입력한 세부사항에서 추출):")
    checklist = mission_obj.get("checklist", [])
    if checklist:
        for c in checklist:
            st.write("- " + str(c.get("item", "")))
    else:
        st.warning("체크리스트가 비어 있어요. 미션 세부사항을 더 구체적으로 적어보는 게 좋아요.")

    st.write("입력한 세부사항 전체:")
    st.info(st.session_state.details)

    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("이 내용으로 진행", type="primary"):
            st.session_state.step = 3
            st.rerun()

    with col2:
        if st.button("미션 다시 수정"):
            st.session_state.step = 1
            st.rerun()

    st.stop()


# =========================================================
# STEP 3) 사진 경로 1개씩 추가 + 목록 확인 + 확인 버튼
# =========================================================
if st.session_state.step == 3:
    st.subheader("3) 사진 경로 추가")

    st.caption("사진은 한 번에 1개씩 추가하세요. 최대 10장까지 사용합니다.")
    if st.session_state.category == "청소":
        st.caption("청소는 before/after 2장을 권장합니다. (정확히 2장이면 전후 비교 모드)")

    new_path = st.text_input("사진 경로", placeholder="/Users/.../before.jpg")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if st.button("사진 추가"):
            if not new_path.strip():
                st.error("경로를 입력해주세요.")
            else:
                if len(st.session_state.photo_paths) >= 10:
                    st.error("최대 10장까지만 추가할 수 있어요.")
                else:
                    # 파일 존재 확인(가능한 경우)
                    if not os.path.exists(new_path):
                        st.error("해당 경로에 파일이 없습니다. 경로를 다시 확인해주세요.")
                    else:
                        st.session_state.photo_paths.append(new_path.strip())
                        st.success("추가 완료")
                        st.rerun()

    with col2:
        if st.button("마지막 사진 삭제"):
            if st.session_state.photo_paths:
                st.session_state.photo_paths.pop()
                st.rerun()

    with col3:
        if st.button("사진 전체 초기화"):
            st.session_state.photo_paths = []
            st.rerun()

    st.markdown("### 현재 추가된 사진")
    if not st.session_state.photo_paths:
        st.warning("아직 사진이 없습니다.")
    else:
        for i, p in enumerate(st.session_state.photo_paths, start=1):
            st.write(f"{i}. {p}")

    if st.button("사진 분석 진행", type="primary"):
        if len(st.session_state.photo_paths) == 0:
            st.error("사진을 최소 1장 추가해주세요.")
        else:
            st.session_state.step = 4
            st.rerun()

    st.stop()


# =========================================================
# STEP 4) 사진 분석 요약 (작은 글씨) + 확인 버튼
# =========================================================
if st.session_state.step == 4:
    st.subheader("[2] 사진 분석 (확인 후 최종 판정)")

    with st.spinner("사진 분석 중..."):
        photo_obj = photo_get(
            st.session_state.llm,
            st.session_state.category,
            st.session_state.mission_obj,
            st.session_state.photo_paths
        )
        st.session_state.photo_obj = photo_obj

        # 저장 (JSON)
        ensure_dir("outputs")
        save_json("outputs/photo_analysis.json", photo_obj)

    # 작은 글씨 출력
    observations = photo_obj.get("observations", [])
    notable_changes = photo_obj.get("notable_changes", [])
    caveats = photo_obj.get("caveats", [])

    st.markdown("관찰 요약")
    if observations:
        st.markdown(
            "<div style='font-size:12px; line-height:1.5; color:#444;'>"
            + "<br>".join([f"- {st.escape_markdown(str(x))}" for x in observations])
            + "</div>",
            unsafe_allow_html=True
        )
    else:
        st.caption("관찰 요약이 비어 있어요.")

    st.markdown("전후 변화")
    if notable_changes:
        st.markdown(
            "<div style='font-size:12px; line-height:1.5; color:#444;'>"
            + "<br>".join([f"- {st.escape_markdown(str(x))}" for x in notable_changes])
            + "</div>",
            unsafe_allow_html=True
        )
    else:
        st.caption("전후 변화 항목이 없어요. (청소+2장 조건이 아니거나 변화가 불명확할 수 있어요.)")

    st.markdown("한계")
    if caveats:
        st.markdown(
            "<div style='font-size:12px; line-height:1.5; color:#666;'>"
            + "<br>".join([f"- {st.escape_markdown(str(x))}" for x in caveats])
            + "</div>",
            unsafe_allow_html=True
        )
    else:
        st.caption("한계 항목이 없어요.")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("최종 판정 보기", type="primary"):
            st.session_state.step = 5
            st.rerun()
    with col2:
        if st.button("사진 다시 추가/수정"):
            st.session_state.step = 3
            st.rerun()

    st.stop()


# =========================================================
# STEP 5) 최종 판정 (한 섹션 / 아이콘 / 색)
# =========================================================
if st.session_state.step == 5:
    st.subheader("[3] 최종 판정")

    with st.spinner("최종 판정 중..."):
        result_obj = mission_complete(
            st.session_state.llm,
            st.session_state.mission_obj,
            st.session_state.photo_obj
        )
        st.session_state.result_obj = result_obj

        # 저장 (JSON)
        ensure_dir("outputs")
        save_json("outputs/final_grade.json", result_obj)

    passed = bool(result_obj.get("pass", False))
    percent = result_obj.get("completion_percent", 0)

    # 한 섹션 구성
    if passed:
        st.success(f"🟢 통과 ({percent}%)")
    else:
        st.error(f"🔴 반려 ({percent}%)")

    st.markdown("근거")
    for r in result_obj.get("reason_summary", [])[:6]:
        st.write("- " + str(r))

    if not passed:
        st.markdown("반려 사유 / 추가 요청")
        missing = result_obj.get("missing_or_unclear", [])
        if missing:
            for m in missing[:6]:
                st.write("- " + str(m))

        req = result_obj.get("next_request_to_child", [])
        if req:
            st.markdown("추가로 요청할 증거")
            for x in req[:6]:
                st.write("- " + str(x))

    st.success("판정 완료 및 JSON 저장 완료 (outputs/mission_summary.json, outputs/photo_analysis.json, outputs/final_grade.json)")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("처음부터 다시"):
            st.session_state.step = 0
            st.session_state.api_key = ""
            st.session_state.llm = None
            st.session_state.category = "청소"
            st.session_state.details = ""
            st.session_state.mission_obj = None
            st.session_state.photo_paths = []
            st.session_state.photo_obj = None
            st.session_state.result_obj = None
            st.rerun()

    with col2:
        if st.button("사진 단계로 돌아가기"):
            st.session_state.step = 3
            st.rerun()
}}

주의:
- 글씨/채점표시가 안 보이면 '판독 불가/불명확'이라고 적어라.
- 개인정보/이름 추정 금지.
""".strip()
    }]

    for i, p in enumerate(photo_paths, start=1):
        content.append({"type": "text", "text": f"사진 {i} (path={p})"})
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(p)}})

    msg = HumanMessage(content=content)
    out = llm.invoke([msg]).content.strip()
    obj = safe_json_load(out)

    if isinstance(obj, dict):
        obj.setdefault("mode", mode)
        obj.setdefault("observations", [])
        obj.setdefault("notable_changes", [])
        obj.setdefault("caveats", [])
    return json.dumps(obj, ensure_ascii=False)


@tool
def missionComplete(mission_summary_json: str, photo_analysis_json: str) -> str:
    """
    [3] 최종 판정(완수율/통과 여부).
    반환: JSON 문자열
    """
    llm: ChatOpenAI = st.session_state["llm"]

    mission_obj = safe_json_load(mission_summary_json)
    photo_obj = safe_json_load(photo_analysis_json)

    prompt = f"""
너는 '미션 채점관'이다. 아래 데이터만 근거로 평가해라.

[미션 정보]
{json.dumps({
  "category": mission_obj.get("category"),
  "details_raw": mission_obj.get("details_raw"),
  "mission_summary": mission_obj.get("mission_summary"),
  "checklist": mission_obj.get("checklist", [])
}, ensure_ascii=False)}

[사진 분석]
{json.dumps(photo_obj, ensure_ascii=False)}

채점 규칙:
- checklist 항목별로 달성=1 / 부분=0.5 / 미달=0
- 완수율 = 평균 * 100
- 60% 이상이면 통과(pass=true)
- 확실하지 않으면 보수적으로(부분/미달) 판정
- JSON만 출력

스키마:
{{
  "completion_percent": number,
  "pass": boolean,
  "reason_summary": ["근거 3~6개"],
  "missing_or_unclear": ["불명확/부족한 점 0~6개"],
  "next_request_to_child": ["추가 요청 0~6개"]
}}
""".strip()

    out = llm.invoke(prompt).content.strip()
    obj = safe_json_load(out)
    if not isinstance(obj, dict):
        obj = {"_raw": out}

    # 보정
    try:
        cp = float(obj.get("completion_percent", 0))
    except Exception:
        cp = 0.0
    cp = max(0.0, min(100.0, cp))
    obj["completion_percent"] = cp
    obj["pass"] = bool(cp >= 60.0)

    obj.setdefault("reason_summary", [])
    obj.setdefault("missing_or_unclear", [])
    obj.setdefault("next_request_to_child", [])
    return json.dumps(obj, ensure_ascii=False)


# =========================================================
# LangChain Agent 생성 (tool 연결)
# - 실전에서는 agent가 "도구를 알아서 호출"하도록 만들 수 있지만
#   여기서는 단계형 UX라서, 각 단계에서 agent_executor.invoke로 호출해도 되고
#   tool.invoke로 직접 호출해도 됨.
#
# 요구사항: "langchain으로 tool 연결"이므로 AgentExecutor까지 구성.
# =========================================================
def build_agent_executor(llm: ChatOpenAI):
    tools = [missionGet, photoGet, missionComplete]
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "너는 미션 인증 판정 에이전트다. 사용자가 요청하면 필요한 도구를 호출해 JSON을 만든다. "
         "항상 사실 기반, 추측 금지. 최종 출력은 한국어로 간결히."),
        ("human", "{input}")
    ])
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=False)


# =========================================================
# Streamlit UI
# =========================================================
st.set_page_config(page_title="미션 인증 판정기", layout="centered")
st.title("📸 미션 인증 확인 (OpenAI + LangChain)")

# ---------- session_state 초기화 ----------
if "step" not in st.session_state:
    st.session_state.step = 0  # 0=API, 1=미션입력, 2=미션확인, 3=사진추가, 4=사진요약, 5=최종판정

for k, v in {
    "api_key": "",
    "llm": None,
    "agent_executor": None,
    "category": "청소",
    "details": "",
    "mission_json": None,
    "photo_paths": [],
    "photo_json": None,
    "result_json": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------- 사이드바 ----------
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
    st.subheader("1) OpenAI API Key 입력")

    api_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("API 키 확인", type="primary"):
            if not api_key.strip():
                st.error("API 키를 입력하세요.")
            else:
                try:
                    llm = build_llm(api_key, model_name="gpt-4o-mini")
                    llm.invoke("ping")  # 키 검증

                    st.session_state.api_key = api_key
                    st.session_state.llm = llm
                    st.session_state.agent_executor = build_agent_executor(llm)

                    st.success("API 키 확인 완료")
                    st.session_state.step = 1
                    st.rerun()
                except Exception:
                    st.error("API 키를 다시 확인해주세요.")

    with colB:
        st.caption("API 키가 올바르지 않으면 다음 단계로 넘어가지 않습니다.")

    st.stop()


# =========================================================
# STEP 1) 미션 입력
# =========================================================
if st.session_state.step == 1:
    st.subheader("2) 미션 입력")

    category = st.selectbox(
        "미션 카테고리",
        ["청소", "숙제", "심부름", "습관"],
        index=["청소", "숙제", "심부름", "습관"].index(st.session_state.category),
    )
    details = st.text_area("미션 세부사항 (부모 입력)", height=140, value=st.session_state.details)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("미션 요약 생성", type="primary"):
            if not details.strip():
                st.error("미션 세부사항을 입력해주세요.")
            else:
                with st.spinner("미션 요약 생성 중..."):
                    # LangChain tool 호출(직접) — agent로도 가능하지만 단계형이라 명확하게
                    mission_json = missionGet.invoke({
                        "category": category,
                        "details": details,
                        "policy": POLICY_TEXT
                    })

                st.session_state.category = category
                st.session_state.details = details
                st.session_state.mission_json = mission_json

                ensure_dir("outputs")
                save_json("outputs/mission_summary.json", safe_json_load(mission_json))

                st.session_state.step = 2
                st.rerun()

    with col2:
        if st.button("초기화"):
            st.session_state.category = "청소"
            st.session_state.details = ""
            st.session_state.mission_json = None
            st.session_state.photo_paths = []
            st.session_state.photo_json = None
            st.session_state.result_json = None
            st.session_state.step = 1
            st.rerun()

    st.stop()


# =========================================================
# STEP 2) 미션 요약 확인
# =========================================================
if st.session_state.step == 2:
    st.subheader("[1] 미션 요약 (확인 후 다음 단계로 이동)")

    mission_obj = safe_json_load(st.session_state.mission_json or "{}")

    st.write("카테고리:", mission_obj.get("category", st.session_state.category))

    st.write("체크리스트(입력한 세부사항에서 추출):")
    checklist = mission_obj.get("checklist", [])
    if checklist:
        for c in checklist:
            st.write("- " + str(c.get("item", "")))
    else:
        st.warning("체크리스트가 비어 있어요. 미션 세부사항을 더 구체적으로 적어보는 게 좋아요.")

    st.write("입력한 세부사항 전체:")
    st.info(st.session_state.details)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("이 내용으로 진행", type="primary"):
            st.session_state.step = 3
            st.rerun()
    with col2:
        if st.button("미션 다시 수정"):
            st.session_state.step = 1
            st.rerun()

    st.stop()


# =========================================================
# STEP 3) 사진 경로 추가
# =========================================================
if st.session_state.step == 3:
    st.subheader("3) 사진 경로 추가")

    st.caption("사진은 한 번에 1개씩 추가하세요. 최대 10장까지 사용합니다.")
    if st.session_state.category == "청소":
        st.caption("청소는 before/after 2장을 권장합니다. (정확히 2장이면 전후 비교 모드)")

    new_path = st.text_input("사진 경로", placeholder="/Users/.../before.jpg")

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("사진 추가"):
            if not new_path.strip():
                st.error("경로를 입력해주세요.")
            else:
                if len(st.session_state.photo_paths) >= 10:
                    st.error("최대 10장까지만 추가할 수 있어요.")
                else:
                    if not os.path.exists(new_path):
                        st.error("해당 경로에 파일이 없습니다. 경로를 다시 확인해주세요.")
                    else:
                        st.session_state.photo_paths.append(new_path.strip())
                        st.success("추가 완료")
                        st.rerun()

    with col2:
        if st.button("마지막 사진 삭제"):
            if st.session_state.photo_paths:
                st.session_state.photo_paths.pop()
                st.rerun()

    with col3:
        if st.button("사진 전체 초기화"):
            st.session_state.photo_paths = []
            st.rerun()

    st.markdown("### 현재 추가된 사진")
    if not st.session_state.photo_paths:
        st.warning("아직 사진이 없습니다.")
    else:
        for i, p in enumerate(st.session_state.photo_paths, start=1):
            st.write(f"{i}. {p}")

    if st.button("사진 분석 진행", type="primary"):
        if len(st.session_state.photo_paths) == 0:
            st.error("사진을 최소 1장 추가해주세요.")
        else:
            st.session_state.step = 4
            st.rerun()

    st.stop()


# =========================================================
# STEP 4) 사진 분석 요약(작은 글씨)
# =========================================================
if st.session_state.step == 4:
    st.subheader("[2] 사진 분석 (확인 후 최종 판정)")

    with st.spinner("사진 분석 중..."):
        photo_json = photoGet.invoke({
            "category": st.session_state.category,
            "mission_summary_json": st.session_state.mission_json,
            "photo_paths": st.session_state.photo_paths
        })
        st.session_state.photo_json = photo_json

        ensure_dir("outputs")
        save_json("outputs/photo_analysis.json", safe_json_load(photo_json))

    photo_obj = safe_json_load(st.session_state.photo_json or "{}")

    observations = photo_obj.get("observations", [])
    notable_changes = photo_obj.get("notable_changes", [])
    caveats = photo_obj.get("caveats", [])

    st.markdown("관찰 요약")
    if observations:
        st.markdown(
            "<div style='font-size:12px; line-height:1.5; color:#444;'>"
            + "<br>".join([f"- {st.escape_markdown(str(x))}" for x in observations])
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("관찰 요약이 비어 있어요.")

    st.markdown("전후변화")
    if notable_changes:
        st.markdown(
            "<div style='font-size:12px; line-height:1.5; color:#444;'>"
            + "<br>".join([f"- {st.escape_markdown(str(x))}" for x in notable_changes])
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("전후변화 항목이 없어요. (청소+2장 조건이 아니거나 변화가 불명확할 수 있어요.)")

    st.markdown("한계")
    if caveats:
        st.markdown(
            "<div style='font-size:12px; line-height:1.5; color:#666;'>"
            + "<br>".join([f"- {st.escape_markdown(str(x))}" for x in caveats])
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("한계 항목이 없어요.")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("최종 판정 보기", type="primary"):
            st.session_state.step = 5
            st.rerun()
    with col2:
        if st.button("사진 다시 추가/수정"):
            st.session_state.step = 3
            st.rerun()

    st.stop()


# =========================================================
# STEP 5) 최종 판정
# =========================================================
if st.session_state.step == 5:
    st.subheader("[3] 최종 판정")

    with st.spinner("최종 판정 중..."):
        result_json = missionComplete.invoke({
            "mission_summary_json": st.session_state.mission_json,
            "photo_analysis_json": st.session_state.photo_json
        })
        st.session_state.result_json = result_json

        ensure_dir("outputs")
        save_json("outputs/final_grade.json", safe_json_load(result_json))

    result_obj = safe_json_load(st.session_state.result_json or "{}")

    passed = bool(result_obj.get("pass", False))
    percent = result_obj.get("completion_percent", 0)

    # 아이콘 + 색상
    if passed:
        st.success(f"🟢 통과 ({percent}%)")
    else:
        st.error(f"🔴 반려 ({percent}%)")

    st.markdown("근거")
    for r in result_obj.get("reason_summary", [])[:6]:
        st.write("- " + str(r))

    if not passed:
        st.markdown("반려시 이유")
        for m in result_obj.get("missing_or_unclear", [])[:6]:
            st.write("- " + str(m))

        st.markdown("추가 요청")
        for x in result_obj.get("next_request_to_child", [])[:6]:
            st.write("- " + str(x))

    st.success("판정 완료 및 JSON 저장 완료 (outputs/)")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("처음부터 다시"):
            st.session_state.step = 0
            st.session_state.api_key = ""
            st.session_state.llm = None
            st.session_state.agent_executor = None
            st.session_state.category = "청소"
            st.session_state.details = ""
            st.session_state.mission_json = None
            st.session_state.photo_paths = []
            st.session_state.photo_json = None
            st.session_state.result_json = None
            st.rerun()

    with col2:
        if st.button("사진 단계로 돌아가기"):
            st.session_state.step = 3
            st.rerun()
