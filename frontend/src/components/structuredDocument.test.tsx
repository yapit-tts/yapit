import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AudioContent, BlockErrorBoundary } from "./structuredDocument";
import type { InlineContent, AudioChunk } from "./structuredDocument";

// --- Helpers ---

function makeChunk(idx: number, text: string, ast?: InlineContent[]): AudioChunk {
  return {
    text,
    audio_block_idx: idx,
    ast: ast ?? [{ type: "text", content: text }],
  };
}

// --- AudioContent ---

describe("AudioContent", () => {
  it("renders block ast when no audio chunks", () => {
    const ast: InlineContent[] = [{ type: "text", content: "display only" }];
    const { container } = render(<AudioContent ast={ast} audioChunks={[]} />);
    expect(container.textContent).toBe("display only");
  });

  it("renders chunk ast for single chunk", () => {
    const chunk = makeChunk(0, "hello");
    const { container } = render(<AudioContent audioChunks={[chunk]} />);
    expect(container.textContent).toBe("hello");
  });

  it("falls back to block ast when single chunk has no ast", () => {
    const chunk: AudioChunk = { text: "hello", audio_block_idx: 0 };
    const ast: InlineContent[] = [{ type: "text", content: "from block" }];
    const { container } = render(<AudioContent ast={ast} audioChunks={[chunk]} />);
    expect(container.textContent).toBe("from block");
  });

  it("renders multi-chunk with data-audio-idx spans", () => {
    const chunks = [
      makeChunk(5, "first"),
      makeChunk(6, "second"),
      makeChunk(7, "third"),
    ];
    const { container } = render(<AudioContent audioChunks={chunks} />);

    const spans = container.querySelectorAll("[data-audio-idx]");
    expect(spans).toHaveLength(3);
    expect(spans[0].getAttribute("data-audio-idx")).toBe("5");
    expect(spans[1].getAttribute("data-audio-idx")).toBe("6");
    expect(spans[2].getAttribute("data-audio-idx")).toBe("7");
    expect(spans[0].textContent).toBe("first");
    expect(spans[1].textContent).toBe("second");
    expect(spans[2].textContent).toBe("third");
  });

  it("renders nothing when no chunks and no ast", () => {
    const { container } = render(<AudioContent audioChunks={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders empty spans when multi-chunk has missing ast", () => {
    const chunks: AudioChunk[] = [
      { text: "a", audio_block_idx: 0 },
      { text: "b", audio_block_idx: 1 },
    ];
    const { container } = render(<AudioContent audioChunks={chunks} />);
    const spans = container.querySelectorAll("[data-audio-idx]");
    expect(spans).toHaveLength(2);
    // Spans exist but have no content (graceful degradation)
    expect(spans[0].textContent).toBe("");
    expect(spans[1].textContent).toBe("");
  });

  it("renders formatted content in chunks", () => {
    const chunks = [
      makeChunk(0, "bold", [
        { type: "strong", content: [{ type: "text", content: "bold" }] },
      ]),
    ];
    const { container } = render(<AudioContent audioChunks={chunks} />);
    expect(container.querySelector("strong")?.textContent).toBe("bold");
  });
});

// --- BlockErrorBoundary ---

function ThrowingComponent(): React.ReactNode {
  throw new Error("test error");
}

describe("BlockErrorBoundary", () => {
  it("renders children normally", () => {
    render(
      <BlockErrorBoundary>
        <p>safe content</p>
      </BlockErrorBoundary>,
    );
    expect(screen.getByText("safe content")).toBeInTheDocument();
  });

  it("shows fallback when child throws", () => {
    // Suppress React error boundary console.error
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <BlockErrorBoundary>
        <ThrowingComponent />
      </BlockErrorBoundary>,
    );
    expect(screen.getByText("Content failed to render")).toBeInTheDocument();
    spy.mockRestore();
  });
});
