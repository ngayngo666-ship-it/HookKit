"use server";

import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { generateText } from "ai";

const MODELS = {
  openai: process.env.OPENAI_MODEL || "openai/gpt-5.6-terra",
  claude: process.env.CLAUDE_MODEL || "anthropic/claude-sonnet-5.5",
  gemini: (process.env.GEMINI_MODEL || "gemini-3.8-flash").replace(
    /^google\//,
    "",
  ),
};

function resolveModel(provider) {
  if (provider === "gemini") {
    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) {
      return { ok: false, message: "Thiếu GEMINI_API_KEY trong .env." };
    }
    const google = createGoogleGenerativeAI({ apiKey });
    return { ok: true, model: google(MODELS.gemini) };
  }

  const model = MODELS[provider];
  if (!model) {
    return { ok: false, message: "Chọn OpenAI, Claude hoặc Gemini." };
  }
  return { ok: true, model };
}

export async function askModel(provider, prompt) {
  const text = typeof prompt === "string" ? prompt.trim() : "";
  if (!text) {
    return { ok: false, message: "Nhập nội dung trước khi gửi." };
  }
  if (text.length > 4000) {
    return { ok: false, message: "Nội dung tối đa 4000 ký tự." };
  }

  const resolved = resolveModel(provider);
  if (!resolved.ok) {
    return resolved;
  }

  try {
    const result = await generateText({ model: resolved.model, prompt: text });
    return { ok: true, text: result.text };
  } catch {
    const hint =
      provider === "gemini" ? "GEMINI_API_KEY" : "AI_GATEWAY_API_KEY";
    return {
      ok: false,
      message: `Không gọi được model. Kiểm tra ${hint} trong .env rồi thử lại.`,
    };
  }
}
