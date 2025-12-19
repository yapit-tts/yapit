import { memo, useCallback, useEffect, useMemo, useRef } from "react";
import katex from "katex";
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
  isActive: boolean;
  onClick?: () => void;
}

const activeBlockClass = "bg-primary/10 border-l-4 border-l-primary -ml-4 pl-3";
const clickableClass = "cursor-pointer hover:bg-muted/50 transition-colors rounded";

function HeadingBlockView({ block, isActive, onClick, slugId }: BlockProps & { block: HeadingBlock; slugId?: string }) {
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
    onClick && clickableClass,
    isActive && activeBlockClass
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

function ParagraphBlockView({ block, isActive, onClick }: BlockProps & { block: ParagraphBlock }) {
  return (
    <p
      className={cn(
        "my-3 py-1 leading-relaxed",
        onClick && clickableClass,
        isActive && activeBlockClass
      )}
      onClick={onClick}
      dangerouslySetInnerHTML={{ __html: block.html }}
    />
  );
}

function ListBlockView({ block, isActive, onClick }: BlockProps & { block: ListBlock }) {
  const ListTag = block.ordered ? "ol" : "ul";
  const listClass = block.ordered ? "list-decimal" : "list-disc";

  return (
    <ListTag
      className={cn(
        "my-3 ml-6 py-1",
        listClass,
        onClick && clickableClass,
        isActive && activeBlockClass
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

function BlockquoteBlockView({ block, currentAudioBlockIdx, onBlockClick }: {
  block: BlockquoteBlock;
  currentAudioBlockIdx: number;
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
              currentAudioBlockIdx={currentAudioBlockIdx}
              onBlockClick={onBlockClick}
            />
          );
        } else {
          const b = grouped.block;
          return (
            <div key={b.id} data-audio-block-idx={b.audio_block_idx ?? undefined}>
              <BlockView
                block={b}
                currentAudioBlockIdx={currentAudioBlockIdx}
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
  currentAudioBlockIdx: number;
  onBlockClick?: (audioIdx: number) => void;
}

function ParagraphGroupView({ blocks, currentAudioBlockIdx, onBlockClick }: ParagraphGroupViewProps) {
  return (
    <p className="my-3 py-1 leading-relaxed">
      {blocks.map((block) => {
        const isActive = block.audio_block_idx === currentAudioBlockIdx && currentAudioBlockIdx >= 0;
        const handleClick = block.audio_block_idx !== null && onBlockClick
          ? () => onBlockClick(block.audio_block_idx as number)
          : undefined;

        return (
          <span
            key={block.id}
            data-audio-block-idx={block.audio_block_idx ?? undefined}
            className={cn(
              handleClick && "cursor-pointer hover:bg-muted/50 transition-colors",
              isActive && "bg-primary/10 rounded"
            )}
            onClick={handleClick}
            dangerouslySetInnerHTML={{ __html: block.html }}
          />
        );
      })}
    </p>
  );
}

// === Main block renderer ===

interface BlockViewProps {
  block: ContentBlock;
  currentAudioBlockIdx: number;
  onBlockClick?: (audioIdx: number) => void;
  slugMap?: Map<string, string>;
}

function BlockView({ block, currentAudioBlockIdx, onBlockClick, slugMap }: BlockViewProps) {
  const isActive = block.audio_block_idx === currentAudioBlockIdx && currentAudioBlockIdx >= 0;
  const handleClick = block.audio_block_idx !== null && onBlockClick
    ? () => onBlockClick(block.audio_block_idx as number)
    : undefined;

  const baseProps = { block, isActive, onClick: handleClick };

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
          currentAudioBlockIdx={currentAudioBlockIdx}
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
  currentAudioBlockIdx: number;
  onBlockClick?: (audioIdx: number) => void;
  fallbackContent?: string;
}

// Memoized to prevent re-renders from parent's audioProgress updates
export const StructuredDocumentView = memo(function StructuredDocumentView({
  structuredContent,
  title,
  currentAudioBlockIdx,
  onBlockClick,
  fallbackContent,
}: StructuredDocumentViewProps) {
  const contentRef = useRef<HTMLDivElement>(null);

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
  }, [structuredContent, currentAudioBlockIdx]);

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
          <p className="mb-[4%] text-4xl font-bold border-b border-b-border pb-2">
            {title}
          </p>
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
        <h1 className="mb-6 text-4xl font-bold border-b border-b-border pb-2">
          {title}
        </h1>
      )}
      <div ref={contentRef} className="structured-content" onClick={handleContentClick}>
        {groupedBlocks.map((grouped) => {
          if (grouped.kind === "paragraph-group") {
            return (
              <ParagraphGroupView
                key={grouped.blocks[0].id}
                blocks={grouped.blocks}
                currentAudioBlockIdx={currentAudioBlockIdx}
                onBlockClick={onBlockClick}
              />
            );
          } else {
            const block = grouped.block;
            return (
              <div
                key={block.id}
                data-audio-block-idx={block.audio_block_idx ?? undefined}
              >
                <BlockView
                  block={block}
                  currentAudioBlockIdx={currentAudioBlockIdx}
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
      `}</style>
    </article>
  );
});

// Export types for use elsewhere
export type { StructuredDocument, ContentBlock, InlineContent };
