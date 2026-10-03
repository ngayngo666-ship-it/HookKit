"use client";

import { cn } from "@/lib/utils";

const MODELS = [
  { id: "openai", label: "OpenAI" },
  { id: "claude", label: "Claude" },
  { id: "gemini", label: "Gemini" },
];

export default function ModelSelector({ value, onChange, disabled = false }) {
  return (
    <fieldset className="flex flex-wrap gap-2" disabled={disabled}>
      <legend className="sr-only">Chọn mô hình AI</legend>
      {MODELS.map((model) => (
        <label
          key={model.id}
          className={cn(
            "cursor-pointer rounded-full border px-4 py-2 text-sm transition-colors",
            value === model.id
              ? "border-stone-900 bg-stone-900 text-white"
              : "border-stone-300 bg-white text-stone-700 hover:border-stone-500",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          <input
            className="sr-only"
            type="radio"
            name="provider"
            value={model.id}
            checked={value === model.id}
            onChange={() => onChange(model.id)}
          />
          {model.label}
        </label>
      ))}
    </fieldset>
  );
}
