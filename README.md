# aiAgent_project_pub
0209~0211 

### Mission Judge Agent 
Gemini 모델을 사용해  
1) 미션 체크리스트 생성 →  
2) 사진 관찰 기반 분석 →  
3) 체크리스트 채점(pass/fail)  
을 수행하는 CLI 도구입니다.

---

## Dependencies

이 프로젝트에서 사용하는 **외부 라이브러리** 목록입니다.

```txt
python-dotenv
langchain-core
langchain-google-genai
```

- python-dotenv  
  - `.env` 파일에서 API 키를 로드하기 위해 사용
- langchain-core  
  - LangChain의 Tool, Message 등 핵심 추상화 제공
- langchain-google-genai  
  - Gemini(Google Generative AI) 모델을 LangChain에서 사용하기 위한 어댑터

※ 아래 모듈들은 Python **표준 라이브러리**이므로 별도 설치가 필요 없습니다.  
`os`, `json`, `base64`, `typing`

---

## Setup

### 1. 가상환경 생성 (권장)

```bash
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate  # Windows
```

### 2. 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. API 키 설정

`gemini_api.env` 파일을 생성하고 아래와 같이 작성합니다.

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
```

> 코드 내부에서 `GEMINI_API_KEY`가 존재하면  
> 자동으로 `GOOGLE_API_KEY`로 매핑됩니다.

---

## Run

```bash
python mission_judge_agent_gemini.py
```
