from strands import Agent
from src.agents.restaurant_agent import restaurant_agent


MAIN_AGENT_PROMPT = """You are the Main Agent — a helpful assistant that coordinates between users and specialized sub-agents.

Your capabilities:
- For restaurant recommendations, dining suggestions, or finding places to eat → Use the "restaurant_agent" tool.
- For general conversation or questions not related to restaurants → Answer directly.

Guidelines:
- When the restaurant_agent asks a clarification question (e.g., about fine dining preference or city), relay that question directly to the user — do not answer on behalf of the user.
- Keep responses concise and helpful.
- If the user's request is not about restaurants, politely let them know you specialize in restaurant recommendations."""


def create_main_agent() -> Agent:
    """Factory — creates a fresh Main Agent with isolated conversation memory."""
    return Agent(
        name="main_agent",
        model="deepseek.v3.2",
        system_prompt=MAIN_AGENT_PROMPT,
        tools=[restaurant_agent],
    )


main_agent = create_main_agent()
