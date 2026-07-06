import { CopilotKit } from "@copilotkit/react-core/v2";
import { HttpAgent } from "@ag-ui/client";
import "@copilotkit/react-core/v2/styles.css";
import { CopilotChat } from "@copilotkit/react-core/v2";
import { useMemo } from "react";
import "./App.css";

// Detect if running locally (Vite dev server) or against deployed AgentCore
const IS_LOCAL = import.meta.env.DEV;

// Local dev: agent runs on localhost:8080
// Production: set VITE_AGENT_URL env var to your AgentCore invoke URL
const AGENT_URL = IS_LOCAL
  ? "http://localhost:8080/invocations"
  : import.meta.env.VITE_AGENT_URL || "http://localhost:8080/invocations";

// Auth token from your login system (set via VITE_AUTH_TOKEN env var or your auth hook)
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
          <h1>🍽️ Restaurant Agent</h1>
          <p>Ask me for restaurant recommendations in Tokyo, Paris, or New York</p>
        </header>
        <CopilotChat
          className="chat-window"
          labels={{
            welcomeMessageText:
              "Hi! I'm your restaurant concierge. I can help you find the perfect place to eat — just tell me which city and whether you're looking for fine dining or casual options.",
            chatInputPlaceholder: "e.g., Find me a fine dining restaurant in Tokyo",
          }}
        />
      </div>
    </CopilotKit>
  );
}

export default RestaurantAgentChat;
