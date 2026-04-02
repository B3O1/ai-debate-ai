from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# 백엔드 로직 임포트 (방금 완성한 ai_debate.py 연결)
from ai_debate import run_debate_pipeline, run_evaluation_pipeline, reset_memory

app = FastAPI()

# ==========================================
# 💡 [1. CORS 설정] (프론트엔드 통신용)
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용 (개발용)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 💡 [2. 프론트엔드 데이터 수신 규격 (매트릭스 분리 완료)]
# ==========================================
class DebateRequest(BaseModel):
    message: str
    model_type: str = "groq"
    personality: str = "cynical"      # 성격 (말투/온도)
    attitude: str = "egoist"          # 태도 (논리/가치관)
    atmosphere: str = "adversarial"   # 상황 및 분위기
    topic: str = ""
    background: Optional[str] = None
    goal: Optional[str] = None
    condition: Optional[str] = None

# ==========================================
# 💡 [3. 라우터 (API 엔드포인트)]
# ==========================================

# ① 토론 채팅 처리
@app.post("/api/v1/debate/chat")
async def start_debate(req: DebateRequest):
    try:
        # 프론트에서 받은 personality와 attitude를 그대로 백엔드에 꽂아줍니다!
        result = await run_debate_pipeline(
            user_claim=req.message,
            model_type=req.model_type,
            personality=req.personality,
            attitude=req.attitude,
            atmosphere=req.atmosphere,
            topic=req.topic,
            background=req.background,
            goal=req.goal,
            condition=req.condition
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ② 토론 종료 및 코히어 심판 평가
@app.post("/api/v1/debate/evaluate")
async def evaluate_debate():
    try:
        result = await run_evaluation_pipeline()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ③ 방 입장 시 메모리 초기화
@app.post("/api/v1/debate/reset")
async def reset_debate():
    try:
        reset_memory()
        return {"status": "success", "message": "Memory reset complete"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))