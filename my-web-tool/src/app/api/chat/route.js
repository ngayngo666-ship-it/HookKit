import { generateReply, PROVIDERS } from "@/lib/ai-providers";

const MAX_PROMPT_LENGTH = 4000;

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Dữ liệu gửi lên không hợp lệ." }, { status: 400 });
  }

  const provider = body?.provider;
  const prompt = typeof body?.prompt === "string" ? body.prompt.trim() : "";

  if (!PROVIDERS.includes(provider)) {
    return Response.json(
      { error: "Chọn OpenAI, Claude hoặc Gemini." },
      { status: 400 },
    );
  }
  if (!prompt) {
    return Response.json({ error: "Nhập nội dung trước khi gửi." }, { status: 400 });
  }
  if (prompt.length > MAX_PROMPT_LENGTH) {
    return Response.json(
      { error: `Nội dung tối đa ${MAX_PROMPT_LENGTH} ký tự.` },
      { status: 400 },
    );
  }

  try {
    const text = await generateReply(provider, prompt);
    return Response.json({ text });
  } catch (error) {
    const messages = {
      MISSING_GEMINI_API_KEY: "Thiếu GEMINI_API_KEY trên máy chủ.",
      MISSING_AI_GATEWAY_CREDENTIALS:
        "Thiếu AI_GATEWAY_API_KEY hoặc VERCEL_OIDC_TOKEN trên máy chủ.",
    };
    const message =
      messages[error instanceof Error ? error.message : ""] ||
      "Không gọi được model. Vui lòng thử lại.";

    return Response.json({ error: message }, { status: 502 });
  }
}
