"use client";

import type { KeyboardEvent } from "react";
import { ArrowUp, Mic, Plus } from "lucide-react";
import TextareaAutosize from "react-textarea-autosize";

import { Button } from "@/components/ui/button";

type ChatInputProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
};

export function ChatInput({ value, onChange, onSend, disabled = false }: ChatInputProps) {
  const canSend = value.trim().length > 0 && !disabled;

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend) {
        onSend();
      }
    }
  };

  return (
    <div className="bg-gradient-to-t from-[#212121] via-[#212121] to-transparent px-4 pb-4 pt-6">
      <div className="mx-auto w-full max-w-3xl rounded-2xl bg-[#2f2f2f] p-3">
        <div className="flex items-end gap-2">
          <button className="rounded-md p-2 text-gray-400 hover:bg-[#3a3a3a] hover:text-gray-200" aria-label="add attachment">
            <Plus className="h-5 w-5" />
          </button>

          <TextareaAutosize
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            minRows={1}
            maxRows={8}
            placeholder="有问题，尽管问"
            className="max-h-56 flex-1 resize-none bg-transparent py-2 text-sm text-gray-100 outline-none placeholder:text-gray-500"
          />

          <button className="rounded-md p-2 text-gray-400 hover:bg-[#3a3a3a] hover:text-gray-200" aria-label="voice input">
            <Mic className="h-5 w-5" />
          </button>

          <Button
            size="icon"
            onClick={onSend}
            disabled={!canSend}
            className={[
              "rounded-full transition-colors",
              canSend
                ? "bg-white text-black hover:bg-gray-200"
                : "bg-[#454545] text-gray-300 hover:bg-[#4b4b4b]",
            ].join(" ")}
            aria-label="send message"
          >
            <ArrowUp className="h-4 w-4" />
          </Button>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-gray-500">Agent 也可能会犯错，请核实重要信息。</p>
    </div>
  );
}
