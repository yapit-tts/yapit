import { useEffect, useRef } from "react";
import katex from "katex";
import type { InlineContent } from "./structuredDocument";

function InlineMath({ content }: { content: string }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!ref.current || !content) return;
    try {
      katex.render(content, ref.current, {
        displayMode: false,
        throwOnError: false,
      });
    } catch {
      if (ref.current) ref.current.textContent = content;
    }
  }, [content]);

  return <span ref={ref} className="math-inline" />;
}

function renderNode(node: InlineContent, key: number): React.ReactNode {
  switch (node.type) {
    case "text":
      return node.content || null;
    case "code_span":
      return <code key={key}>{node.content}</code>;
    case "strong":
      return (
        <strong key={key}>
          <InlineContentRenderer nodes={node.content} />
        </strong>
      );
    case "emphasis":
      return (
        <em key={key}>
          <InlineContentRenderer nodes={node.content} />
        </em>
      );
    case "link": {
      if (/\.(mp4|webm|mov|ogg)$/i.test(node.href)) {
        return (
          <video key={key} src={node.href} controls preload="metadata"
            className="max-w-full max-h-96 rounded my-2" />
        );
      }
      return (
        <a key={key} href={node.href} title={node.title ?? undefined}>
          <InlineContentRenderer nodes={node.content} />
        </a>
      );
    }
    case "inline_image":
      return <img key={key} src={node.src} alt={node.alt} />;
    case "math_inline":
      return <InlineMath key={key} content={node.content} />;
    case "hardbreak":
      return <br key={key} />;
    case "speak":
      // TTS-only, not rendered
      return null;
    case "show":
      return (
        <span key={key}>
          <InlineContentRenderer nodes={node.content} />
        </span>
      );
    case "footnote_ref":
      return (
        <sup key={key} id={`fnref-${node.label}`}>
          {node.has_content ? (
            <a href={`#fn-${node.label}`}>[{node.label}]</a>
          ) : (
            `[^${node.label}]`
          )}
        </sup>
      );
    case "list":
      // Rendered at block level (e.g. ListBlockView), not inside inline spans.
      // Rendering <ul>/<ol> inside <span> is invalid HTML and causes browser quirks.
      return null;
    default:
      return null;
  }
}

export function InlineContentRenderer({
  nodes,
}: {
  nodes: InlineContent[] | undefined | null;
}) {
  if (!nodes || nodes.length === 0) return null;
  return <>{nodes.map((node, i) => renderNode(node, i))}</>;
}
