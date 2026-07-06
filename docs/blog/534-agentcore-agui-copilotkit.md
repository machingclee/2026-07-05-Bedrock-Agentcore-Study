---
title: "Migrate AgentCore From HTTP to AG-UI With CopilotKit Frontend"
date: 2026-07-07
id: blog0534
tag: aws, bedrock, agentcore, agui, copilotkit, strands
img: aws
toc: true
intro: "Convert an AgentCore Strands agent from the HTTP protocol to AG-UI, then wire a CopilotKit React frontend that streams typed events directly from the runtime."
indent: true
wip: false
---

<style>
  img {
    max-width: 660px !important;
  }
  table td:first-child, table th:first-child {
    min-width: 160px;
  }
</style>

### The Problem {#the-problem}

Amazon Bedrock AgentCore Runtime offers four protocols for hosting agents: HTTP, MCP, A2A, and AG-UI. The HTTP protocol works well for backend-to-backend calls, but it leaves the frontend on its own to parse whatever event format the agent framework emits. When we use Strands Agents with `BedrockAgentCoreApp`, the entrypoint yields raw Strands events. Every frontend we build must understand Strands' internal event structure, and tool calls, reasoning steps, and sub-agent handoffs are opaque unless we write custom parsing logic.

AG-UI solves this by standardizing the event stream. It defines a fixed vocabulary of typed events that any AG-UI-compatible frontend can render without knowing which agent framework produced them. Coupled with CopilotKit, we get a production chat UI that surfaces tool calls, streams tokens, and handles state changes out of the box.

This article walks through migrating an existing AgentCore Strands agent from HTTP to AG-UI, then building a Vite + React frontend with CopilotKit that connects directly to the deployed runtime.

### The Starting Point: An HTTP Strands Agent {#starting-point}

Our project is a Restaurant Agent built with the AgentCore CLI. The `agentcore create` command scaffolded it with the Strands framework and HTTP protocol. The agent uses the agents-as-tools pattern: a main orchestrator delegates restaurant queries to a sub-agent, which calls a Python `@tool` that returns mock restaurant data for Tokyo, Paris, and New York.

The original entrypoint at `app/MyRestaurantAgent/main.py` used `BedrockAgentCoreApp`:

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from src.agents.main_agent import main_agent

app = BedrockAgentCoreApp()
log = app.logger


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")

    async for event in main_agent.stream_async(prompt):
        yield event


if __name__ == "__main__":
    app.run()
```

This works, but each `yield`ed event is a raw Strands event. The frontend has no way to distinguish a text delta from a tool call, a reasoning step, or a multi-agent handoff without brittle, framework-specific logic.

The `agentcore.json` configured the runtime with the `"HTTP"` protocol:

```json
{
  "runtimes": [
    {
      "name": "MyRestaurantAgent",
      "protocol": "HTTP",
      "entrypoint": "main.py",
      "codeLocation": "app/MyRestaurantAgent/"
    }
  ]
}
```

### What AG-UI Brings {#what-agui-brings}

AG-UI (Agent-User Interface) is an open protocol for agent-to-frontend communication available at [docs.ag-ui.com](https://docs.ag-ui.com). It specifies a transport (Server-Sent Events over HTTP POST, or WebSocket), a request format (`RunAgentInput` with `threadId`, `runId`, `messages`, `state`, `tools`), and a set of typed response events. The event catalog includes:

| Category | Event Types |
|---|---|
| Lifecycle | `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR` |
| Text Messages | `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END` |
| Tool Calls | `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT` |
| Reasoning | `REASONING_START`, `REASONING_MESSAGE_CONTENT`, `REASONING_END` |
| State | `STATE_SNAPSHOT`, `STATE_DELTA`, `MESSAGES_SNAPSHOT` |
| Activity | `ACTIVITY_SNAPSHOT`, `ACTIVITY_DELTA` |
| Steps | `STEP_STARTED`, `STEP_FINISHED` |

Every event carries a `type` field and a timestamp. The frontend can switch on `type` to render each event appropriately without knowing whether the backend is Strands, LangGraph, CrewAI, or raw Python.

The `ag-ui-strands` package provides a `StrandsAgent` wrapper that translates Strands' internal events into this standard vocabulary. Multi-agent handoffs become `CustomEvent("MultiAgentHandoff")`. Streaming text becomes `TEXT_MESSAGE_CONTENT` deltas. Tool calls become `TOOL_CALL_START` through `TOOL_CALL_RESULT`.

### Migrating the Agent to AG-UI {#migrating-agent}

#### Dependencies {#dependencies}

Add three packages to `pyproject.toml`:

```toml
[project]
requires-python = ">=3.12, <3.14"
dependencies = [
    "ag-ui-protocol >= 0.1.18",
    "ag-ui-strands >= 0.2.0",
    "fastapi >= 0.115.0",
    "uvicorn >= 0.32.0",
    # ... existing: bedrock-agentcore, strands-agents, etc.
]
```

The Python version constraint is important. The `ag-ui-strands` package requires Python 3.12 or later, so we must update `requires-python` from the scaffolded `>=3.10` to `>=3.12, <3.14`. If our project uses a `.python-version` file, we should pin it to `3.12` as well.

#### The New Entrypoint {#new-entrypoint}

Replace the `BedrockAgentCoreApp` with a FastAPI server that exposes the two endpoints AgentCore expects from an AG-UI container:

```python
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
```

The `StrandsAgent` wrapper takes our existing `main_agent` and a human-readable name and description. The `POST /invocations` endpoint receives a `RunAgentInput` payload, runs the agent, and streams each AG-UI event through the `EventEncoder` as SSE. The `GET /ping` endpoint returns the health check that AgentCore uses to verify the container is alive.

Note that we no longer import `BedrockAgentCoreApp`. The AG-UI protocol contract is self-contained: a FastAPI server on port 8080 with `/invocations` and `/ping`. AgentCore handles authentication, scaling, and session isolation around it.

An alternative convenience function exists if we prefer to skip the boilerplate: `create_strands_app(agui_agent, path="/")` from `ag_ui_strands` builds the same FastAPI app and adds CORS middleware automatically.

#### Protocol Configuration {#protocol-config}

Change the protocol field in `agentcore.json` from `"HTTP"` to `"AGUI"`:

```json
{
  "runtimes": [
    {
      "name": "MyRestaurantAgent",
      "protocol": "AGUI",
      "entrypoint": "main.py",
      "codeLocation": "app/MyRestaurantAgent/",
      "runtimeVersion": "PYTHON_3_14",
      "networkMode": "PUBLIC"
    }
  ]
}
```

With this change, `agentcore deploy` provisions the container as an AG-UI runtime. The CLI validates that the protocol is one of `"HTTP" | "MCP" | "A2A" | "AGUI"` and the CDK constructs wire the runtime accordingly.

#### Deployment {#deployment}

Run the deploy:

```bash
cd RestaurantAgent
agentcore deploy --yes
```

The CLI validates the project spec, builds the CDK project, synthesizes the CloudFormation template, checks CDK bootstrap status, and deploys. On first deploy to a new account, we may need to bootstrap CDK first:

```bash
npx cdk bootstrap aws://ACCOUNT_ID/us-east-1
```

After deployment, the runtime ARN is available in the CLI output and in `agentcore/.cli/deployed-state.json`. We can invoke the deployed agent to verify AG-UI events are streaming:

```bash
agentcore invoke --prompt "Find me a fine dining restaurant in Tokyo"
```

### The AG-UI Event Stream {#event-stream}

When the frontend POSTs to `/invocations` with a `RunAgentInput` payload, the response is an SSE stream. A typical exchange for our restaurant agent looks like this:

```
data: {"type":"RUN_STARTED","threadId":"thread-1","runId":"run-1"}

data: {"type":"TEXT_MESSAGE_START","messageId":"msg-1","role":"assistant"}
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":"I'll"}
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":" help"}
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":" you"}

data: {"type":"TOOL_CALL_START","toolCallId":"tc-1","toolCallName":"restaurant_agent"}
data: {"type":"TOOL_CALL_ARGS","toolCallId":"tc-1","delta":"{\"city\":"}
data: {"type":"TOOL_CALL_ARGS","toolCallId":"tc-1","delta":"\"Tokyo\"}"}
data: {"type":"TOOL_CALL_END","toolCallId":"tc-1"}

data: {"type":"TOOL_CALL_RESULT","toolCallId":"tc-1","content":"## Fine Dining..."}

data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-1","delta":" find"}
data: {"type":"TEXT_MESSAGE_END","messageId":"msg-1"}

data: {"type":"RUN_FINISHED","threadId":"thread-1","runId":"run-1"}
```

The frontend can switch on `type` to render each event appropriately: append text deltas character by character, display tool calls as expandable cards with arguments and results, show a spinner during reasoning steps, and update state when `STATE_DELTA` events arrive.

### Building the CopilotKit Frontend {#copilotkit-frontend}

#### Project Setup {#project-setup}

Create a Vite + React + TypeScript project and install the CopilotKit packages:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @copilotkit/react-core @copilotkit/runtime @ag-ui/client
```

#### The Chat Component {#chat-component}

CopilotKit v2 unifies all components under `@copilotkit/react-core/v2`. We use `HttpAgent` from `@ag-ui/client` to connect directly to our AG-UI endpoint, and pass it to CopilotKit via `selfManagedAgents`:

```tsx
import { CopilotKit } from "@copilotkit/react-core/v2";
import { HttpAgent } from "@ag-ui/client";
import "@copilotkit/react-core/v2/styles.css";
import { CopilotChat } from "@copilotkit/react-core/v2";
import { useMemo } from "react";

const IS_LOCAL = import.meta.env.DEV;

const AGENT_URL = IS_LOCAL
  ? "http://localhost:8080/invocations"
  : import.meta.env.VITE_AGENT_URL || "http://localhost:8080/invocations";

const AUTH_TOKEN = import.meta.env.VITE_AUTH_TOKEN || "";

function RestaurantAgentChat() {
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: AGENT_URL,
        headers: AUTH_TOKEN
          ? { Authorization: `Bearer ${AUTH_TOKEN}` }
          : undefined,
      }),
    []
  );

  return (
    <CopilotKit
      selfManagedAgents={{ restaurant_agent: agent }}
      showDevConsole={import.meta.env.DEV}
    >
      <div className="chat-container">
        <header className="chat-header">
          <h1>Restaurant Agent</h1>
          <p>Ask me for restaurant recommendations in Tokyo, Paris, or New York</p>
        </header>
        <CopilotChat
          className="chat-window"
          labels={{
            welcomeMessageText:
              "Hi! I'm your restaurant concierge. I can help you find " +
              "the perfect place to eat.",
            chatInputPlaceholder:
              "e.g., Find me a fine dining restaurant in Tokyo",
          }}
        />
      </div>
    </CopilotKit>
  );
}

export default RestaurantAgentChat;
```

The `HttpAgent` implements the AG-UI client protocol. It sends `RunAgentInput` payloads to the configured URL and parses the SSE response into typed events. CopilotKit consumes those events and renders text messages, tool calls, reasoning steps, and state changes through the `CopilotChat` component.

During local development, the agent runs on `localhost:8080` and Vite proxies to it. For production, set `VITE_AGENT_URL` to the AgentCore invoke URL.

#### Architecture {#architecture}

The data flow from browser to model and back:

```
Browser (Vite + React + CopilotKit)
  |  POST /invocations  {threadId, runId, messages, state, tools}
  |  Content-Type: application/json
  |
  v
AgentCore Runtime (FastAPI on port 8080)
  |  StrandsAgent.run(RunAgentInput)
  |  Strands events -> AG-UI event translation
  |
  v
Strands Agent (main_agent -> restaurant_agent -> restaurant_collaborator)
  |
  v
DeepSeek v3.2 (via Bedrock)
  |
  |  SSE stream: RUN_STARTED, TEXT_MESSAGE_CONTENT, TOOL_CALL_*, RUN_FINISHED
  v
CopilotKit renders tokens, tool cards, reasoning steps in CopilotChat
```

The `selfManagedAgents` pattern means the browser talks directly to AgentCore without a CopilotKit Runtime proxy in between. For production use with authentication, configure AgentCore's inbound JWT authorizer to validate tokens from our identity provider, then pass the token through `HttpAgent` headers.

#### Authentication {#authentication}

AgentCore supports OAuth 2.0 bearer tokens via JWT. To enable browser-to-AgentCore calls without SigV4 signing, configure an inbound authorizer on the runtime:

```json
{
  "runtimes": [
    {
      "name": "MyRestaurantAgent",
      "protocol": "AGUI",
      "authorizerType": "CUSTOM_JWT",
      "authorizerConfiguration": {
        "customJwtAuthorizer": {
          "discoveryUrl": "https://your-idp.com/.well-known/openid-configuration",
          "allowedAudience": ["your-api-audience"],
          "allowedClients": ["your-client-id"]
        }
      }
    }
  ]
}
```

After deploying this configuration, the browser can call AgentCore with `Authorization: Bearer <jwt>`. The `HttpAgent` headers prop forwards the token automatically.

### Gotchas {#gotchas}

#### Python Version {#python-version}

The `ag-ui-strands` package declares `requires-python = ">=3.12, <3.14"`. The AgentCore CLI scaffolds projects with `requires-python = ">=3.10"`, which causes resolution failures. Update both the root `pyproject.toml` and the agent's `pyproject.toml` to `>=3.12, <3.14`, and pin `.python-version` to `3.12`.

#### Imports From Two Packages {#two-packages}

The AG-UI imports come from two separate packages. `StrandsAgent` lives in `ag-ui-strands`. `RunAgentInput` and `EventEncoder` live in `ag-ui-protocol`. Both must be listed in `pyproject.toml`, even though `ag-ui-protocol` is a transitive dependency of `ag-ui-strands`. The IDE and type checkers need the explicit declaration.

#### selfManagedAgents Licensing {#selfmanagedagents}

The `selfManagedAgents` prop on CopilotKit requires an Enterprise Intelligence license for production use. For development and prototyping, it works without one. The production alternative is to deploy a thin CopilotKit Runtime proxy (as a Lambda function or Cloudflare Worker) that handles auth and forwards requests to AgentCore using `HttpAgent` on the server side. This also keeps the AgentCore SigV4 credentials server-side.

#### CDK Bootstrap State {#cdk-bootstrap}

If CDK deployment fails with a `DELETE_FAILED` or `ROLLBACK_FAILED` stack state, the `CDKToolkit` stack may be stuck. Delete it from the AWS Console or via CLI, then redeploy. The `agentcore deploy --yes` command handles bootstrap automatically for clean accounts.

### Summary {#summary}

Migrating from HTTP to AG-UI replaces opaque framework events with a standardized, typed event stream that any AG-UI frontend can consume. The code change on the agent side is swapping `BedrockAgentCoreApp` for a FastAPI server with `StrandsAgent`, plus changing one field in `agentcore.json`. On the frontend, CopilotKit provides a turnkey chat UI that renders the full event catalog: streaming text, tool call cards, reasoning steps, and state updates, all without writing a custom SSE parser.
