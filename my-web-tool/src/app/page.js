"use client";

import { useState } from "react";
import { askModel } from "../utils/api";

const PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "claude", label: "Claude" },
];

export default function HomePage() {
  const [provider, setProvider] = useState("openai");
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function onSubmit(event) {
    event.preventDefault();
    setPending(true);
    setError("");
    const result = await askModel(provider, prompt);
    setPending(false);
    if (result.ok) {
      setAnswer(result.text);
      return;
    }
    setAnswer("");
    setError(result.message);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col px-6 py-12">
      <header className="flex items-center gap-3">
        <img src="/logo.svg" alt="" width={40} height={40} />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My Web Tool</h1>
          <p className="text-sm text-stone-600">
            Gửi câu hỏi tới OpenAI hoặc Claude. Khóa API chỉ ở máy chủ.
          </p>
        </div>
      </header>

      <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-4">
        <fieldset className="flex gap-2">
          <legend className="sr-only">Nhà cung cấp</legend>
          {PROVIDERS.map((item) => (
            <label
              key={item.id}
              className={`cursor-pointer rounded-full border px-4 py-2 text-sm ${
                provider === item.id
                  ? "border-stone-900 bg-stone-900 text-white"
                  : "border-stone-300 bg-white text-stone-700"
              }`}
            >
              <input
                className="sr-only"
                type="radio"
                name="provider"
                value={item.id}
                checked={provider === item.id}
                onChange={() => setProvider(item.id)}
              />
              {item.label}
            </label>
          ))}
        </fieldset>

        <label className="flex flex-col gap-2 text-sm font-medium">
          Nội dung
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={6}
            maxLength={4000}
            required
            placeholder="Viết câu hỏi ở đây"
            className="rounded-xl border border-stone-300 bg-white px-3 py-2 font-normal text-stone-900 outline-none focus:border-stone-900"
          />
        </label>

        <button
          type="submit"
          disabled={pending}
          className="rounded-xl bg-stone-900 px-4 py-3 text-sm font-medium text-white disabled:opacity-60"
        >
          {pending ? "Đang gửi…" : "Gửi"}
        </button>
      </form>

      {error ? (
        <p className="mt-6 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </p>
      ) : null}

      {answer ? (
        <section className="mt-6 rounded-xl border border-stone-200 bg-white px-4 py-3">
          <h2 className="text-sm font-medium text-stone-500">Trả lời</h2>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{answer}</p>
        </section>
      ) : null}
    </main>
  );
}
