import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import katex from "katex";
import { Copy, Download, Music, Check } from "lucide-react";
import { cn } from "@/lib/utils";

// === Slug generation for heading anchors ===

function generateSlug(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, "") // Remove special chars except spaces and hyphens
    .replace(/\s+/g, "-") // Replace spaces with hyphens
    .replace(/-+/g, "-") // Collapse multiple hyphens
    .replace(/^-|-$/g, ""); // Trim leading/trailing hyphens
}

function buildSlugMap(blocks: ContentBlock[]): Map<string, string> {
  const slugMap = new Map<string, string>();
  const slugCounts = new Map<string, number>();

  for (const block of blocks) {
    if (block.type === "heading") {
      const baseSlug = generateSlug(block.plain_text);
      if (!baseSlug) continue;

      const count = slugCounts.get(baseSlug) || 0;
      const slug = count === 0 ? baseSlug : `${baseSlug}-${count}`;
      slugCounts.set(baseSlug, count + 1);
      slugMap.set(block.id, slug);
    }
  }

  return slugMap;
}

// === TypeScript types matching backend Pydantic models ===

type InlineContent =
  | { type: "text"; content: string }
  | { type: "strong"; content: InlineContent[] }
  | { type: "emphasis"; content: InlineContent[] }
  | { type: "code"; content: string }
  | { type: "link"; href: string; title?: string; content: InlineContent[] }
  | { type: "image"; src: string; alt: string };

interface ListItem {
  html: string;
  ast: InlineContent[];
  plain_text: string;
}

interface HeadingBlock {
  type: "heading";
  id: string;
  level: 1 | 2 | 3 | 4 | 5 | 6;
  html: string;
  ast: InlineContent[];
  plain_text: string;
  audio_block_idx: number | null;
}

interface ParagraphBlock {
  type: "paragraph";
  id: string;
  html: string;
  ast: InlineContent[];
  plain_text: string;
  audio_block_idx: number | null;
  visual_group_id?: string;
}

interface ListBlock {
  type: "list";
  id: string;
  ordered: boolean;
  start?: number;
  items: ListItem[];
  plain_text: string;
  audio_block_idx: number | null;
}

interface BlockquoteBlock {
  type: "blockquote";
  id: string;
  blocks: ContentBlock[];
  plain_text: string;
  audio_block_idx: number | null;
}

interface CodeBlock {
  type: "code";
  id: string;
  language?: string;
  content: string;
  audio_block_idx: null;
}

interface MathBlock {
  type: "math";
  id: string;
  content: string;
  display_mode: boolean;
  audio_block_idx: null;
}

interface TableBlock {
  type: "table";
  id: string;
  headers: string[];
  rows: string[][];
  audio_block_idx: null;
}

interface ImageBlock {
  type: "image";
  id: string;
  src: string;
  alt: string;
  title?: string;
  audio_block_idx: null;
}

interface ThematicBreak {
  type: "hr";
  id: string;
  audio_block_idx: null;
}

type ContentBlock =
  | HeadingBlock
  | ParagraphBlock
  | ListBlock
  | BlockquoteBlock
  | CodeBlock
  | MathBlock
  | TableBlock
  | ImageBlock
  | ThematicBreak;

interface StructuredDocument {
  version: string;
  blocks: ContentBlock[];
}

// === Block renderers ===

interface BlockProps {
  block: ContentBlock;
  onClick?: () => void;
}

// Always have border-l-4 to prevent layout shift when active state changes
// Active state is managed via DOM manipulation in PlaybackPage, not React props (avoids re-renders)
const blockBaseClass = "border-l-4 border-l-transparent -ml-1 transition-colors duration-150";
const clickableClass = "cursor-pointer hover:bg-muted/50 rounded";

function HeadingBlockView({ block, onClick, slugId }: BlockProps & { block: HeadingBlock; slugId?: string }) {
  const sizeClasses: Record<number, string> = {
    1: "text-3xl font-bold mt-8 mb-4",
    2: "text-2xl font-semibold mt-6 mb-3",
    3: "text-xl font-semibold mt-5 mb-2",
    4: "text-lg font-medium mt-4 mb-2",
    5: "text-base font-medium mt-3 mb-1",
    6: "text-sm font-medium mt-2 mb-1",
  };

  const className = cn(
    sizeClasses[block.level],
    "py-1",
    blockBaseClass,
    onClick && clickableClass
  );

  const props = {
    id: slugId,
    className,
    onClick,
    dangerouslySetInnerHTML: { __html: block.html },
  };

  switch (block.level) {
    case 1: return <h1 {...props} />;
    case 2: return <h2 {...props} />;
    case 3: return <h3 {...props} />;
    case 4: return <h4 {...props} />;
    case 5: return <h5 {...props} />;
    case 6: return <h6 {...props} />;
  }
}

function ParagraphBlockView({ block, onClick }: BlockProps & { block: ParagraphBlock }) {
  return (
    <p
      className={cn(
        "my-3 py-1 leading-relaxed",
        blockBaseClass,
        onClick && clickableClass
      )}
      onClick={onClick}
      dangerouslySetInnerHTML={{ __html: block.html }}
    />
  );
}

function ListBlockView({ block, onClick }: BlockProps & { block: ListBlock }) {
  const ListTag = block.ordered ? "ol" : "ul";
  const listClass = block.ordered ? "list-decimal" : "list-disc";

  return (
    <ListTag
      className={cn(
        "my-3 ml-6 py-1 transition-colors duration-150 rounded",
        listClass,
        onClick && clickableClass
      )}
      onClick={onClick}
      start={block.ordered ? block.start : undefined}
    >
      {block.items.map((item, idx) => (
        <li
          key={idx}
          className="my-1"
          dangerouslySetInnerHTML={{ __html: item.html }}
        />
      ))}
    </ListTag>
  );
}

function BlockquoteBlockView({ block, onBlockClick }: {
  block: BlockquoteBlock;
  onBlockClick?: (audioIdx: number) => void;
}) {
  // Group nested blocks by visual_group_id (same as top-level)
  const groupedBlocks = groupBlocks(block.blocks);

  // Blockquote is a visual container - nested blocks have their own audio indices
  return (
    <blockquote className="my-4 border-l-4 border-muted-foreground/30 pl-4 italic text-muted-foreground py-1">
      {groupedBlocks.map((grouped) => {
        if (grouped.kind === "paragraph-group") {
          return (
            <ParagraphGroupView
              key={grouped.blocks[0].id}
              blocks={grouped.blocks}
              onBlockClick={onBlockClick}
            />
          );
        } else {
          const b = grouped.block;
          return (
            <div key={b.id} data-audio-block-idx={b.audio_block_idx ?? undefined}>
              <BlockView
                block={b}
                onBlockClick={onBlockClick}
              />
            </div>
          );
        }
      })}
    </blockquote>
  );
}

function CodeBlockView({ block }: BlockProps & { block: CodeBlock }) {
  return (
    <div className="my-4">
      {block.language && (
        <div className="text-xs text-muted-foreground bg-muted px-3 py-1 rounded-t border border-b-0 border-border">
          {block.language}
        </div>
      )}
      <pre
        className={cn(
          "bg-muted p-4 overflow-x-auto text-sm font-mono",
          block.language ? "rounded-b border border-t-0 border-border" : "rounded border border-border"
        )}
      >
        <code>{block.content}</code>
      </pre>
    </div>
  );
}

function MathBlockView({ block }: BlockProps & { block: MathBlock }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      try {
        katex.render(block.content, containerRef.current, {
          displayMode: true,
          throwOnError: false,
        });
      } catch (e) {
        console.warn("KaTeX render error:", e);
        containerRef.current.textContent = block.content;
      }
    }
  }, [block.content]);

  return (
    <div
      ref={containerRef}
      className="my-4 p-4 bg-muted/50 rounded border border-border text-center overflow-x-auto"
    />
  );
}

function TableBlockView({ block }: BlockProps & { block: TableBlock }) {
  return (
    <div className="my-4 overflow-x-auto">
      <table className="w-full border-collapse border border-border text-sm">
        <thead>
          <tr className="bg-muted">
            {block.headers.map((header, idx) => (
              <th
                key={idx}
                className="border border-border px-3 py-2 text-left font-medium"
                dangerouslySetInnerHTML={{ __html: header }}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIdx) => (
            <tr key={rowIdx} className="hover:bg-muted/30">
              {row.map((cell, cellIdx) => (
                <td
                  key={cellIdx}
                  className="border border-border px-3 py-2"
                  dangerouslySetInnerHTML={{ __html: cell }}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImageBlockView({ block }: BlockProps & { block: ImageBlock }) {
  return (
    <figure className="my-4">
      <img
        src={block.src}
        alt={block.alt}
        title={block.title}
        className="max-w-full h-auto rounded"
      />
      {block.alt && (
        <figcaption className="text-sm text-muted-foreground mt-2 text-center">
          {block.alt}
        </figcaption>
      )}
    </figure>
  );
}

function ThematicBreakView() {
  return <hr className="my-6 border-t border-border" />;
}

// === Block grouping for visual continuity ===

type GroupedBlock =
  | { kind: "single"; block: ContentBlock }
  | { kind: "paragraph-group"; blocks: ParagraphBlock[] };

function groupBlocks(blocks: ContentBlock[]): GroupedBlock[] {
  const result: GroupedBlock[] = [];
  let currentGroup: ParagraphBlock[] = [];
  let currentGroupId: string | null = null;

  const flushGroup = () => {
    if (currentGroup.length > 1) {
      result.push({ kind: "paragraph-group", blocks: currentGroup });
    } else if (currentGroup.length === 1) {
      result.push({ kind: "single", block: currentGroup[0] });
    }
    currentGroup = [];
    currentGroupId = null;
  };

  for (const block of blocks) {
    const groupId = block.type === "paragraph" ? block.visual_group_id : null;

    if (groupId && groupId === currentGroupId) {
      currentGroup.push(block as ParagraphBlock);
    } else {
      flushGroup();
      if (groupId) {
        currentGroup = [block as ParagraphBlock];
        currentGroupId = groupId;
      } else {
        result.push({ kind: "single", block });
      }
    }
  }

  flushGroup();
  return result;
}

// Renders multiple paragraph blocks as spans within a single <p>
interface ParagraphGroupViewProps {
  blocks: ParagraphBlock[];
  onBlockClick?: (audioIdx: number) => void;
}

function ParagraphGroupView({ blocks, onBlockClick }: ParagraphGroupViewProps) {
  return (
    <p className="my-3 py-1 leading-relaxed">
      {blocks.map((block, idx) => {
        const handleClick = block.audio_block_idx !== null && onBlockClick
          ? () => onBlockClick(block.audio_block_idx as number)
          : undefined;

        return (
          <span
            key={block.id}
            data-audio-block-idx={block.audio_block_idx ?? undefined}
            className={cn(
              "transition-colors duration-150 rounded",
              handleClick && "cursor-pointer hover:bg-muted/50"
            )}
            onClick={handleClick}
          >
            {/* Add space between consecutive spans (lost during sentence splitting) */}
            {idx > 0 && " "}
            <span dangerouslySetInnerHTML={{ __html: block.html }} />
          </span>
        );
      })}
    </p>
  );
}

// === Main block renderer ===

interface BlockViewProps {
  block: ContentBlock;
  onBlockClick?: (audioIdx: number) => void;
  slugMap?: Map<string, string>;
}

function BlockView({ block, onBlockClick, slugMap }: BlockViewProps) {
  const handleClick = block.audio_block_idx !== null && onBlockClick
    ? () => onBlockClick(block.audio_block_idx as number)
    : undefined;

  const baseProps = { block, onClick: handleClick };

  switch (block.type) {
    case "heading":
      return <HeadingBlockView {...baseProps} block={block} slugId={slugMap?.get(block.id)} />;
    case "paragraph":
      return <ParagraphBlockView {...baseProps} block={block} />;
    case "list":
      return <ListBlockView {...baseProps} block={block} />;
    case "blockquote":
      return (
        <BlockquoteBlockView
          block={block}
          onBlockClick={onBlockClick}
        />
      );
    case "code":
      return <CodeBlockView {...baseProps} block={block} />;
    case "math":
      return <MathBlockView {...baseProps} block={block} />;
    case "table":
      return <TableBlockView {...baseProps} block={block} />;
    case "image":
      return <ImageBlockView {...baseProps} block={block} />;
    case "hr":
      return <ThematicBreakView />;
    default:
      return null;
  }
}

// === Main component ===

interface StructuredDocumentViewProps {
  structuredContent: string | null;
  title?: string;
  sourceUrl?: string | null;
  markdownContent?: string | null;
  onBlockClick?: (audioIdx: number) => void;
  fallbackContent?: string;
}

// Memoized to prevent re-renders from parent's audioProgress updates
export const StructuredDocumentView = memo(function StructuredDocumentView({
  structuredContent,
  title,
  sourceUrl,
  markdownContent,
  onBlockClick,
  fallbackContent,
}: StructuredDocumentViewProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  // Copy markdown to clipboard
  const handleCopyMarkdown = useCallback(async () => {
    if (!markdownContent) return;
    try {
      await navigator.clipboard.writeText(markdownContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  }, [markdownContent]);

  // Download markdown file
  const handleDownloadMarkdown = useCallback(() => {
    if (!markdownContent) return;
    const filename = (title || "document").replace(/[^a-z0-9]/gi, "_").toLowerCase() + ".md";
    const blob = new Blob([markdownContent], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [markdownContent, title]);

  // Open source URL in new tab
  const handleTitleClick = useCallback(() => {
    if (sourceUrl) {
      window.open(sourceUrl, "_blank", "noopener,noreferrer");
    }
  }, [sourceUrl]);

  // Parse structured content
  const doc = useMemo(() => {
    if (!structuredContent) return null;
    try {
      return JSON.parse(structuredContent) as StructuredDocument;
    } catch (e) {
      console.warn("Failed to parse structured content:", e);
      return null;
    }
  }, [structuredContent]);

  // Build slug map for heading anchors
  const slugMap = useMemo(() => {
    if (!doc?.blocks) return new Map<string, string>();
    return buildSlugMap(doc.blocks);
  }, [doc]);

  // Render inline math after content updates
  useEffect(() => {
    if (!contentRef.current) return;
    const mathSpans = contentRef.current.querySelectorAll(".math-inline");
    mathSpans.forEach((span) => {
      const latex = span.textContent || "";
      if (latex && !span.classList.contains("katex-rendered")) {
        try {
          katex.render(latex, span as HTMLElement, {
            displayMode: false,
            throwOnError: false,
          });
          span.classList.add("katex-rendered");
        } catch (e) {
          console.warn("KaTeX inline render error:", e);
        }
      }
    });
  }, [structuredContent]);

  // Mark dead anchor links (no matching heading)
  useEffect(() => {
    if (!contentRef.current) return;

    // Small delay to ensure heading IDs are in the DOM
    const timeoutId = setTimeout(() => {
      if (!contentRef.current) return;
      const anchorLinks = contentRef.current.querySelectorAll('a[href^="#"]');
      anchorLinks.forEach((link) => {
        const fragment = link.getAttribute("href")?.slice(1);
        if (!fragment) return;
        const targetExists = document.getElementById(fragment);
        if (targetExists) {
          link.classList.remove("dead-link");
        } else {
          link.classList.add("dead-link");
        }
      });
    }, 0);

    return () => clearTimeout(timeoutId);
  });

  // Handle clicks on links within document content
  const handleContentClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    const anchor = target.closest("a") as HTMLAnchorElement | null;
    if (!anchor) return;

    const href = anchor.getAttribute("href");
    if (!href) return;

    // Anchor links (#fragment) - scroll to heading if exists, otherwise no-op
    if (href.startsWith("#")) {
      e.preventDefault();
      const fragment = href.slice(1);
      const targetElement = document.getElementById(fragment);
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      return;
    }

    // Relative links (/path) - no-op, these are from original site and don't work here
    if (href.startsWith("/")) {
      e.preventDefault();
      return;
    }

    // External links (http://, https://) - open in new tab
    if (href.startsWith("http://") || href.startsWith("https://")) {
      e.preventDefault();
      window.open(href, "_blank", "noopener,noreferrer");
    }
  }, []);

  // Fallback to plain text rendering
  if (!doc || !doc.blocks || doc.blocks.length === 0) {
    return (
      <div className="flex flex-col overflow-y-auto m-[10%] mt-[4%]">
        {title && (
          <div className="flex items-center justify-between mb-[4%] border-b border-b-border pb-2">
            <p
              className={cn(
                "text-4xl font-bold",
                sourceUrl && "cursor-pointer hover:opacity-80"
              )}
              onClick={sourceUrl ? handleTitleClick : undefined}
            >
              {title}
            </p>
            <div className="flex items-center gap-1 ml-4">
              <button
                onClick={handleCopyMarkdown}
                disabled={!markdownContent}
                className="p-2 rounded hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title={copied ? "Copied!" : "Copy markdown"}
              >
                {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4 text-muted-foreground" />}
              </button>
              <button
                onClick={handleDownloadMarkdown}
                disabled={!markdownContent}
                className="p-2 rounded hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="Download markdown"
              >
                <Download className="h-4 w-4 text-muted-foreground" />
              </button>
              <button
                disabled
                className="p-2 rounded opacity-40 cursor-not-allowed"
                title="Export as audio (coming soon)"
              >
                <Music className="h-4 w-4 text-muted-foreground" />
              </button>
            </div>
          </div>
        )}
        <pre className="whitespace-pre-wrap break-words w-full">
          {fallbackContent || "No content available"}
        </pre>
      </div>
    );
  }

  // Group consecutive paragraphs with same visual_group_id
  const groupedBlocks = groupBlocks(doc.blocks);

  return (
    <article className="flex flex-col overflow-y-auto m-[10%] mt-[4%] prose-container">
      {title && (
        <div className="flex items-center justify-between mb-6 border-b border-b-border pb-2">
          <h1
            className={cn(
              "text-4xl font-bold",
              sourceUrl && "cursor-pointer hover:opacity-80"
            )}
            onClick={sourceUrl ? handleTitleClick : undefined}
          >
            {title}
          </h1>
          <div className="flex items-center gap-1 ml-4">
            <button
              onClick={handleCopyMarkdown}
              disabled={!markdownContent}
              className="p-2 rounded hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title={copied ? "Copied!" : "Copy markdown"}
            >
              {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4 text-muted-foreground" />}
            </button>
            <button
              onClick={handleDownloadMarkdown}
              disabled={!markdownContent}
              className="p-2 rounded hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="Download markdown"
            >
              <Download className="h-4 w-4 text-muted-foreground" />
            </button>
            <button
              disabled
              className="p-2 rounded opacity-40 cursor-not-allowed"
              title="Export as audio (coming soon)"
            >
              <Music className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
        </div>
      )}
      <div ref={contentRef} className="structured-content" onClick={handleContentClick}>
        {groupedBlocks.map((grouped) => {
          if (grouped.kind === "paragraph-group") {
            return (
              <ParagraphGroupView
                key={grouped.blocks[0].id}
                blocks={grouped.blocks}
                onBlockClick={onBlockClick}
              />
            );
          } else {
            const block = grouped.block;
            const handleWrapperClick = block.audio_block_idx !== null && onBlockClick
              ? () => onBlockClick(block.audio_block_idx as number)
              : undefined;
            return (
              <div
                key={block.id}
                data-audio-block-idx={block.audio_block_idx ?? undefined}
                onClick={handleWrapperClick}
              >
                <BlockView
                  block={block}
                  onBlockClick={onBlockClick}
                  slugMap={slugMap}
                />
              </div>
            );
          }
        })}
      </div>

      {/* Inline styles for HTML content */}
      <style>{`
        /* Base link style */
        .structured-content a {
          color: var(--primary);
          text-decoration: none;
        }
        .structured-content a:hover {
          opacity: 0.8;
        }

        /* Internal anchor links - dotted underline */
        .structured-content a[href^="#"]:not(.dead-link) {
          text-decoration: underline;
          text-decoration-style: dotted;
          text-underline-offset: 2px;
        }

        /* External links - solid underline + icon */
        .structured-content a[href^="http"] {
          text-decoration: underline;
          text-underline-offset: 2px;
        }
        .structured-content a[href^="http"]::after {
          content: " ↗";
          font-size: 0.7em;
          text-decoration: none;
          display: inline;
        }

        /* Dead links - slightly muted, no underline */
        .structured-content a[href^="/"],
        .structured-content a[href^="#"].dead-link {
          color: var(--primary);
          opacity: 0.7;
          text-decoration: none;
          cursor: default;
        }
        .structured-content a[href^="/"]::after,
        .structured-content a.dead-link::after {
          content: none;
        }

        .structured-content strong {
          font-weight: 600;
        }
        .structured-content em {
          font-style: italic;
        }
        .structured-content code:not(pre code) {
          background: hsl(var(--muted));
          padding: 0.125rem 0.375rem;
          border-radius: 0.25rem;
          font-size: 0.875em;
          font-family: ui-monospace, monospace;
        }

        /* Nested lists (rendered via dangerouslySetInnerHTML) */
        .structured-content li ul,
        .structured-content li ol {
          margin-left: 1.5rem;
          margin-top: 0.25rem;
          margin-bottom: 0.25rem;
        }
        .structured-content li ul {
          list-style-type: disc;
        }
        .structured-content li ol {
          list-style-type: decimal;
        }

        /* Active audio block highlighting (applied via DOM manipulation) */
        /* Block-level elements get left border + background */
        .structured-content .audio-block-active {
          background: oklch(0.55 0.1 133.7 / 0.15);
          border-left-color: oklch(0.55 0.1 133.7);
        }
        /* Inline spans (paragraph groups) get background only */
        .structured-content span.audio-block-active {
          background: oklch(0.55 0.1 133.7 / 0.15);
        }
      `}</style>
    </article>
  );
});

// Export types for use elsewhere
export type { StructuredDocument, ContentBlock, InlineContent };
