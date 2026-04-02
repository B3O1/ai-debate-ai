import os
import json
import re

# 각 LLM 라이브러리
import groq
import google.generativeai as genai
import cohere

# ==========================================
# 💡 [API 키 하드코딩 세팅]
# ==========================================
여기에api하드코딩


# 클라이언트 초기화
groq_client = groq.Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
cohere_client = cohere.Client(COHERE_API_KEY) if COHERE_API_KEY else None

# ==========================================
# 💡 [전역 메모리 및 토큰 사용량]
# ==========================================
debate_memory = []
user_claims_summary = []
ai_rebuttals_summary = []
model_token_usage = {"groq": 0, "gemini": 0, "cohere": 0}

# 가이드 데이터 (생략 없이 유지)
personality_guide = {
    "cynical": "까칠하고 방어적인 팩트폭격기입니다. 사용자가 억지를 부리면 말투가 차갑고 날카로워지며 빈틈을 무자비하게 찌릅니다.",
    "kind": "다정하고 인내심 많은 멘토입니다. 부드럽고 긍정적인 어조로 대화를 이끌며, 더 나은 방향을 제시하려고 노력합니다.",
    "cold": "감정 공감 0%의 냉정한 채점관입니다. 상대방의 말에 틀린 것이 없을 경우 다른 부족한 점을 억지로라도 찾아내서 공격합니다."
}

attitude_guide = {
    "pragmatist": "극단적 현실주의자. 거창한 명분보다 '비용, 시간, 가성비, 실현 가능성'만 집요하게 따집니다.",
    "egoist": "철저한 이기주의자. 공동체나 도덕보다는 '그래서 당장 나(개인)에게 떨어지는 이득'을 최우선으로 여깁니다.",
    "idealist": "도덕적 이상주의자. 인권, 인류애, 다수의 행복 등 숭고한 가치를 최우선으로 내세웁니다.",
    "data_freak": "데이터 맹신론자. 감정적 호소는 무시하고 오직 통계, 숫자, 논문 출처만 끈질기게 요구합니다.",
    "radical": "극단적 혁명가. 미적지근한 타협을 극혐하며 시스템을 완전히 뒤엎는 파괴적인 해결책만 고집합니다.",
    "innovator": "무한 긍정 혁신가. 리스크를 감수하더라도 새로운 기술과 도전을 적극 지지합니다.",
    "traditionalist": "굳건한 전통수호자. 검증된 기존 방식이 최고라 믿으며 변화가 가져올 리스크를 부각합니다."
}

atmosphere_guide = {
    "adversarial": "우리는 현재 [이해관계가 충돌하는 팽팽한 대립/협상] 중입니다.",
    "cooperative": "우리는 현재 [같은 목표를 달성하기 위해 협력하는 회의] 중입니다.",
    "judge": "당신은 현재 [사용자의 제안을 평가하는 깐깐한 심사위원]입니다.",
    "professor": "당신은 현재 [사용자의 과제를 검사하는 교수님]입니다.",
    "ceo_client": "당신은 현재 [계약을 결정할 갑 사장님]입니다.",
    "bored_friend": "당신은 현재 [딴지 거는 현실 찐친]입니다."
}

# ==========================================
# 💡 [유틸리티 함수]
# ==========================================
DYNAMIC_COHERE_MODEL = None

def get_best_cohere_model():
    global DYNAMIC_COHERE_MODEL
    if DYNAMIC_COHERE_MODEL: return DYNAMIC_COHERE_MODEL
    if not cohere_client: return "command-r-08-2024"
    try:
        models_data = cohere_client.models.list().models
        models = [m.name for m in models_data if 'chat' in m.endpoints]
        priority = ["command-r-08-2024", "c4ai-aya-expanse-8b", "c4ai-aya-expanse-32b"]
        for p in priority:
            if p in models:
                DYNAMIC_COHERE_MODEL = p
                return DYNAMIC_COHERE_MODEL
        # 💡 리스트 자체가 아닌 첫 번째 항목 반환 수정
        DYNAMIC_COHERE_MODEL = models if models else "command-r-08-2024"
        return DYNAMIC_COHERE_MODEL
    except:
        return "command-r-08-2024"

def extract_json(text):
    try:
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            return json.loads(text[start_idx:end_idx+1])
        return None
    except: return None

def remove_cjk(text: str) -> str:
    if not text: return ""
    return re.sub(r'[\u3040-\u30FF\u4E00-\u9FFF\u3400-\u4DBF]+', '', text).strip()

def sanitize_rebuttal(text: str) -> str:
    if not text: return text
    text = remove_cjk(text)
    # 프롬프트 누출 방지 키워드 검사
    leak_keywords = ["당신은 최고 수준", "한국인 토론 전문가", "JSON 형식으로만"]
    for k in leak_keywords:
        if k in text:
            return "⚠️ 응답 생성 오류가 감지되었습니다. 다시 입력해주세요."
    return text

def reset_memory():
    debate_memory.clear()
    user_claims_summary.clear()
    ai_rebuttals_summary.clear()

def create_debate_prompt(user_claim, personality, attitude, atmosphere, topic, history_text):
    p_desc = personality_guide.get(personality, personality_guide["cynical"])
    a_desc = attitude_guide.get(attitude, attitude_guide["egoist"])
    s_desc = atmosphere_guide.get(atmosphere, atmosphere_guide["adversarial"])

    return (
        f"당신은 최고 수준의 한국인 토론 전문가입니다.\n"
        f"[성격 및 말투]: {p_desc}\n[핵심 가치관]: {a_desc}\n[상황]: {s_desc}\n\n"
        f"[현재 주제]: {topic if topic else '자유 토론'}\n"
        "[🔥 핵심 절대 규칙]\n"
        "1. [언어]: 오직 한글만 사용하세요. 한자, 중국어 절대 금지!\n"
        "2. [어투]: 자연스러운 '해요체'나 '하십시오체'를 사용하세요.\n"
        "3. 반박은 3문장 이내로 짧고 날카롭게 하세요.\n\n"
        f"[요약본 히스토리]\n{history_text}\n"
        f"[사용자의 새로운 주장]: {user_claim}\n\n"
        "반드시 JSON 형식으로만 답하세요: { \"ai_rebuttal\": \"...\", \"user_summary\": \"...\", \"ai_summary\": \"...\", \"evaluation\": { \"logic_score\": 0, \"persuasion_score\": 0, \"feedback\": \"...\" } }"
    )

# ==========================================
# 💡 [5. 메인 토론 파이프라인]
# ==========================================
async def run_debate_pipeline(user_claim, model_type="groq", personality="cynical", attitude="egoist", atmosphere="adversarial", topic="", **kwargs):
    global debate_memory, user_claims_summary, ai_rebuttals_summary, model_token_usage
    
    history_text = "".join([f"[턴 {i+1}] 유저: {u} / AI: {a}\n" for i, (u, a) in enumerate(zip(user_claims_summary, ai_rebuttals_summary))])
    full_prompt = create_debate_prompt(user_claim, personality, attitude, atmosphere, topic, history_text)
    
    try:
        if model_type == "groq" and groq_client:
            # 🥊 1차 생성 (오타 수정: choices[0] 추가)
            res1 = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": full_prompt}],
                response_format={"type": "json_object"},
                temperature=0.4
            )
            raw1 = res1.choices[0].message.content
            
            # 🥊 2차 검수 (오타 수정: choices[0] 추가)
            res2 = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": f"아래 JSON에서 한국어는 그대로 두고 한자만 한글로 바꾸세요:\n{raw1}"}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_response = res2.choices[0].message.content
            used_tokens = res1.usage.total_tokens + res2.usage.total_tokens
        
        elif model_type == "cohere" and cohere_client:
            res = cohere_client.chat(model=get_best_cohere_model(), message=full_prompt, temperature=0.7)
            raw_response = res.text
            used_tokens = len(raw_response) * 2
        else:
            raw_response = "{}"
            used_tokens = 0

    except Exception as e:
        print(f"Error: {e}")
        raw_response = "{}"
        used_tokens = 0

    result = extract_json(raw_response)
    if result:
        result['ai_rebuttal'] = sanitize_rebuttal(result.get('ai_rebuttal', ''))
        model_token_usage[model_type] += used_tokens
        debate_memory.append(f"[나]: {user_claim}")
        debate_memory.append(f"[AI]: {result.get('ai_rebuttal', '')}")
        user_claims_summary.append(result.get('user_summary', ''))
        ai_rebuttals_summary.append(result.get('ai_summary', ''))
        return { **result, "user_history": user_claims_summary, "ai_history": ai_rebuttals_summary, "total_tokens": model_token_usage[model_type] }
    
    return { "ai_rebuttal": "통신 에러", "total_tokens": 0 }

# 심판 평가 파이프라인 (생략)
# ai_debate.py 맨 하단의 평가 함수를 이걸로 교체하세요!
async def run_evaluation_pipeline():
    global debate_memory
    chat_history = "\n".join(debate_memory)
    
    if not chat_history:
        return {"score": 0, "logic_score": 0, "persuasion_score": 0, "strengths": ["데이터 없음"], "weaknesses": ["대화 기록 없음"], "feedback": "토론 기록이 존재하지 않습니다."}

    live_model = get_best_cohere_model()
    # 💡 프론트엔드 UI(index.html)가 요구하는 6가지 키값을 명확히 정의
    prompt = (
        f"당신은 냉철한 토론 심판입니다. 아래 대화를 분석해 JSON으로만 답하세요.\n"
        f"반드시 다음 구조를 지키세요:\n"
        f'{{"score": 0~100점, "logic_score": 0~100점, "persuasion_score": 0~100점, '
        f'"strengths": ["장점1", "장점2"], "weaknesses": ["단점1", "단점2"], "feedback": "상세평"}}'
        f"\n\n[대화 기록]\n{chat_history}"
    )
    
    try:
        if cohere_client:
            res = cohere_client.chat(model=live_model, message=prompt, temperature=0.3)
            result = extract_json(res.text)
            if result:
                # 💡 index.html에서 파일 저장 시 필요한 대화 기록도 포함
                result['raw_chat'] = chat_history
                return result
        return {"score": 0, "feedback": "심판 호출 실패"}
    except Exception as e:
        print(f"Eval Error: {e}")
        return {"score": 0, "feedback": f"에러 발생: {str(e)}"}