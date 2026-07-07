import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from ag_ui_strands import StrandsAgent
from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from src.agents.main_agent import main_agent

agui_agent = StrandsAgent(
    agent=main_agent,
    name="restaurant_agent",
    description=(
        "Find restaurants for a user based on city and fine-dining preference. "
        "Handles determining city and dining preference, then returns matching "
        "restaurant recommendations."
    ),
)

app = FastAPI()


@app.post("/invocations")
async def invocations(input_data: dict, request: Request):
    accept_header = request.headers.get("accept")
    encoder = EventEncoder(accept=accept_header)

    async def event_generator():
        run_input = RunAgentInput(**input_data)
        async for event in agui_agent.run(run_input):
            yield encoder.encode(event)

    return StreamingResponse(
        event_generator(),
        media_type=encoder.get_content_type(),
    )


@app.get("/ping")
async def ping():
    return JSONResponse({"status": "Healthy"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
