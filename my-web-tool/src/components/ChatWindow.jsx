"use client";

import { useState } from "react";

import { formatMessageTime } from "@/lib/utils";

import ModelSelector from "./ModelSelector";

export default function ChatWindow() {
  const [provider, setProvider] = useState("openai");
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || pending) return;

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text,
      time: formatMessageTime(),
    };

    setMessages((current) => [...current, userMessage]);
    setPrompt("");
    setError("");
    setPending(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, prompt: text }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Không gửi được câu hỏi.");
      }

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: data.text,
          time: formatMessageTime(),
        },
      ]);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Không gửi được câu hỏi.",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="mt-8">
      <ModelSelector
        value={provider}
        onChange={setProvider}
        disabled={pending}
      />

      <div
        className="mt-4 min-h-64 space-y-3 rounded-2xl border border-stone-200 bg-white p-4"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <p className="text-sm text-stone-500">
            Chọn model, nhập câu hỏi và bắt đầu trò chuyện.
          </p>
        ) : (
          messages.map((message) => (
            <article
              key={message.id}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[85%] rounded-2xl bg-stone-900 px-4 py-3 text-white"
                  : "mr-auto max-w-[85%] rounded-2xl bg-stone-100 px-4 py-3 text-stone-900"
              }
            >
              <p className="whitespace-pre-wrap text-sm leading-6">{message.text}</p>
              <p
                className={`mt-1 text-xs ${
                  message.role === "user" ? "text-stone-300" : "text-stone-500"
                }`}
              >
                {message.time}
              </p>
            </article>
          ))
        )}
        {pending ? <p className="text-sm text-stone-500">Đang trả lời…</p> : null}
      </div>

      {error ? (
        <p
          role="alert"
          className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {error}
        </p>
      ) : null}

      <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
        <label htmlFor="chat-prompt" className="sr-only">
          Nội dung
        </label>
        <textarea
          id="chat-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={4}
          maxLength={4000}
          required
          placeholder="Viết câu hỏi ở đây"
          className="rounded-xl border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 outline-none focus:border-stone-900"
        />
        <button
          type="submit"
          disabled={pending || !prompt.trim()}
          className="rounded-xl bg-stone-900 px-4 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Đang gửi…" : "Gửi"}
        </button>
      </form>
    </section>
  );
}
