# Deploy a Custom Strands Agent to AWS Bedrock AgentCore — From Zero to Production

**A step-by-step guide to scaffolding, building with a custom model (DeepSeek), and deploying to any AWS region — plus how to tear it all down.**

---

Amazon Bedrock AgentCore Runtime is a fully managed, serverless execution environment for AI agents. It handles scaling, observability, and the HTTP protocol contract so you focus on your agent logic. The AgentCore CLI scaffolds the project, builds the deployment package, and provisions the infrastructure via CloudFormation.

In this walkthrough, we'll build a **Restaurant Recommendation Agent** using Strands Agents, swap the default Claude model for **DeepSeek v3.2**, deploy to `us-east-1`, and clean everything up. No prior AgentCore experience needed.

---

## What We're Building

```
User → Main Agent → Restaurant Agent → Restaurant Collaborator (@tool)
```

The **Main Agent** coordinates the conversation. It delegates restaurant requests to the **Restaurant Agent**, which gathers the city and fine-dining preference from the user, then calls the **Restaurant Collaborator** — a Python `@tool` that returns matching restaurants. This is the **agents-as-tools** pattern: sub-agents are passed as tools to the orchestrator.

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Node.js | 20+ | `node --version` |
| Python | 3.10+ | `python3 --version` |
| AWS CDK | latest | `npx cdk --version` |
| AWS credentials | configured | `aws sts get-caller-identity` |
| DeepSeek model access | enabled | [Bedrock console → Model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html) |

---

## Step 1: Install the AgentCore CLI

```bash
npm install -g @aws/agentcore
```

Verify:

```bash
agentcore --help
```

---

## Step 2: Create the Project

The `--framework Strands` flag is critical — without it, you get a Harness (config-only agent) instead of a code-driven project.

```bash
agentcore create \
  --name RestaurantAgent \
  --framework Strands \
  --protocol HTTP \
  --model-provider Bedrock \
  --memory none
```

This generates:

```
RestaurantAgent/
  agentcore/
    agentcore.json          # Project & runtime config
    aws-targets.json        # AWS account + region
    .env.local              # Local env vars (gitignored)
    cdk/                    # CDK infrastructure code
  app/MyRestaurantAgent/
    main.py                 # Agent entrypoint
    pyproject.toml          # Python dependencies
    model/load.py           # Model loader
  README.md
```

---

## Step 3: Add a Custom Model (DeepSeek)

The scaffold defaults to Claude Sonnet. To use DeepSeek, edit `model/load.py`:

```python
from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    return BedrockModel(model_id="deepseek.v3.2")
```

Or if you're writing your own agent code directly, specify the model in the `Agent` constructor:

```python
from strands import Agent

agent = Agent(
    name="my_agent",
    model="deepseek.v3.2",          # <-- custom model
    system_prompt="You are helpful.",
    tools=[...],
)
```

---

## Step 4: Write Your Agent Code

Here's the project structure for our restaurant agent:

```
app/MyRestaurantAgent/
  main.py                           # BedrockAgentCoreApp entrypoint
  src/agents/
    main_agent.py                   # Orchestrator agent
    restaurant_agent.py             # Sub-agent (city + fine-dining)
    restaurant_collaborator.py      # @tool — mock restaurant lookup
```

### `main.py` — Entrypoint

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from src.agents.main_agent import main_agent

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")
    async for event in main_agent.stream_async(prompt):
        yield event


if __name__ == "__main__":
    app.run()
```

### `src/agents/main_agent.py` — Orchestrator

```python
from strands import Agent
from src.agents.restaurant_agent import restaurant_agent

MAIN_AGENT_PROMPT = """You are the Main Agent...
For restaurant recommendations → Use the "restaurant_agent" tool.
For general questions → Answer directly."""

main_agent = Agent(
    name="main_agent",
    model="deepseek.v3.2",
    system_prompt=MAIN_AGENT_PROMPT,
    tools=[restaurant_agent],         # agents-as-tools
)
```

### `src/agents/restaurant_agent.py` — Sub-Agent

```python
from strands import Agent
from src.agents.restaurant_collaborator import restaurant_collaborator

RESTAURANT_AGENT_PROMPT = """You are the Restaurant Agent.
1. Determine the city and fine-dining preference.
2. Call restaurant_collaborator with both values."""

restaurant_agent = Agent(
    name="restaurant_agent",
    description="Find restaurants by city and fine-dining preference.",
    system_prompt=RESTAURANT_AGENT_PROMPT,
    tools=[restaurant_collaborator],
)
```

### `src/agents/restaurant_collaborator.py` — Tool

```python
from strands import tool

MOCK_RESTAURANTS = {
    "tokyo": {
        "Yes": [{"name": "Narisawa", "cuisine": "Innovative Japanese", "price_range": "$$$$"}, ...],
        "No":  [{"name": "Ichiran Ramen", "cuisine": "Ramen", "price_range": "$"}, ...],
    },
    "paris": { ... },
    "new york": { ... },
}

@tool
def restaurant_collaborator(city: str, fine_dining: str) -> str:
    """Search for restaurants by city and fine-dining preference."""
    city_data = MOCK_RESTAURANTS.get(city.lower().strip())
    if not city_data:
        return f'No restaurants found for "{city}".'
    restaurants = city_data.get(fine_dining, [])
    return "\n".join(f"- **{r['name']}** | {r['cuisine']} | {r['price_range']}" for r in restaurants)
```

---

## Step 5: Configure the Target Region

The deployment region lives in **one file**: `agentcore/aws-targets.json`.

```json
[
  {
    "name": "default",
    "description": "Default target (us-east-1)",
    "account": "562976154517",
    "region": "us-east-1"
  }
]
```

Change `region` to any AWS region you need — `ap-northeast-1`, `eu-west-1`, etc. Nothing else overrides this.

---

## Step 6: Bootstrap CDK in the Target Region

**Each region needs its own CDK bootstrap.** This creates the S3 assets bucket and IAM roles the deployment uses:

```bash
cd RestaurantAgent
npx cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
```

Example:

```bash
npx cdk bootstrap aws://562976154517/us-east-1
```

If you skip this step, `agentcore deploy` will fail with SSL errors when trying to publish assets to a non-existent S3 bucket.

---

## Step 7: Test Locally

```bash
agentcore dev
```

This starts a local server at `http://localhost:8080`. The agent inspector opens in your browser. Test it:

```bash
agentcore dev "Find me a fine dining restaurant in Tokyo"
```

---

## Step 8: Deploy

```bash
agentcore deploy
```

The CLI:
1. Validates the project
2. Builds the CDK project
3. Synthesizes CloudFormation
4. Publishes assets to S3
5. Provisions the AgentCore Runtime

First deploy takes ~3–5 minutes. Subsequent deploys are faster (dependencies are cached). After it completes, note the **runtime ARN** from the output.

---

## Step 9: Invoke the Deployed Agent

Via the CLI:

```bash
agentcore invoke "Find me a casual restaurant in Paris"
```

Via curl (SigV4 signed):

```bash
curl -X POST \
  "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/<RUNTIME_ARN>/invocations" \
  -H "Content-Type: application/json" \
  --aws-sigv4 "aws:amz:us-east-1:bedrock-agentcore" \
  -d '{"prompt": "Find me a fine dining restaurant in Tokyo"}'
```

Via boto3:

```python
import boto3, json

client = boto3.client("bedrock-agentcore", region_name="us-east-1")
response = client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:us-east-1:...",
    payload=json.dumps({"prompt": "Find me a restaurant in Tokyo"}),
    contentType="application/json",
)
print(response["payload"].read().decode())
```

The HTTP protocol contract expects `{"prompt": "<your message>"}` as the request body and returns JSON or SSE streaming responses.

---

## Step 10: Monitor & Debug

```bash
agentcore status          # Deployment status and runtime ARN
agentcore logs            # Stream CloudWatch logs
agentcore traces list     # View recent traces
```

---

## Step 11: Destroy Everything

The CLI's old `agentcore destroy` command was removed. The current flow:

```bash
agentcore remove all      # Clear resources from local config
agentcore deploy --yes    # Detect empty spec → tear down stack
```

**However**, there's a known issue where `remove all` only clears local state without deleting AWS resources. The most reliable approach is deleting the CloudFormation stack directly:

```bash
# Find the stack name in agentcore/.cli/deployed-state.json
aws cloudformation delete-stack \
  --stack-name AgentCore-RestaurantAgent-default \
  --region us-east-1
```

One command, guaranteed cleanup.

---

## Project File Reference

| File | Purpose |
|------|---------|
| `agentcore/agentcore.json` | Agent runtime config — entrypoint, runtime version, protocol |
| `agentcore/aws-targets.json` | AWS account + region — **the only place region is set** |
| `agentcore/cdk/` | CDK infrastructure — synthesizes CloudFormation |
| `app/<name>/main.py` | Entrypoint — must export `@app.entrypoint` function |
| `app/<name>/pyproject.toml` | Python dependencies |
| `app/<name>/model/load.py` | Model loader — swap model IDs here |

---

## Common Pitfalls & Fixes

| Problem | Cause | Fix |
|---------|-------|-----|
| `SSL routines:ssl3_read_bytes` on deploy | CDK not bootstrapped in target region | Run `npx cdk bootstrap aws://<ACCOUNT>/<REGION>` |
| `Access to Anthropic models is not allowed` | Scaffolded code uses Claude by default | Change model in `model/load.py` or your Agent constructor |
| `No resources defined in project` | `agentcore remove all` wiped the config | Run `agentcore add agent` (interactive) to add it back |
| Harness scaffold instead of code project | Forgot `--framework Strands` | Re-run `agentcore create` with the flag |
| Old deployment still running in another region | Changing `aws-targets.json` doesn't auto-delete old stacks | Manually delete the old CloudFormation stack |
| Deployment goes to wrong region | Cached state confusion | `aws-targets.json` is the only source of truth — check it |

---

## Quick Reference: All Commands

```bash
# Install
npm install -g @aws/agentcore

# Create project
agentcore create --name MyAgent --framework Strands --protocol HTTP --model-provider Bedrock --memory none

# Bootstrap CDK (once per region)
npx cdk bootstrap aws://<ACCOUNT>/<REGION>

# Local dev
agentcore dev

# Deploy
agentcore deploy

# Invoke
agentcore invoke "Your prompt here"

# Monitor
agentcore status
agentcore logs
agentcore traces list

# Destroy
aws cloudformation delete-stack --stack-name AgentCore-MyAgent-default --region <REGION>
```

---

## Wrapping Up

You now have a complete AgentCore workflow: scaffold → build with a custom model → deploy to any region → invoke → destroy. The restaurant agent is a toy example, but the pattern scales — swap the mock tool for a real API, add memory for conversation persistence, or chain more sub-agents for complex workflows.

The key takeaways:

1. **`--framework Strands`** gets you a code-driven project
2. **`aws-targets.json`** is the single place for region configuration
3. **Bootstrap CDK per region** before deploying there
4. **Delete CloudFormation stacks directly** for reliable cleanup
5. **Custom models** are a one-line change in your Agent constructor or `model/load.py`

Happy building! 🚀
