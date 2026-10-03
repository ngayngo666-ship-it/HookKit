"use client";

import ChatWindow from "@/components/ChatWindow";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col px-6 py-12">
      <header className="flex items-center gap-3">
        <img src="/logo.svg" alt="" width={40} height={40} />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My Web Tool</h1>
          <p className="text-sm text-stone-600">
            Gửi câu hỏi tới OpenAI, Claude hoặc Gemini. Khóa API chỉ ở máy chủ.
          </p>
        </div>
      </header>

      <ChatWindow />
    </main>
  );
}
