from fastapi import FastAPI, Request
import uvicorn

app = FastAPI()

@app.post("/meetstream/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("EVENT:", body)
    return {"ok": True}

@app.post("/meetstream/transcript")
async def transcript(request: Request):
    body = await request.json()
    print("TRANSCRIPT:", body)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)