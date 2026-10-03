import "./globals.css";

export const metadata = {
  title: "My Web Tool",
  description: "Hỏi OpenAI, Claude hoặc Gemini từ một trang.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="vi">
      <body className="min-h-screen bg-stone-100 text-stone-900 antialiased">
        {children}
      </body>
    </html>
  );
}
