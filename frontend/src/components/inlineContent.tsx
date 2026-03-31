import { useContext, useEffect, useRef, type ReactNode } from "react";
import katex from "katex";
import type { InlineContent } from "./structuredDocument";
import { FootnoteContext } from "./footnoteContext";
import { HoverCard, HoverCardTrigger, HoverCardContent } from "@/components/ui/hover-card";
import { useSettings } from "@/hooks/useSettings";

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

// Fixation length lookup table from the Bionic Reading algorithm.
// Each row is a boundary list for a given intensity (1=heavy, 5=light).
// Source: text-vide (MIT), reverse-engineered from the official API.
const FIXATION_BOUNDARIES = [
  [0, 4, 12, 17, 24, 29, 35, 42, 48],
  [1, 2, 7, 10, 13, 14, 19, 22, 25, 28, 31, 34, 37, 40, 43, 46, 49],
  [1, 2, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 47, 49],
];
const DEFAULT_FIXATION = FIXATION_BOUNDARIES[0];

function fixationLength(wordLength: number): number {
  const idx = DEFAULT_FIXATION.findIndex(b => wordLength <= b);
  if (idx === -1) return Math.max(wordLength - DEFAULT_FIXATION.length, 0);
  return Math.max(wordLength - idx, 0);
}

const PURE_NUMBER = /^[\d-]+$/;

function bionicWord(word: string, key: number): ReactNode {
  if (PURE_NUMBER.test(word)) return word;
  const n = fixationLength(word.length);
  if (n === 0) return word;
  return (
    <span key={key}>
      <b className="font-semibold">{word.slice(0, n)}</b>
      {word.slice(n) || null}
    </span>
  );
}

function bionicText(text: string): ReactNode[] {
  // Split on whitespace and hyphens (hyphens split words in bionic reading)
  return text.split(/(\s+|(?<=\w)-(?=\w))/).map((segment, i) => {
    if (!segment || /^\s+$/.test(segment)) return segment;
    if (segment === "-") return segment;
    return bionicWord(segment, i);
  });
}

function renderNode(node: InlineContent, key: number, bionic: boolean): React.ReactNode {
  switch (node.type) {
    case "text":
      if (bionic && node.content) return <span key={key}>{bionicText(node.content)}</span>;
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
    case "strikethrough":
      return (
        <s key={key}>
          <InlineContentRenderer nodes={node.content} />
        </s>
      );
    case "link": {
      const href = node.href;
      if (/^(javascript|vbscript|data):/i.test(href.trim())) {
        return <span key={key}><InlineContentRenderer nodes={node.content} /></span>;
      }
      if (/\.(mp4|webm|mov|ogg)$/i.test(href)) {
        return (
          <video key={key} src={href} controls preload="metadata"
            className="max-w-full max-h-96 rounded my-2" />
        );
      }
      return (
        <a key={key} href={href} title={node.title ?? undefined}
          rel="noopener noreferrer">
          <InlineContentRenderer nodes={node.content} />
        </a>
      );
    }
    case "inline_image":
      return <img key={key} src={node.src} alt={node.alt} referrerPolicy="no-referrer" />;
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
      return <FootnoteRef key={key} label={node.label} hasContent={node.has_content} />;
    case "list":
      // Rendered at block level (e.g. ListBlockView), not inside inline spans.
      // Rendering <ul>/<ol> inside <span> is invalid HTML and causes browser quirks.
      return null;
    default:
      return null;
  }
}

function FootnoteRef({ label, hasContent }: { label: string; hasContent: boolean }) {
  const footnotes = useContext(FootnoteContext);

  if (!hasContent) {
    return <sup>[^{label}]</sup>;
  }

  const anchor = (
    <sup id={`fnref-${label}`}>
      <a href={`#fn-${label}`}>[{label}]</a>
    </sup>
  );

  const paragraphs = footnotes.get(label);
  if (!paragraphs) return anchor;

  return (
    <HoverCard openDelay={300} closeDelay={150}>
      <HoverCardTrigger asChild>
        {anchor}
      </HoverCardTrigger>
      <HoverCardContent side="top" className="w-auto max-w-sm">
        <div className="space-y-1.5 text-sm max-h-48 overflow-y-auto">
          {paragraphs.map((ast, i) => (
            <p key={i}><InlineContentRenderer nodes={ast} /></p>
          ))}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

export function InlineContentRenderer({
  nodes,
}: {
  nodes: InlineContent[] | undefined | null;
}) {
  const { settings } = useSettings();
  if (!nodes || nodes.length === 0) return null;
  return <>{nodes.map((node, i) => renderNode(node, i, settings.bionicReading))}</>;
}
