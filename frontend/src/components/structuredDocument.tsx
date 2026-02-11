import { Component, memo, useCallback, useEffect, useMemo, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import katex from "katex";
import { Copy, Download, Music, Check, ChevronRight, FileDown, FileCode2 } from "lucide-react";
import { InlineContentRenderer } from "./inlineContent";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import type { Section } from "@/lib/sectionIndex";
import { filterVisibleBlocks } from "@/lib/filterVisibleBlocks";
import { useSettings, type ContentWidth } from "@/hooks/useSettings";

const contentWidthClasses: Record<ContentWidth, string> = {
  narrow: "max-w-2xl",  // 672px
  medium: "max-w-4xl",  // 896px
  wide: "max-w-6xl",    // 1152px
  full: "",             // no limit
};

export function stripYapTags(markdown: string): string {
  return markdown
    .replace(/<yap-speak>[\s\S]*?<\/yap-speak>/g, "")
    .replace(/<yap-show>([\s\S]*?)<\/yap-show>/g, "$1")
    .replace(/<yap-cap>([\s\S]*?)<\/yap-cap>/g, "$1")
    .replace(/  +/g, " ")
    .replace(/\n{3,}/g, "\n\n");
}

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

// Extract plain text from AST for slug generation
function extractTextFromAst(nodes: InlineContent[]): string {
  return nodes.map(node => {
    switch (node.type) {
      case "text":
      case "code_span":
        return node.content;
      case "strong":
      case "emphasis":
      case "strikethrough":
      case "link":
        return extractTextFromAst(node.content);
      case "inline_image":
        return node.alt;
      case "math_inline":
        return ""; // Math doesn't contribute to slug
      default:
        return "";
    }
  }).join("");
}

function buildSlugMap(blocks: ContentBlock[]): Map<string, string> {
  const slugMap = new Map<string, string>();
  const slugCounts = new Map<string, number>();

  for (const block of blocks) {
    if (block.type === "heading") {
      const plainText = extractTextFromAst(block.ast);
      const baseSlug = generateSlug(plainText);
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

interface AudioChunk {
  text: string;
  audio_block_idx: number;
  ast?: InlineContent[];
}

type InlineContent =
  | { type: "text"; content: string }
  | { type: "code_span"; content: string }
  | { type: "strong"; content: InlineContent[] }
  | { type: "emphasis"; content: InlineContent[] }
  | { type: "link"; href: string; title?: string; content: InlineContent[] }
  | { type: "inline_image"; src: string; alt: string }
  | { type: "math_inline"; content: string }
  | { type: "speak"; content: string }  // TTS-only, doesn't render
  | { type: "show"; content: InlineContent[] }  // Display-only, no TTS
  | { type: "strikethrough"; content: InlineContent[] }
  | { type: "hardbreak" }
  | { type: "footnote_ref"; label: string; has_content: boolean }  // Display-only superscript
  | { type: "list"; ordered: boolean; start?: number; items: InlineContent[][] };  // Nested list

interface ListItem {
  html: string;
  ast: InlineContent[];
  audio_chunks: AudioChunk[];
}

interface HeadingBlock {
  type: "heading";
  id: string;
  level: 1 | 2 | 3 | 4 | 5 | 6;
  html: string;
  ast: InlineContent[];
  audio_chunks: AudioChunk[];
}

interface ParagraphBlock {
  type: "paragraph";
  id: string;
  html: string;  // Contains <span data-audio-idx="N"> wrappers if split
  ast: InlineContent[];
  audio_chunks: AudioChunk[];
}

interface ListBlock {
  type: "list";
  id: string;
  ordered: boolean;
  start?: number;
  items: ListItem[];
  audio_chunks: AudioChunk[];  // Always empty (items have chunks)
}

interface BlockquoteBlock {
  type: "blockquote";
  id: string;
  callout_type?: string;  // "BLUE", "GREEN", "PURPLE", "RED", "YELLOW", "TEAL"
  callout_title?: string;  // Optional title like "Definition 1.2"
  blocks: ContentBlock[];
  audio_chunks: AudioChunk[];  // Title audio if callout, else empty
}

interface CodeBlock {
  type: "code";
  id: string;
  language?: string;
  content: string;
  audio_chunks: AudioChunk[];  // Always empty
}

interface MathBlock {
  type: "math";
  id: string;
  content: string;  // LaTeX
  display_mode: boolean;
  audio_chunks: AudioChunk[];
}

interface TableCell {
  ast: InlineContent[];
}

interface TableBlock {
  type: "table";
  id: string;
  headers: TableCell[];
  rows: TableCell[][];
  audio_chunks: AudioChunk[];  // Always empty
}

interface ImageBlock {
  type: "image";
  id: string;
  src: string;
  alt: string;
  caption?: string;  // Display caption (with LaTeX)
  caption_html?: string;  // Caption with span wrappers if split
  title?: string;
  width_pct?: number;  // Figure width as % of page (from YOLO detection)
  row_group?: string;  // "row0", "row1", etc. - figures in same row are side-by-side
  audio_chunks: AudioChunk[];
}

interface ThematicBreak {
  type: "hr";
  id: string;
  audio_chunks: AudioChunk[];  // Always empty
}

interface FootnoteItem {
  label: string;  // Footnote label (may be deduplicated like "1-2")
  has_ref: boolean;  // False if no matching inline [^label] exists
  blocks: ContentBlock[];  // Nested content
  audio_chunks: AudioChunk[];
}

interface FootnotesBlock {
  type: "footnotes";
  id: string;
  items: FootnoteItem[];
  audio_chunks: AudioChunk[];  // Always empty (items have chunks)
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
  | ThematicBreak
  | FootnotesBlock;

interface StructuredDocument {
  version: string;
  blocks: ContentBlock[];
}

// === Block renderers ===

function AudioContent({ ast, audioChunks }: { ast?: InlineContent[]; audioChunks: AudioChunk[] }) {
  if (audioChunks.length <= 1) {
    return <InlineContentRenderer nodes={audioChunks[0]?.ast ?? ast} />;
  }
  return (
    <>
      {audioChunks.map((chunk) => (
        <span key={chunk.audio_block_idx} data-audio-idx={chunk.audio_block_idx}>
          <InlineContentRenderer nodes={chunk.ast} />
        </span>
      ))}
    </>
  );
}

class BlockErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Block render error:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <p className="text-sm text-muted-foreground italic py-1">
          Content failed to render
        </p>
      );
    }
    return this.props.children;
  }
}

interface BlockProps {
  block: ContentBlock;
  onClick?: () => void;
}

// Always have border-l-4 to prevent layout shift when active state changes
// Active state is managed via DOM manipulation in PlaybackPage, not React props (avoids re-renders)
const blockBaseClass = "border-l-4 border-l-transparent transition-colors duration-150";
const clickableClass = "cursor-pointer clickable-block";

interface HeadingBlockViewProps {
  block: HeadingBlock;
  slugId?: string;
  // Section collapse props (only for H1/H2 section headers)
  isCollapsed?: boolean;
  canCollapse?: boolean; // false if current block is in this section
  onToggleCollapse?: () => void;
}

function HeadingBlockView({ block, slugId, isCollapsed, canCollapse = true, onToggleCollapse }: HeadingBlockViewProps) {
  const [isHovered, setIsHovered] = useState(false);
  const isSectionHeader = onToggleCollapse !== undefined;
  const showChevron = isSectionHeader && canCollapse;

  const sizeClasses: Record<number, string> = {
    1: "text-3xl font-bold mt-8 mb-4",
    2: "text-2xl font-semibold mt-6 mb-3",
    3: "text-xl font-semibold mt-5 mb-2",
    4: "text-lg font-medium mt-4 mb-2",
    5: "text-base font-medium mt-3 mb-1",
    6: "text-sm font-medium mt-2 mb-1",
  };

  const headingClassName = cn(
    sizeClasses[block.level],
    "py-1",
    isCollapsed && "text-muted-foreground cursor-pointer"
  );

  const handleHeaderClick = (e: React.MouseEvent) => {
    if (isCollapsed && onToggleCollapse) {
      e.stopPropagation();
      onToggleCollapse();
    }
  };

  const HeadingTag = `h${block.level}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';

  if (!showChevron) {
    return (
      <HeadingTag
        id={slugId}
        className={headingClassName}
        onClick={isCollapsed ? handleHeaderClick : undefined}
      >
        <InlineContentRenderer nodes={block.ast} />
      </HeadingTag>
    );
  }

  // Chevron in fixed-position box, heading unaffected
  return (
    <div
      className="relative"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Chevron box - fixed size, fixed position, only opacity and internal rotation change */}
      <div className="absolute -left-6 top-0 bottom-0 w-5 hidden md:flex items-center justify-center">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onToggleCollapse?.();
          }}
          className={cn(
            "flex items-center justify-center w-5 h-5 text-muted-foreground hover:text-foreground transition-opacity",
            isCollapsed ? "opacity-100" : (isHovered ? "opacity-70" : "opacity-0")
          )}
          title={isCollapsed ? "Expand section" : "Collapse section"}
        >
          <ChevronRight className={cn(
            "w-4 h-4 transition-transform duration-200",
            !isCollapsed && "rotate-90"
          )} />
        </button>
      </div>
      <HeadingTag
        id={slugId}
        className={headingClassName}
        onClick={handleHeaderClick}
      >
        <InlineContentRenderer nodes={block.ast} />
      </HeadingTag>
    </div>
  );
}

function ParagraphBlockView({ block }: { block: ParagraphBlock }) {
  return (
    <p className="my-3 py-1 leading-relaxed">
      <AudioContent ast={block.ast} audioChunks={block.audio_chunks} />
    </p>
  );
}

// Renders a ListContent node as a proper <ul>/<ol> — used outside AudioContent
// to avoid block-in-inline nesting (<ul> inside <span> is invalid HTML).
function NestedList({ node }: { node: Extract<InlineContent, { type: "list" }> }) {
  const Tag = node.ordered ? "ol" : "ul";
  const listClass = node.ordered ? "list-decimal" : "list-disc";
  return (
    <Tag className={cn("ml-6", listClass)} start={node.start ?? undefined}>
      {node.items.map((item, i) => {
        const nestedLists = item.filter((n): n is Extract<InlineContent, { type: "list" }> => n.type === "list");
        const inlineNodes = item.filter(n => n.type !== "list");
        return (
          <li key={i} className="my-1">
            <InlineContentRenderer nodes={inlineNodes} />
            {nestedLists.map((list, j) => <NestedList key={j} node={list} />)}
          </li>
        );
      })}
    </Tag>
  );
}

function ListBlockView({
  block,
  onBlockClick,
}: {
  block: ListBlock;
  onBlockClick?: (audioIdx: number) => void;
}) {
  const ListTag = block.ordered ? "ol" : "ul";
  const listClass = block.ordered ? "list-decimal" : "list-disc";

  return (
    <ListTag
      className={cn("my-3 ml-6 py-1", listClass)}
      start={block.ordered ? block.start : undefined}
    >
      {block.items.map((item, idx) => {
        const hasAudio = item.audio_chunks.length > 0;
        const nestedLists = item.ast.filter((n): n is Extract<InlineContent, { type: "list" }> => n.type === "list");
        const hasNestedLists = nestedLists.length > 0;

        if (hasNestedLists) {
          // Items with nested lists: render inline text and nested lists separately.
          // Can't use AudioContent because <ul> inside <span> is invalid HTML.
          const visibleChunks = item.audio_chunks.filter(c => c.ast?.some(n => n.type !== "list"));
          const lostChunkIdxs = item.audio_chunks
            .filter(c => !c.ast?.some(n => n.type !== "list"))
            .map(c => c.audio_block_idx);

          return (
            <li key={idx} className="my-1">
              {/* Inline text: each chunk gets its own span for per-chunk highlighting */}
              {visibleChunks.map(chunk => (
                <span key={chunk.audio_block_idx} data-audio-idx={chunk.audio_block_idx}>
                  <InlineContentRenderer nodes={chunk.ast} />
                </span>
              ))}
              {/* Fallback for no visible chunks (old docs) */}
              {visibleChunks.length === 0 && !lostChunkIdxs.length && (
                <InlineContentRenderer nodes={item.ast.filter(n => n.type !== "list")} />
              )}
              {/* Nested list: highlight target for nested-list audio chunks.
                 Uses :has(.audio-block-active) CSS to stay highlighted through ALL
                 nested chunks, not just the first one (markers trigger the rule). */}
              <div
                data-audio-idx={lostChunkIdxs[0]}
                className={cn(
                  "nested-list-audio transition-colors duration-150 rounded",
                  onBlockClick && lostChunkIdxs.length > 0 && "cursor-pointer"
                )}
                onClick={onBlockClick && lostChunkIdxs[0] !== undefined
                  ? () => onBlockClick(lostChunkIdxs[0])
                  : undefined}
              >
                {/* Marker spans for additional lost chunk indices — display:contents
                    so :has(.audio-block-active) on the parent div detects them */}
                {lostChunkIdxs.slice(1).map(chunkIdx => (
                  <span key={chunkIdx} data-audio-idx={chunkIdx} style={{ display: "contents" }} />
                ))}
                {nestedLists.map((list, i) => <NestedList key={i} node={list} />)}
              </div>
            </li>
          );
        }

        // Regular items (no nested lists): use AudioContent for chunk-level rendering
        const hasSingleChunk = item.audio_chunks.length === 1;
        const firstAudioIdx = hasAudio ? item.audio_chunks[0].audio_block_idx : undefined;
        const isClickable = hasSingleChunk && onBlockClick;
        return (
          <li
            key={idx}
            className={cn("my-1", isClickable && "cursor-pointer hover:bg-accent/50 rounded px-1 -mx-1")}
            data-audio-block-idx={hasSingleChunk ? firstAudioIdx : undefined}
            onClick={isClickable ? () => onBlockClick?.(firstAudioIdx!) : undefined}
          >
            <AudioContent ast={item.ast} audioChunks={item.audio_chunks} />
          </li>
        );
      })}
    </ListTag>
  );
}

// Callout color palette (muted/warm to match theme)
const calloutColors: Record<string, { border: string; bg: string }> = {
  BLUE: { border: "#6B8CAE", bg: "rgba(107, 140, 174, 0.1)" },
  GREEN: { border: "#7A9E7E", bg: "rgba(122, 158, 126, 0.1)" },
  PURPLE: { border: "#9B8AA6", bg: "rgba(155, 138, 166, 0.1)" },
  RED: { border: "#C98B8B", bg: "rgba(201, 139, 139, 0.1)" },
  YELLOW: { border: "#C9B87A", bg: "rgba(201, 184, 122, 0.1)" },
  TEAL: { border: "#6B9E9E", bg: "rgba(107, 158, 158, 0.1)" },
  GRAY: { border: "#8C8C8C", bg: "rgba(140, 140, 140, 0.1)" },
};

function BlockquoteBlockView({ block, onBlockClick }: {
  block: BlockquoteBlock;
  onBlockClick?: (audioIdx: number) => void;
}) {
  // Group nested blocks by row_group for side-by-side images
  const groupedBlocks = groupBlocks(block.blocks);

  // Check if this is a callout
  const isCallout = !!block.callout_type;
  const colors = block.callout_type ? calloutColors[block.callout_type] : null;

  // Title audio handling for callouts
  const hasTitleAudio = block.audio_chunks.length > 0;
  const titleAudioIdx = hasTitleAudio ? block.audio_chunks[0].audio_block_idx : undefined;
  const handleTitleClick = hasTitleAudio && onBlockClick
    ? () => onBlockClick(titleAudioIdx!)
    : undefined;

  return (
    <blockquote
      className={cn(
        "my-4 pl-4 py-2",
        isCallout
          ? "border-l-4 rounded-r not-italic text-foreground"
          : "border-l-4 border-muted-foreground/30 italic text-muted-foreground"
      )}
      style={colors ? {
        borderLeftColor: colors.border,
        backgroundColor: colors.bg,
      } : undefined}
    >
      {/* Callout title */}
      {block.callout_title && (
        <div
          className={cn(
            "font-semibold mb-2 transition-colors duration-150",
            handleTitleClick && clickableClass
          )}
          style={{ color: colors?.border }}
          data-audio-block-idx={hasTitleAudio ? titleAudioIdx : undefined}
          onClick={handleTitleClick}
        >
          {block.callout_title}
        </div>
      )}

      {/* Content - nested blocks need data-audio-block-idx for playback highlighting */}
      {groupedBlocks.map((grouped) => {
        if (grouped.kind === "image-row") {
          return (
            <ImageRowView
              key={grouped.blocks[0].id}
              blocks={grouped.blocks}
              onBlockClick={onBlockClick}
            />
          );
        } else {
          const b = grouped.block;
          const hasAudio = b.audio_chunks.length > 0;
          const hasSingleChunk = b.audio_chunks.length === 1;
          const firstAudioIdx = hasAudio ? b.audio_chunks[0].audio_block_idx : undefined;
          const handleClick = hasSingleChunk && onBlockClick
            ? () => onBlockClick(firstAudioIdx!)
            : undefined;
          return (
            <div
              key={b.id}
              data-audio-block-idx={hasSingleChunk ? firstAudioIdx : undefined}
              className={cn("transition-colors duration-150", handleClick && clickableClass)}
              onClick={handleClick}
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
              >
                <InlineContentRenderer nodes={header.ast} />
              </th>
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
                >
                  <InlineContentRenderer nodes={cell.ast} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImageBlockView({ block, inRow }: BlockProps & { block: ImageBlock; inRow?: boolean }) {
  return (
    <figure className={cn("flex flex-col items-center", !inRow && "my-4")}>
      <img
        src={block.src}
        alt={block.alt}
        title={block.title}
        className="max-w-full max-h-96 h-auto object-contain rounded"
      />
      {block.audio_chunks.length > 0 && (
        <figcaption className="text-sm text-muted-foreground mt-2 text-center">
          <AudioContent audioChunks={block.audio_chunks} />
        </figcaption>
      )}
    </figure>
  );
}

function ThematicBreakView() {
  return <hr className="my-6 border-t border-border" />;
}

function FootnotesBlockView({ block, onBlockClick }: {
  block: FootnotesBlock;
  onBlockClick?: (audioIdx: number) => void;
}) {
  if (block.items.length === 0) return null;

  return (
    <div className="mt-12 pt-4 border-t border-border">
      <h4 className="text-sm font-semibold text-muted-foreground mb-4">Footnotes</h4>
      <ol className="list-none ml-0 text-sm space-y-3">
        {block.items.map((item) => {
          return (
            <li
              key={item.label}
              id={`fn-${item.label}`}
              className={cn(
                "flex gap-2",
                !item.has_ref && "opacity-60"  // Dim orphan footnotes
              )}
            >
              <span className="font-semibold text-muted-foreground shrink-0">
                [{item.label}]
              </span>
              <div className="flex-1">
                {item.blocks.map((contentBlock) => {
                  const hasAudio = contentBlock.audio_chunks.length > 0;
                  const hasSingleChunk = contentBlock.audio_chunks.length === 1;
                  const firstAudioIdx = hasAudio ? contentBlock.audio_chunks[0].audio_block_idx : undefined;
                  const handleClick = hasSingleChunk && onBlockClick
                    ? () => onBlockClick(firstAudioIdx!)
                    : undefined;

                  return (
                    <span
                      key={contentBlock.id}
                      data-audio-block-idx={hasSingleChunk ? firstAudioIdx : undefined}
                      className={cn(
                        handleClick && "cursor-pointer hover:bg-accent/50 rounded px-1 -mx-1"
                      )}
                      onClick={handleClick}
                    >
                      {contentBlock.type === "paragraph" && (
                        <AudioContent ast={contentBlock.ast} audioChunks={contentBlock.audio_chunks} />
                      )}
                    </span>
                  );
                })}
                {/* Back-link to ref */}
                {item.has_ref && (
                  <a
                    href={`#fnref-${item.label}`}
                    className="ml-2 text-primary hover:text-primary/80 no-underline"
                    title="Back to reference"
                  >
                    ↩
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// === Block grouping for visual continuity ===

type GroupedBlock =
  | { kind: "single"; block: ContentBlock }
  | { kind: "image-row"; blocks: ImageBlock[] };

function groupBlocks(blocks: ContentBlock[]): GroupedBlock[] {
  const result: GroupedBlock[] = [];
  let currentImageRow: ImageBlock[] = [];
  let currentImageRowGroup: string | null = null;

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
    // Handle image row groups
    if (block.type === "image" && block.row_group) {
      if (block.row_group === currentImageRowGroup) {
        currentImageRow.push(block);
      } else {
        flushImageRow();
        currentImageRow = [block];
        currentImageRowGroup = block.row_group;
      }
      continue;
    }

    // Single block - flush any pending image row first
    flushImageRow();
    result.push({ kind: "single", block });
  }

  flushImageRow();
  return result;
}

// Renders multiple image blocks in a flex row (side-by-side figures)
// Normalizes widths so images fill available space proportionally
function ImageRowView({ blocks, onBlockClick }: { blocks: ImageBlock[]; onBlockClick?: (audioIdx: number) => void }) {
  // Calculate scaled widths: preserve relative proportions but fill ~95% of space
  const totalRawWidth = blocks.reduce((sum, b) => sum + (b.width_pct || 50), 0);
  const targetTotalWidth = 95; // Leave 5% for gaps
  const scaleFactor = Math.min(targetTotalWidth / totalRawWidth, 2.5); // Cap scaling to prevent oversized images

  return (
    <div className="my-4 flex gap-4 justify-center items-start flex-wrap">
      {blocks.map((block) => {
        const scaledWidth = Math.min((block.width_pct || 50) * scaleFactor, 100);
        const hasAudio = block.audio_chunks.length > 0;
        const hasSingleChunk = block.audio_chunks.length === 1;
        const firstAudioIdx = hasAudio ? block.audio_chunks[0].audio_block_idx : undefined;
        // Only make wrapper clickable/hoverable if single chunk (not split caption)
        const handleClick = hasSingleChunk && onBlockClick
          ? () => onBlockClick(firstAudioIdx!)
          : undefined;
        return (
          <div
            key={block.id}
            data-audio-block-idx={hasSingleChunk ? firstAudioIdx : undefined}
            className={cn(blockBaseClass, handleClick && clickableClass)}
            style={{ width: `${scaledWidth}%` }}
            onClick={handleClick}
          >
            <ImageBlockView
              block={{ ...block, width_pct: undefined }}
              inRow
            />
          </div>
        );
      })}
    </div>
  );
}

// === Main block renderer ===

interface BlockViewProps {
  block: ContentBlock;
  onBlockClick?: (audioIdx: number) => void;
  slugMap?: Map<string, string>;
  // Section collapse props for headings
  isCollapsed?: boolean;
  canCollapse?: boolean;
  onToggleCollapse?: () => void;
}

function BlockView({ block, onBlockClick, slugMap, isCollapsed, canCollapse, onToggleCollapse }: BlockViewProps) {
  switch (block.type) {
    case "heading":
      return (
        <HeadingBlockView
          block={block}
          slugId={slugMap?.get(block.id)}
          isCollapsed={isCollapsed}
          canCollapse={canCollapse}
          onToggleCollapse={onToggleCollapse}
        />
      );
    case "paragraph":
      return <ParagraphBlockView block={block} />;
    case "list":
      return <ListBlockView block={block} onBlockClick={onBlockClick} />;
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
    case "footnotes":
      return <FootnotesBlockView block={block} onBlockClick={onBlockClick} />;
    default:
      return null;
  }
}

// === Action buttons ===

function ActionButtons({
  copied,
  hasContent,
  onCopy,
  onDownload,
}: {
  copied: boolean;
  hasContent: boolean;
  onCopy: () => void;
  onDownload: (preserveAnnotations: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-1 shrink-0">
      <button
        onClick={onCopy}
        disabled={!hasContent}
        className="p-2 rounded hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        title={copied ? "Copied!" : "Copy markdown"}
      >
        {copied ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4 text-muted-foreground" />}
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            disabled={!hasContent}
            className="p-2 rounded hover:bg-muted transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            title="Download markdown"
          >
            <Download className="h-4 w-4 text-muted-foreground" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => onDownload(false)}>
            <FileDown className="h-4 w-4" />
            Markdown
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onDownload(true)}>
            <FileCode2 className="h-4 w-4" />
            With TTS annotations
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <button
        disabled
        className="p-2 rounded opacity-40 cursor-not-allowed"
        title="Export as audio (coming soon)"
      >
        <Music className="h-4 w-4 text-muted-foreground" />
      </button>
    </div>
  );
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
  // Section filtering for outliner integration
  sections?: Section[];
  expandedSections?: Set<string>;
  skippedSections?: Set<string>;
  onSectionExpand?: (sectionId: string) => void;
  currentBlockIdx?: number; // To prevent collapsing section containing current block
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
  sections,
  expandedSections,
  skippedSections,
  onSectionExpand,
  currentBlockIdx,
}: StructuredDocumentViewProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editedTitle, setEditedTitle] = useState("");

  const handleCopyMarkdown = useCallback(async () => {
    if (!markdownContent) return;
    try {
      await navigator.clipboard.writeText(stripYapTags(markdownContent));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  }, [markdownContent]);

  const sanitizedTitle = (title || "document").replace(/[^a-z0-9]/gi, "_").toLowerCase();

  const handleDownloadMarkdown = useCallback((preserveAnnotations = false) => {
    if (!markdownContent) return;
    const content = preserveAnnotations ? markdownContent : stripYapTags(markdownContent);
    const suffix = preserveAnnotations ? " (annotated)" : "";
    const filename = `${sanitizedTitle}${suffix}.md`;
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [markdownContent, sanitizedTitle]);

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

  // Handle clicks on links and audio spans within document content
  const handleContentClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;

    // Check for link clicks FIRST (before audio spans)
    // This ensures footnote refs and other links work even inside split paragraphs
    const anchor = target.closest("a") as HTMLAnchorElement | null;
    if (anchor) {
      const href = anchor.getAttribute("href");
      if (href) {
        // Anchor links (#fragment) - scroll to element if exists
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
          return;
        }
      }

      e.preventDefault();
      return;
    }

    // Check for clicks on inner audio spans (data-audio-idx)
    // These are spans inside split paragraphs/captions that have their own audio index
    const audioSpan = target.closest("[data-audio-idx]") as HTMLElement | null;
    if (audioSpan && onBlockClick) {
      const audioIdx = audioSpan.getAttribute("data-audio-idx");
      if (audioIdx !== null) {
        e.preventDefault();
        e.stopPropagation();
        onBlockClick(parseInt(audioIdx, 10));
        return;
      }
    }
  }, [onBlockClick]);

  const { settings } = useSettings();

  // pb-52 (208px) provides clearance above the fixed SoundControl bar (~177px)
  // Content width is user-configurable; when constrained, use fixed padding instead of percentage
  const hasMaxWidth = settings.contentWidth !== "full";
  const containerClass = cn(
    "w-full flex flex-col overflow-y-auto pt-4 sm:pt-[4%] pb-52",
    hasMaxWidth ? "px-4 sm:px-6 mx-auto" : "px-4 sm:px-[8%] md:px-[10%]",
    contentWidthClasses[settings.contentWidth]
  );

  // Build map from heading block ID to section (for collapse/expand UI)
  // Must be before early return to satisfy React hooks rules
  const sectionByHeadingId = useMemo(() => {
    const map = new Map<string, Section>();
    if (sections) {
      for (const section of sections) {
        map.set(section.id, section);
      }
    }
    return map;
  }, [sections]);

  // Filter blocks based on section state (must be before early return)
  const visibleBlocks = useMemo(() => {
    if (!doc?.blocks || !sections || sections.length === 0 || !expandedSections) {
      return doc?.blocks ?? [];
    }
    return filterVisibleBlocks(
      doc.blocks,
      sections,
      expandedSections,
      skippedSections ?? new Set<string>(),
      sectionByHeadingId,
    );
  }, [doc?.blocks, sections, expandedSections, skippedSections, sectionByHeadingId]);

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
              <ActionButtons copied={copied} hasContent={!!markdownContent} onCopy={handleCopyMarkdown} onDownload={handleDownloadMarkdown} />
            </div>
          </div>
        ) : (
          <div className={cn(
            "mb-4 pb-2 border-b border-b-border",
            !hasMaxWidth && "-mx-4 px-4 sm:-mx-[8%] sm:px-[8%] md:-mx-[10%] md:px-[10%]"
          )}>
            <div className="w-full flex justify-end">
              <ActionButtons copied={copied} hasContent={!!markdownContent} onCopy={handleCopyMarkdown} onDownload={handleDownloadMarkdown} />
            </div>
          </div>
        )}
        <pre className="whitespace-pre-wrap break-words w-full">
          {fallbackContent || "No content available"}
        </pre>
      </div>
    );
  }

  // Group consecutive images with same row_group for side-by-side display
  const groupedBlocks = groupBlocks(visibleBlocks);

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
            <ActionButtons copied={copied} hasContent={!!markdownContent} onCopy={handleCopyMarkdown} onDownload={handleDownloadMarkdown} />
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
            <ActionButtons copied={copied} hasContent={!!markdownContent} onCopy={handleCopyMarkdown} onDownload={handleDownloadMarkdown} />
          </div>
        </div>
      ) : (
        <div className={cn(
          "mb-6 pb-2 border-b border-b-border",
          // Only use negative margin trick for full width (percentage padding); constrained widths use fixed padding
          !hasMaxWidth && "-mx-4 px-4 sm:-mx-[8%] sm:px-[8%] md:-mx-[10%] md:px-[10%]"
        )}>
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
            <ActionButtons copied={copied} hasContent={!!markdownContent} onCopy={handleCopyMarkdown} onDownload={handleDownloadMarkdown} />
          </div>
        </div>
      )}
      <div ref={contentRef} className="structured-content px-3 break-words" onClick={handleContentClick}>
        {groupedBlocks.map((grouped) => {
          if (grouped.kind === "image-row") {
            return (
              <BlockErrorBoundary key={grouped.blocks[0].id}>
                <ImageRowView
                  blocks={grouped.blocks}
                  onBlockClick={onBlockClick}
                />
              </BlockErrorBoundary>
            );
          } else {
            const block = grouped.block;
            // Check if this is a section header (H1/H2)
            const section = sectionByHeadingId.get(block.id);
            const isCollapsed = section ? !expandedSections?.has(section.id) : false;
            // Can't collapse section if current block is in it
            const canCollapse = section && currentBlockIdx !== undefined
              ? !(currentBlockIdx >= section.startBlockIdx && currentBlockIdx <= section.endBlockIdx)
              : true;
            const handleToggleCollapse = section && onSectionExpand
              ? () => onSectionExpand(section.id)
              : undefined;

            // Container blocks (blockquote, list, footnotes) handle their own inner highlighting
            // Don't add data-audio-block-idx to their wrapper - it causes double highlight
            const isContainerBlock = block.type === "blockquote" || block.type === "list" || block.type === "footnotes";
            const hasAudio = block.audio_chunks.length > 0;
            const hasSingleChunk = block.audio_chunks.length === 1;
            const firstAudioIdx = hasAudio ? block.audio_chunks[0].audio_block_idx : undefined;
            const handleWrapperClick = hasSingleChunk && !isContainerBlock && onBlockClick
              ? () => onBlockClick(firstAudioIdx!)
              : undefined;
            return (
              <div
                key={block.id}
                data-audio-block-idx={hasSingleChunk && !isContainerBlock ? firstAudioIdx : undefined}
                className={cn(blockBaseClass, handleWrapperClick && clickableClass)}
                onClick={handleWrapperClick}
              >
                <BlockErrorBoundary>
                  <BlockView
                    block={block}
                    onBlockClick={onBlockClick}
                    slugMap={slugMap}
                    isCollapsed={isCollapsed}
                    canCollapse={canCollapse}
                    onToggleCollapse={handleToggleCollapse}
                  />
                </BlockErrorBoundary>
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

        /* Inline images */
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
        /* Inside callouts: keep highlight within the callout bounds */
        .structured-content blockquote [data-audio-block-idx] {
          margin-left: 0;
          margin-right: 0;
          padding-left: 0.375rem;
          padding-right: 0.375rem;
        }
        /* Inner audio spans (within split paragraphs/captions) - clickable and highlightable */
        .structured-content [data-audio-idx] {
          cursor: pointer;
          padding-left: 0.125rem;
          padding-right: 0.125rem;
          margin-left: -0.125rem;
          margin-right: -0.125rem;
          border-radius: 0.25rem;
          transition: background-color 0.15s;
        }

        /* Active audio block highlighting - just toggle background */
        .structured-content .audio-block-active {
          background: oklch(0.55 0.1 133.7 / 0.15);
          border-left-color: oklch(0.55 0.1 133.7);
        }
        /* Nested list wrapper: stay highlighted when ANY child marker is active.
           Markers use display:contents (no box), so :has() propagates their state. */
        .structured-content .nested-list-audio:has(.audio-block-active) {
          background: oklch(0.55 0.1 133.7 / 0.15);
        }

        /* Hover highlighting from progress bar */
        .structured-content .audio-block-hovered {
          background: oklch(0.55 0.1 133.7 / 0.1);
          border-left-color: oklch(0.55 0.1 133.7 / 0.6);
        }
        .structured-content .nested-list-audio:has(.audio-block-hovered) {
          background: oklch(0.55 0.1 133.7 / 0.1);
        }

        /* Native hover on clickable blocks */
        .structured-content .clickable-block:hover:not(.audio-block-active) {
          background: oklch(0.55 0.1 133.7 / 0.1);
        }
        .structured-content .clickable-span:hover:not(.audio-block-active) {
          background: oklch(0.55 0.1 133.7 / 0.1);
        }
        /* Native hover on inner audio spans */
        .structured-content [data-audio-idx]:hover:not(.audio-block-active) {
          background: oklch(0.55 0.1 133.7 / 0.1);
        }
      `}</style>
    </article>
  );
});

// Export types for use elsewhere
export type { StructuredDocument, ContentBlock, InlineContent, AudioChunk };
// Test-only exports
export { AudioContent, BlockErrorBoundary };
