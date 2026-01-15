import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import katex from "katex";
import { Copy, Download, Music, Check } from "lucide-react";
import { cn } from "@/lib/utils";

// Sanitize HTML to prevent XSS attacks
const sanitize = (html: string): string => DOMPurify.sanitize(html);

// === Slug generation for heading anchors ===

function generateSlug(text: string): string {
  return text
    .normalize("NFD") // Decompose accented chars (é → e + combining accent)
    .replace(/[\u0300-\u036f]/g, "") // Remove combining diacritical marks
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
  width_pct?: number;  // Figure width as % of page (from YOLO detection)
  row_group?: string;  // "row0", "row1", etc. - figures in same row are side-by-side
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
const clickableClass = "cursor-pointer clickable-block";

function HeadingBlockView({ block, slugId }: { block: HeadingBlock; slugId?: string }) {
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
    "py-1"
  );

  const props = {
    id: slugId,
    className,
    dangerouslySetInnerHTML: { __html: sanitize(block.html) },
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

function ParagraphBlockView({ block }: { block: ParagraphBlock }) {
  return (
    <p
      className="my-3 py-1 leading-relaxed"
      dangerouslySetInnerHTML={{ __html: sanitize(block.html) }}
    />
  );
}

function ListBlockView({ block }: { block: ListBlock }) {
  const ListTag = block.ordered ? "ol" : "ul";
  const listClass = block.ordered ? "list-decimal" : "list-disc";

  return (
    <ListTag
      className={cn("my-3 ml-6 py-1", listClass)}
      start={block.ordered ? block.start : undefined}
    >
      {block.items.map((item, idx) => (
        <li
          key={idx}
          className="my-1"
          dangerouslySetInnerHTML={{ __html: sanitize(item.html) }}
        />
      ))}
    </ListTag>
  );
}

function BlockquoteBlockView({ block, onBlockClick }: {
  block: BlockquoteBlock;
  onBlockClick?: (audioIdx: number) => void;
}) {
  // Group nested blocks by visual_group_id and row_group (same as top-level)
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
        } else if (grouped.kind === "image-row") {
          return (
            <ImageRowView
              key={grouped.blocks[0].id}
              blocks={grouped.blocks}
            />
          );
        } else {
          const b = grouped.block;
          return (
            <div
              key={b.id}
              data-audio-block-idx={b.audio_block_idx ?? undefined}
              className={cn(blockBaseClass, b.audio_block_idx !== null && onBlockClick && clickableClass)}
              onClick={b.audio_block_idx !== null && onBlockClick ? () => onBlockClick(b.audio_block_idx as number) : undefined}
            >
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
        <div className="text-xs text-muted-foreground bg-muted-brown px-3 py-1 rounded-t border border-b-0 border-border">
          {block.language}
        </div>
      )}
      <pre
        className={cn(
          "bg-muted-brown p-4 overflow-x-auto text-sm font-mono",
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
      className="my-4 p-4 bg-muted-brown rounded border border-border text-center overflow-x-auto"
    />
  );
}

function TableBlockView({ block }: BlockProps & { block: TableBlock }) {
  return (
    <div className="my-4 overflow-x-auto">
      <table className="w-full border-collapse border border-border text-sm">
        <thead>
          <tr className="bg-muted-brown">
            {block.headers.map((header, idx) => (
              <th
                key={idx}
                className="border border-border px-3 py-2 text-left font-medium"
                dangerouslySetInnerHTML={{ __html: sanitize(header) }}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIdx) => (
            <tr key={rowIdx} className="hover:bg-muted-brown/30">
              {row.map((cell, cellIdx) => (
                <td
                  key={cellIdx}
                  className="border border-border px-3 py-2"
                  dangerouslySetInnerHTML={{ __html: sanitize(cell) }}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImageBlockView({ block, inRow }: BlockProps & { block: ImageBlock; inRow?: boolean }) {
  // Apply width styling if width_pct is provided (from YOLO detection)
  const style = block.width_pct
    ? { width: `${Math.min(block.width_pct, 100)}%`, maxWidth: "100%" }
    : {};

  return (
    <figure className={cn("flex flex-col items-center", !inRow && "my-4")}>
      <img
        src={block.src}
        alt={block.alt}
        title={block.title}
        style={style}
        className="max-w-full max-h-96 h-auto object-contain rounded"
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
  | { kind: "paragraph-group"; blocks: ParagraphBlock[] }
  | { kind: "image-row"; blocks: ImageBlock[] };

function groupBlocks(blocks: ContentBlock[]): GroupedBlock[] {
  const result: GroupedBlock[] = [];
  let currentParagraphGroup: ParagraphBlock[] = [];
  let currentParagraphGroupId: string | null = null;
  let currentImageRow: ImageBlock[] = [];
  let currentImageRowGroup: string | null = null;

  const flushParagraphGroup = () => {
    if (currentParagraphGroup.length > 1) {
      result.push({ kind: "paragraph-group", blocks: currentParagraphGroup });
    } else if (currentParagraphGroup.length === 1) {
      result.push({ kind: "single", block: currentParagraphGroup[0] });
    }
    currentParagraphGroup = [];
    currentParagraphGroupId = null;
  };

  const flushImageRow = () => {
    if (currentImageRow.length > 1) {
      result.push({ kind: "image-row", blocks: currentImageRow });
    } else if (currentImageRow.length === 1) {
      result.push({ kind: "single", block: currentImageRow[0] });
    }
    currentImageRow = [];
    currentImageRowGroup = null;
  };

  for (const block of blocks) {
    // Handle paragraph visual groups
    if (block.type === "paragraph" && block.visual_group_id) {
      flushImageRow(); // Flush any pending image row
      if (block.visual_group_id === currentParagraphGroupId) {
        currentParagraphGroup.push(block);
      } else {
        flushParagraphGroup();
        currentParagraphGroup = [block];
        currentParagraphGroupId = block.visual_group_id;
      }
      continue;
    }

    // Handle image row groups
    if (block.type === "image" && block.row_group) {
      flushParagraphGroup(); // Flush any pending paragraph group
      if (block.row_group === currentImageRowGroup) {
        currentImageRow.push(block);
      } else {
        flushImageRow();
        currentImageRow = [block];
        currentImageRowGroup = block.row_group;
      }
      continue;
    }

    // Single block - flush any pending groups first
    flushParagraphGroup();
    flushImageRow();
    result.push({ kind: "single", block });
  }

  flushParagraphGroup();
  flushImageRow();
  return result;
}

// Renders multiple image blocks in a flex row (side-by-side figures)
function ImageRowView({ blocks }: { blocks: ImageBlock[] }) {
  return (
    <div className="my-4 flex gap-4 justify-center items-start flex-wrap">
      {blocks.map((block) => (
        <ImageBlockView key={block.id} block={block} inRow />
      ))}
    </div>
  );
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
              "transition-colors duration-150",
              handleClick && "cursor-pointer clickable-span"
            )}
            onClick={handleClick}
          >
            {/* Add space between consecutive spans (lost during sentence splitting) */}
            {idx > 0 && " "}
            <span dangerouslySetInnerHTML={{ __html: sanitize(block.html) }} />
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
  switch (block.type) {
    case "heading":
      return <HeadingBlockView block={block} slugId={slugMap?.get(block.id)} />;
    case "paragraph":
      return <ParagraphBlockView block={block} />;
    case "list":
      return <ListBlockView block={block} />;
    case "blockquote":
      return (
        <BlockquoteBlockView
          block={block}
          onBlockClick={onBlockClick}
        />
      );
    case "code":
      return <CodeBlockView block={block} />;
    case "math":
      return <MathBlockView block={block} />;
    case "table":
      return <TableBlockView block={block} />;
    case "image":
      return <ImageBlockView block={block} />;
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
  onTitleChange?: (newTitle: string) => void;
}

// Memoized to prevent re-renders from parent's audioProgress updates
export const StructuredDocumentView = memo(function StructuredDocumentView({
  structuredContent,
  title,
  sourceUrl,
  markdownContent,
  onBlockClick,
  fallbackContent,
  onTitleChange,
}: StructuredDocumentViewProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editedTitle, setEditedTitle] = useState("");

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

  // Inline title editing (for no-title documents)
  const startEditingTitle = useCallback(() => {
    if (!title && onTitleChange) {
      setEditedTitle("");
      setIsEditingTitle(true);
    }
  }, [title, onTitleChange]);

  const saveTitle = useCallback(() => {
    if (editedTitle.trim() && onTitleChange) {
      onTitleChange(editedTitle.trim());
    }
    setIsEditingTitle(false);
    setEditedTitle("");
  }, [editedTitle, onTitleChange]);

  const cancelEditingTitle = useCallback(() => {
    setIsEditingTitle(false);
    setEditedTitle("");
  }, []);

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
  }, [doc]);

  // Replace video links with embedded video players
  useEffect(() => {
    if (!contentRef.current) return;

    // Defer to next tick to ensure DOM is painted (Firefox timing differs from Chromium)
    const timeoutId = setTimeout(() => {
      if (!contentRef.current) return;
      const videoExtensions = /\.(mp4|webm|mov|ogg)$/i;
      const videoLinks = contentRef.current.querySelectorAll('a[href]');

      videoLinks.forEach((link) => {
        const href = link.getAttribute("href");
        if (!href || !videoExtensions.test(href)) return;

        const video = document.createElement("video");
        video.src = href;
        video.controls = true;
        video.className = "max-w-full max-h-96 rounded my-2";
        video.preload = "metadata";

        link.replaceWith(video);
      });
    }, 0);

    return () => clearTimeout(timeoutId);
  }, [structuredContent]);

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

  // Action buttons toolbar - always rendered
  const ActionButtons = () => (
    <div className="flex items-center gap-1 shrink-0">
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
  );

  // Responsive margins: larger on desktop, smaller on mobile
  // pb-52 (208px) provides clearance above the fixed SoundControl bar (~177px)
  const containerClass = "w-full flex flex-col overflow-y-auto px-4 sm:px-[8%] md:px-[10%] pt-4 sm:pt-[4%] pb-52";

  // Fallback to plain text rendering
  if (!doc || !doc.blocks || doc.blocks.length === 0) {
    return (
      <div className={containerClass}>
        {title ? (
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 pb-2 border-b border-b-border">
            <p
              className={cn(
                "text-4xl font-bold sm:mr-4",
                sourceUrl && "cursor-pointer hover:opacity-80"
              )}
              onClick={sourceUrl ? handleTitleClick : undefined}
            >
              {title}
            </p>
            <div className="flex justify-end mt-2 sm:mt-0">
              <ActionButtons />
            </div>
          </div>
        ) : (
          <div className="-mx-4 px-4 sm:-mx-[8%] sm:px-[8%] md:-mx-[10%] md:px-[10%] mb-4 pb-2 border-b border-b-border">
            <div className="w-full flex justify-end">
              <ActionButtons />
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
    <article className={cn(containerClass, "prose-container")}>
      {title && !isEditingTitle ? (
        <div
          className={cn(
            "flex flex-col sm:flex-row sm:items-center sm:justify-between mb-6 pb-2 border-b border-b-border overflow-hidden",
            onTitleChange && "cursor-text"
          )}
          onClick={onTitleChange ? () => { setEditedTitle(title); setIsEditingTitle(true); } : undefined}
        >
          <h1 className="text-4xl font-bold sm:mr-4 break-all min-w-0 flex-1">
            {sourceUrl ? (
              <a
                href={sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:opacity-80"
                onClick={(e) => e.stopPropagation()}
              >
                {title}
              </a>
            ) : (
              title
            )}
          </h1>
          <div className="flex justify-end mt-2 sm:mt-0 shrink-0" onClick={(e) => e.stopPropagation()}>
            <ActionButtons />
          </div>
        </div>
      ) : title && isEditingTitle ? (
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-6 pb-2 border-b border-b-border">
          <input
            type="text"
            value={editedTitle}
            onChange={(e) => setEditedTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveTitle();
              if (e.key === "Escape") cancelEditingTitle();
            }}
            onBlur={saveTitle}
            autoFocus
            maxLength={500}
            className="flex-1 text-4xl font-bold bg-transparent border-none outline-none sm:mr-4"
          />
          <div className="flex justify-end mt-2 sm:mt-0">
            <ActionButtons />
          </div>
        </div>
      ) : (
        <div className="-mx-4 px-4 sm:-mx-[8%] sm:px-[8%] md:-mx-[10%] md:px-[10%] mb-6 pb-2 border-b border-b-border">
          <div className="w-full flex items-center justify-between gap-4">
            {isEditingTitle ? (
              <input
                type="text"
                value={editedTitle}
                onChange={(e) => setEditedTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveTitle();
                  if (e.key === "Escape") cancelEditingTitle();
                }}
                onBlur={saveTitle}
                autoFocus
                maxLength={500}
                placeholder="Enter title..."
                className="flex-1 text-2xl font-bold bg-transparent border-none outline-none placeholder:text-muted-foreground/40"
              />
            ) : onTitleChange ? (
              <div
                onClick={startEditingTitle}
                className="flex-1 h-8 cursor-text"
                title="Click to add title"
              />
            ) : (
              <div className="flex-1" />
            )}
            <ActionButtons />
          </div>
        </div>
      )}
      <div ref={contentRef} className="structured-content px-3 break-words" onClick={handleContentClick}>
        {groupedBlocks.map((grouped) => {
          if (grouped.kind === "paragraph-group") {
            return (
              <ParagraphGroupView
                key={grouped.blocks[0].id}
                blocks={grouped.blocks}
                onBlockClick={onBlockClick}
              />
            );
          } else if (grouped.kind === "image-row") {
            return (
              <ImageRowView
                key={grouped.blocks[0].id}
                blocks={grouped.blocks}
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
                className={cn(blockBaseClass, handleWrapperClick && clickableClass)}
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
          content: "";
          display: inline-block;
          width: 0.5em;
          height: 0.5em;
          margin-left: 0.06em;
          vertical-align: -0.1em;
          /* Arrow-up-right icon - longer tail */
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23588157' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M9 5h10v10'/%3E%3Cpath d='M5 19L19 5'/%3E%3C/svg%3E");
          background-size: contain;
          background-repeat: no-repeat;
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
          background: var(--muted-brown);
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

        /* Inline images (from dangerouslySetInnerHTML) */
        .structured-content img {
          display: block;
          max-width: 100%;
          max-height: 24rem;
          width: auto;
          height: auto;
          object-fit: contain;
          border-radius: 0.25rem;
          margin: 0.75rem auto;
        }

        /* Embedded videos */
        .structured-content video {
          display: block;
          margin: 0.75rem auto;
        }

        /* Block-level audio blocks - padding + negative margin keeps text position unchanged */
        .structured-content [data-audio-block-idx] {
          padding-left: 0.625rem;
          padding-right: 0.625rem;
          margin-left: -0.625rem;
          margin-right: -0.625rem;
          border-radius: 0.5rem;
        }
        /* Inline spans - minimal padding for subtle highlight extension */
        .structured-content span[data-audio-block-idx] {
          padding-left: 0.0625rem;
          padding-right: 0.0625rem;
          margin-left: -0.0625rem;
          margin-right: -0.0625rem;
          border-radius: 0.25rem;
        }

        /* Active audio block highlighting - just toggle background */
        .structured-content .audio-block-active {
          background: oklch(0.55 0.1 133.7 / 0.15);
          border-left-color: oklch(0.55 0.1 133.7);
        }

        /* Hover highlighting from progress bar */
        .structured-content .audio-block-hovered {
          background: oklch(0.55 0.1 133.7 / 0.1);
          border-left-color: oklch(0.55 0.1 133.7 / 0.6);
        }

        /* Native hover on clickable blocks */
        .structured-content .clickable-block:hover:not(.audio-block-active) {
          background: oklch(0.55 0.1 133.7 / 0.1);
        }
        .structured-content .clickable-span:hover:not(.audio-block-active) {
          background: oklch(0.55 0.1 133.7 / 0.1);
        }
      `}</style>
    </article>
  );
});

// Export types for use elsewhere
export type { StructuredDocument, ContentBlock, InlineContent };
