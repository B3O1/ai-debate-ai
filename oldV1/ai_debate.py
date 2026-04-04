import os
import json
import re

import groq
import google.generativeai as genai
import cohere
from dotenv import load_dotenv
load_dotenv() # 이 줄이 있어야 .env 파일을 읽어옵니다!
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
groq_client = groq.Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
cohere_client = cohere.Client(COHERE_API_KEY) if COHERE_API_KEY else None

debate_memory = []
user_claims_summary = []
ai_rebuttals_summary = []
model_token_usage = {"groq": 0, "gemini": 0, "cohere": 0}

atmosphere_guide = {
    "aggressive": "매우 공격적이고 자비 없는 팩트폭격기입니다. 상대방의 주장에 있는 논리적 허점, 모순, 억지를 찾아내어 무자비하게 짓밟습니다. 감정적인 호소는 철저히 조롱하고 무시하며, 얼음장처럼 차갑고 날카로운 어조로 숨 막히게 압박하세요. 절대 타협하거나 동의하지 않으며, 상대를 완벽하게 논파하는 것만을 목표로 합니다. 단, 매 턴마다 똑같은 표현이나 비꼬기를 앵무새처럼 반복하지 말고, 상대의 발언에 맞춰 다채롭고 창의적인 수사의문문과 날카로운 어휘를 구사하세요.",
    "logical": "감정에 휩쓸리지 않고 오직 객관적인 데이터, 근거, 논리적 타당성만 깐깐하게 따지는 이성적인 토론자입니다.",
    "kind": "다정하고 인내심 많은 멘토입니다. 부드럽고 존중하는 어조로 대화를 이끌며, 상대방이 더 나은 논리를 펼칠 수 있도록 돕습니다."
}

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
    leak_keywords = ["당신은 최고 수준", "한국인 토론 전문가", "JSON 형식으로만"]
    for k in leak_keywords:
        if k in text:
            return "⚠️ 응답 생성 오류가 감지되었습니다. 다시 입력해주세요."
    return text

def reset_memory():
    debate_memory.clear()
    user_claims_summary.clear()
    ai_rebuttals_summary.clear()

def create_debate_prompt(user_claim, atmosphere, topic, history_text):
    p_desc = atmosphere_guide.get(atmosphere, atmosphere_guide["aggressive"])

    if atmosphere == "aggressive":
        style_rules = (
            "4. [점수별 반응 및 예의 수준]: 당신이 평가한 점수에 따라 ai_rebuttal의 어투를 다르게 하세요. (점수 언급 금지, 3문장 이내 유지)\n"
            "   - 둘 다 50점 이상 (존대 100%): 정중한 어조로 다른 사각지대를 찌르며 공격하세요.\n"
            "   - 둘 중 하나만 50점 미만 (존대 80%): 가시 돋친 말투로 논리/설득력의 부족함을 쏘아붙이세요.\n"
            "   - 둘 다 50점 미만 (존대 50%): 반말을 섞으며 '여기 뭐 하러 오셨습니까?'라며 한심해하세요.\n"
            "   - 둘 다 20점 미만 (존대 0%, 🚨이스터에그): 무의미한 타자(럳룯자ㅣ) 등 트롤링 시 100% 반말로 '장난하냐? 그냥 가라.'라며 짓밟으세요."
        )
    elif atmosphere == "logical":
        style_rules = (
            "4. [점수별 반응 및 문장 길이]: 당신이 평가한 점수에 따라 ai_rebuttal의 **문장 길이**를 철저히 다르게 하세요. (어투는 항상 차갑고 깐깐한 정중함 유지, 점수 언급 금지)\n"
            "   - 둘 다 50점 이상 (3문장 이내): '그럼 이 부분의 논리적 허점은 어쩔 겁니까?'라며 화제를 전환해 다른 사각지대를 공격하세요.\n"
            "   - 둘 중 하나만 50점 미만 (정확히 4문장): 상대의 주장에서 부족한 논리나 증거를 깐깐하게 꼬집으며 대화를 약간 길게 끌고 가세요.\n"
            "   - 둘 다 50점 미만 (정확히 6문장): 주장의 모순점과 데이터 부재를 아주 집요하고 숨막히도록 조목조목 상세히 따져 물으세요.\n"
            "   - 둘 다 20점 미만 (단 1문장, 🚨이스터에그): 무의미한 타자(럳룯자ㅣ) 등 명백한 트롤링 시 발동. '논리적 대화가 불가능한 상대와는 토론할 가치가 없습니다.' 처럼 차갑게 딱 한 마디만 남기세요."
        )
    else: 
        style_rules = (
            "4. [점수별 반응 및 멘토링]: 당신이 평가한 점수에 따라 ai_rebuttal의 어투를 다르게 하되, **끝까지 다정하고 친절한 존댓말**을 유지하세요. (점수 언급 금지)\n"
            "   - 둘 다 50점 이상: 평소처럼 부드럽게 반박하며 건강한 토론을 이어가세요.\n"
            "   - 설득력만 50점 미만: 문장에 대한 부드러운 반박을 섞으면서, '이럴 땐 이렇게 말씀하시면 상대를 설득하는 데 훨씬 효과가 좋답니다'라는 식의 조언을 추가하세요.\n"
            "   - 논리력만 50점 미만: '앞서 하신 말씀이나 상황과 앞뒤가 조금 안 맞는 것 같아요. 생각이 아직 덜 정리되신 것 같으니 다시 한번 차분히 정리해 보실까요?'라는 식으로 부드럽게 짚어주세요.\n"
            "   - 둘 다 50점 미만: 위 두 가지(설득력 조언 + 논리 정리 제안)를 모두 합쳐서 멘토처럼 아주 친절하게 피드백해 주세요.\n"
            "   - 둘 다 20점 미만 (🚨이스터에그): 무의미한 타자나 억지 주장을 보더라도 절대 화내지 말고, '우리 조금 쉬었다가 다시 이야기해 볼까요? 😊'라며 휴식을 권유하는 따뜻한 멘트만 남기세요."
        )

    return (
        f"당신은 최고 수준의 한국인 토론 전문가입니다.\n"
        f"[토론 분위기 및 말투]: {p_desc}\n\n"
        f"[현재 주제(상황극 포함)]: {topic if topic else '자유 토론'}\n"
        "[🔥 핵심 절대 규칙]\n"
        "1. [언어]: 오직 한글만 사용하세요. 한자, 중국어 절대 금지!\n"
        "2. [어투]: 자연스러운 '해요체'나 '하십시오체'를 사용하세요. (단, 트롤링 감지 시 즉시 100% 반말 사용)\n"
        "3. [문맥 파악 및 스탠스 불변]: 한국어 특성상 주어가 자주 생략되므로 절대 억측하지 마세요. 또한 사용자가 명시적으로 입장을 번복하지 않는 한, 사용자의 찬성/반대 스탠스는 처음부터 끝까지 절대 변하지 않는다고 확신하세요.\n"
        "4. [깐깐한 트롤링 심판]: 무의미한 자음/모음(ㅁㄴㅇㄹ)이나 장난식 채팅 등 명백한 헛소리일 경우 즉시 논리 0점 처리하세요.\n"
        "5. [3인칭 관찰자 시점 절대 금지 🚨]: '사용자의 주장은~', '학생의 주장은~'처럼 제3자 평가자처럼 말하지 마세요. 당신은 심판이 아니라 직접 맞붙는 1:1 토론자입니다. 반드시 나(AI)와 너(사용자)의 대화로, 상대방을 향해 직접적으로 반박하세요.\n"
        f"{style_rules}\n\n"
        f"[요약본 히스토리]\n{history_text}\n"
        f"[사용자의 새로운 주장]: {user_claim}\n\n"
        "🔥 반드시 아래 JSON 형식의 사고 흐름을 거쳐서 답하세요 (명시된 key값 절대 유지):\n"
        "{\n"
        "  \"step1_context\": \"생략된 주어와 진짜 의도 파악\",\n"
        "  \"step2_attitude\": \"내 점수와 규칙을 바탕으로 이번 턴의 내 말투(반말, 비꼬기 등) 결정\",\n"
        "  \"evaluation\": { \"logic_score\": 0, \"persuasion_score\": 0, \"feedback\": \"...\", \"is_emotional\": false },\n"
        "  \"ai_rebuttal\": \"결정된 태도로 작성된 최종 반응\",\n"
        "  \"user_summary\": \"...\",\n"
        "  \"ai_summary\": \"...\"\n"
        "}"
    )

async def run_debate_pipeline(user_claim, model_type="groq", atmosphere="aggressive", topic="", **kwargs):
    global debate_memory, user_claims_summary, ai_rebuttals_summary, model_token_usage
    
    history_text = "".join([f"[턴 {i+1}] 유저: {u} / AI: {a}\n" for i, (u, a) in enumerate(zip(user_claims_summary, ai_rebuttals_summary))])
    full_prompt = create_debate_prompt(user_claim, atmosphere, topic, history_text)
    
    try:
        if model_type == "groq" and groq_client:
            # 1. 본체 AI 호출 (속마음 포함 전체 JSON)
            res1 = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": full_prompt}],
                response_format={"type": "json_object"},
                temperature=0.4
            )
            raw1 = res1.choices[0].message.content
            
            # 2. JSON 파싱 후 'ai_rebuttal' 알맹이만 빼냄 (토큰 다이어트)
            parsed_result = extract_json(raw1)
            
            if parsed_result and "ai_rebuttal" in parsed_result:
                target_text = parsed_result["ai_rebuttal"]
                
                # 3. 알맹이 하나만 번역기에 던져서 매운맛 보존 및 외계어 차단
                trans_prompt = f"당신은 완벽한 한국어 교정기입니다. 다음 텍스트의 본래 어조와 성격은 100% 그대로 살리되, 힌디어나 한자 등 외국어 및 외계어만 완벽한 한국어로 번역/교정하세요. 부연 설명이나 추가적인 문장 없이 교정된 결과만 딱 텍스트로 출력하세요:\n\n{target_text}"
                
                res2 = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": trans_prompt}],
                    temperature=0.0
                )
                
                # 4. 교정된 깔끔한 텍스트를 다시 기존 JSON 구조에 합체
                parsed_result["ai_rebuttal"] = res2.choices[0].message.content.strip()
                raw_response = json.dumps(parsed_result, ensure_ascii=False)
                used_tokens = res1.usage.total_tokens + res2.usage.total_tokens
            else:
                raw_response = raw1
                used_tokens = res1.usage.total_tokens
            
        elif model_type == "gemini" and GOOGLE_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            res = model.generate_content(full_prompt)
            raw_response = res.text
            used_tokens = len(raw_response) * 2
            
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

async def run_evaluation_pipeline():
    global debate_memory
    chat_history = "\n".join(debate_memory)
    
    if not chat_history:
        return {"score": 0, "logic_score": 0, "persuasion_score": 0, "strengths": ["데이터 없음"], "weaknesses": ["대화 기록 없음"], "feedback": "토론 기록이 존재하지 않습니다."}

    live_model = get_best_cohere_model()
    prompt = (
        f"당신은 가장 공정하고 냉철한 토론 심판입니다. 아래 대화 기록을 분석해 JSON으로만 답하세요.\n\n"
        "[심판 절대 규칙]\n"
        "1. 편파 판정 금지: AI가 헛소리(외계어, 섀도복싱, 똑같은 비꼬기 반복)를 했다면 가차 없이 AI를 비판하세요.\n"
        "2. 꼰대식 채점 금지: 사용자가 캐주얼한 말투를 썼다고 무조건 '감정적'이라고 깎아내리지 마세요. 팩트와 논리 뼈대를 높이 평가하세요.\n\n"
        "🔥 아래 JSON 구조를 지켜 속마음 분석 후 최종 점수를 내세요:\n"
        "{\n"
        "  \"step1_turn_by_turn\": \"전체 흐름 요약\",\n"
        "  \"step2_ai_fault_check\": \"AI가 외국어를 썼거나 섀도복싱을 했는지 심사\",\n"
        "  \"score\": 0, \"logic_score\": 0, \"persuasion_score\": 0,\n"
        "  \"strengths\": [\"장점1\", \"장점2\"], \"weaknesses\": [\"단점1\", \"단점2\"], \"feedback\": \"상세평\"\n"
        "}\n\n"
        f"[대화 기록]\n{chat_history}"
    )
    
    try:
        if cohere_client:
            res = cohere_client.chat(model=live_model, message=prompt, temperature=0.3)
            result = extract_json(res.text)
            if result:
                result['raw_chat'] = chat_history
                return result
        return {"score": 0, "feedback": "심판 호출 실패"}
    except Exception as e:
        print(f"Eval Error: {e}")
        return {"score": 0, "feedback": f"에러 발생: {str(e)}"}