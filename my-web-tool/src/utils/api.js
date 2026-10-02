"use server";

import { generateText } from "ai";

const MODELS = {
  openai: process.env.OPENAI_MODEL || "openai/gpt-5.6-terra",
  claude: process.env.CLAUDE_MODEL || "anthropic/claude-sonnet-5.5",
};

export async function askModel(provider, prompt) {
  const text = typeof prompt === "string" ? prompt.trim() : "";
  if (!text) {
    return { ok: false, message: "Nhập nội dung trước khi gửi." };
  }
  if (text.length > 4000) {
    return { ok: false, message: "Nội dung tối đa 4000 ký tự." };
  }

  const model = MODELS[provider];
  if (!model) {
    return { ok: false, message: "Chọn OpenAI hoặc Claude." };
  }

  try {
    const result = await generateText({ model, prompt: text });
    return { ok: true, text: result.text };
  } catch {
    return {
      ok: false,
      message:
        "Không gọi được model. Kiểm tra AI_GATEWAY_API_KEY trong .env rồi thử lại.",
    };
  }
}
