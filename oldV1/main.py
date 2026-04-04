from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 백엔드 로직 임포트
from ai_debate import run_debate_pipeline, run_evaluation_pipeline, reset_memory

app = FastAPI()

# ==========================================
# 💡 [1. CORS 설정] (프론트엔드 통신용)
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 💡 [2. 프론트엔드 데이터 수신 규격 (ERD 동기화)]
# ==========================================
class DebateRequest(BaseModel):
    session_string_id: str             # ERD 추가: 방 고유 식별자 (room_1712...)
    message: str                       # ERD: content에 해당
    model_type: str = "groq"           # ERD: model_type에 해당
    atmosphere: str = "aggressive"     # ERD: atmosphere (기존 debate_style)
    topic: str = ""                    # 💡 커스텀 설정이 여기로 모두 뭉쳐서 들어옴

# ==========================================
# 💡 [3. 라우터 (API 엔드포인트)]
# ==========================================

# ① 토론 채팅 처리
@app.post("/api/v1/debate/chat")
async def start_debate(req: DebateRequest):
    try:
        result = await run_debate_pipeline(
            user_claim=req.message,
            model_type=req.model_type,
            atmosphere=req.atmosphere,
            topic=req.topic  # 뭉쳐진 텍스트 전달
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