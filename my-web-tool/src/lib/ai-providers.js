import "server-only";

import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import { generateText } from "ai";

const MODELS = {
  openai: process.env.OPENAI_MODEL || "openai/gpt-5.6-terra",
  claude: process.env.CLAUDE_MODEL || "anthropic/claude-sonnet-5.5",
  gemini: (process.env.GEMINI_MODEL || "gemini-3.8-flash").replace(
    /^google\//,
    "",
  ),
};

export const PROVIDERS = ["openai", "claude", "gemini"];

function getModel(provider) {
  if (provider === "openai" && process.env.OPENAI_API_KEY) {
    const openai = createOpenAI({ apiKey: process.env.OPENAI_API_KEY });
    return openai(MODELS.openai.replace(/^openai\//, ""));
  }

  if (provider === "gemini") {
    if (!process.env.GEMINI_API_KEY) {
      throw new Error("MISSING_GEMINI_API_KEY");
    }

    const google = createGoogleGenerativeAI({
      apiKey: process.env.GEMINI_API_KEY,
    });
    return google(MODELS.gemini);
  }

  if (!["openai", "claude"].includes(provider)) {
    throw new Error("INVALID_PROVIDER");
  }
  if (!process.env.AI_GATEWAY_API_KEY && !process.env.VERCEL_OIDC_TOKEN) {
    throw new Error(
      provider === "openai"
        ? "MISSING_OPENAI_CREDENTIALS"
        : "MISSING_AI_GATEWAY_CREDENTIALS",
    );
  }

  return MODELS[provider];
}

export async function generateReply(provider, prompt) {
  const { text } = await generateText({
    model: getModel(provider),
    prompt,
  });

  return text;
}
