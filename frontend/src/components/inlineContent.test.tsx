import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { InlineContentRenderer } from "./inlineContent";
import type { InlineContent } from "./structuredDocument";

// === Node type rendering ===

describe("InlineContentRenderer", () => {
  it("renders plain text", () => {
    const nodes: InlineContent[] = [{ type: "text", content: "hello world" }];
    render(<InlineContentRenderer nodes={nodes} />);
    expect(screen.getByText("hello world")).toBeInTheDocument();
  });

  it("renders code span", () => {
    const nodes: InlineContent[] = [{ type: "code_span", content: "const x" }];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const code = container.querySelector("code");
    expect(code).toBeInTheDocument();
    expect(code?.textContent).toBe("const x");
  });

  it("renders strong", () => {
    const nodes: InlineContent[] = [
      { type: "strong", content: [{ type: "text", content: "bold" }] },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const strong = container.querySelector("strong");
    expect(strong).toBeInTheDocument();
    expect(strong?.textContent).toBe("bold");
  });

  it("renders emphasis", () => {
    const nodes: InlineContent[] = [
      { type: "emphasis", content: [{ type: "text", content: "italic" }] },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const em = container.querySelector("em");
    expect(em).toBeInTheDocument();
    expect(em?.textContent).toBe("italic");
  });

  it("renders link with href", () => {
    const nodes: InlineContent[] = [
      {
        type: "link",
        href: "https://example.com",
        content: [{ type: "text", content: "click me" }],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const a = container.querySelector("a");
    expect(a).toBeInTheDocument();
    expect(a?.getAttribute("href")).toBe("https://example.com");
    expect(a?.textContent).toBe("click me");
  });

  it("renders inline image", () => {
    const nodes: InlineContent[] = [
      { type: "inline_image", src: "img.png", alt: "photo" },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const img = container.querySelector("img");
    expect(img).toBeInTheDocument();
    expect(img?.getAttribute("src")).toBe("img.png");
    expect(img?.getAttribute("alt")).toBe("photo");
  });

  it("renders inline math with katex class", () => {
    const nodes: InlineContent[] = [
      { type: "math_inline", content: "\\alpha" },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    // KaTeX renders into a span — check the katex class is present
    const katexEl = container.querySelector(".katex");
    expect(katexEl).toBeInTheDocument();
  });

  it("renders show content (display-only)", () => {
    const nodes: InlineContent[] = [
      {
        type: "show",
        content: [{ type: "text", content: "visible reference" }],
      },
    ];
    render(<InlineContentRenderer nodes={nodes} />);
    expect(screen.getByText("visible reference")).toBeInTheDocument();
  });

  it("does not render speak content (TTS-only)", () => {
    const nodes: InlineContent[] = [
      { type: "text", content: "before" },
      { type: "speak", content: "spoken only" },
      { type: "text", content: "after" },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.textContent).toContain("before");
    expect(container.textContent).toContain("after");
    expect(container.textContent).not.toContain("spoken only");
  });

  it("renders hardbreak as <br>", () => {
    const nodes: InlineContent[] = [
      { type: "text", content: "Line one" },
      { type: "hardbreak" },
      { type: "text", content: "Line two" },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.querySelector("br")).toBeInTheDocument();
    expect(container.textContent).toContain("Line one");
    expect(container.textContent).toContain("Line two");
  });

  it("renders footnote ref as superscript link", () => {
    const nodes: InlineContent[] = [
      { type: "footnote_ref", label: "1", has_content: true },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const sup = container.querySelector("sup");
    expect(sup).toBeInTheDocument();
    const a = sup?.querySelector("a");
    expect(a).toBeInTheDocument();
    expect(a?.getAttribute("href")).toBe("#fn-1");
    expect(a?.textContent).toBe("[1]");
  });

  it("renders footnote ref without link when no content", () => {
    const nodes: InlineContent[] = [
      { type: "footnote_ref", label: "2", has_content: false },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const sup = container.querySelector("sup");
    expect(sup).toBeInTheDocument();
    expect(sup?.textContent).toBe("[^2]");
    expect(sup?.querySelector("a")).toBeNull();
  });
});

// === Nesting ===

describe("InlineContentRenderer nesting", () => {
  it("renders strong inside link", () => {
    const nodes: InlineContent[] = [
      {
        type: "link",
        href: "/doc",
        content: [
          { type: "strong", content: [{ type: "text", content: "bold link" }] },
        ],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const a = container.querySelector("a");
    const strong = a?.querySelector("strong");
    expect(strong?.textContent).toBe("bold link");
  });

  it("renders math inside show", () => {
    const nodes: InlineContent[] = [
      {
        type: "show",
        content: [
          { type: "text", content: "ref " },
          { type: "math_inline", content: "x^2" },
        ],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.querySelector(".katex")).toBeInTheDocument();
    expect(screen.getByText("ref")).toBeInTheDocument();
  });

  it("renders deeply nested content", () => {
    const nodes: InlineContent[] = [
      {
        type: "emphasis",
        content: [
          {
            type: "strong",
            content: [
              {
                type: "link",
                href: "#",
                content: [{ type: "text", content: "deep" }],
              },
            ],
          },
        ],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const em = container.querySelector("em");
    const strong = em?.querySelector("strong");
    const a = strong?.querySelector("a");
    expect(a?.textContent).toBe("deep");
  });
});

// === Robustness (don't crash on missing/malformed data) ===

describe("InlineContentRenderer robustness", () => {
  it("renders empty for empty array", () => {
    const { container } = render(<InlineContentRenderer nodes={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders empty for undefined nodes", () => {
    const { container } = render(
      <InlineContentRenderer nodes={undefined as unknown as InlineContent[]} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders empty for null nodes", () => {
    const { container } = render(
      <InlineContentRenderer nodes={null as unknown as InlineContent[]} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("skips unknown node types without crashing", () => {
    const nodes = [
      { type: "text", content: "ok" },
      { type: "unknown_future_type", content: "ignored" },
      { type: "text", content: "also ok" },
    ] as InlineContent[];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.textContent).toContain("ok");
    expect(container.textContent).toContain("also ok");
    expect(container.textContent).not.toContain("ignored");
  });

  it("handles text node with empty content", () => {
    const nodes: InlineContent[] = [{ type: "text", content: "" }];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.innerHTML).toBe("");
  });

  it("handles math_inline with empty content without crashing", () => {
    const nodes: InlineContent[] = [{ type: "math_inline", content: "" }];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    // Should render something (KaTeX may render empty) but not throw
    expect(container).toBeInTheDocument();
  });
});

// === Video links ===

describe("InlineContentRenderer video links", () => {
  it("renders .mp4 link as video element", () => {
    const nodes: InlineContent[] = [
      {
        type: "link",
        href: "https://example.com/clip.mp4",
        content: [{ type: "text", content: "video" }],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    const video = container.querySelector("video");
    expect(video).toBeInTheDocument();
    expect(video?.getAttribute("src")).toBe("https://example.com/clip.mp4");
    expect(video?.hasAttribute("controls")).toBe(true);
    expect(container.querySelector("a")).toBeNull();
  });

  it("renders .webm link as video element", () => {
    const nodes: InlineContent[] = [
      {
        type: "link",
        href: "/videos/demo.webm",
        content: [{ type: "text", content: "demo" }],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.querySelector("video")).toBeInTheDocument();
  });

  it("renders normal link as anchor, not video", () => {
    const nodes: InlineContent[] = [
      {
        type: "link",
        href: "https://example.com/page",
        content: [{ type: "text", content: "link" }],
      },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.querySelector("a")).toBeInTheDocument();
    expect(container.querySelector("video")).toBeNull();
  });
});

// === Nested list handling ===

describe("InlineContentRenderer nested lists", () => {
  it("skips list nodes (rendered at block level, not inline)", () => {
    // ListContent is rendered by NestedList component in ListBlockView,
    // not by InlineContentRenderer — avoids <ul> inside <span> (invalid HTML)
    const nodes: InlineContent[] = [
      { type: "text", content: "Before " },
      {
        type: "list",
        ordered: false,
        items: [[{ type: "text", content: "Nested" }]],
      } as InlineContent,
      { type: "text", content: " After" },
    ];
    const { container } = render(<InlineContentRenderer nodes={nodes} />);
    expect(container.textContent).toContain("Before");
    expect(container.textContent).toContain("After");
    expect(container.textContent).not.toContain("Nested");
    expect(container.querySelector("ul")).toBeNull();
  });
});
