import { cn } from "@/lib/utils";

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
  audio_block_idx: number;
}

interface ParagraphBlock {
  type: "paragraph";
  id: string;
  html: string;
  ast: InlineContent[];
  plain_text: string;
  audio_block_idx: number;
}

interface ListBlock {
  type: "list";
  id: string;
  ordered: boolean;
  start?: number;
  items: ListItem[];
  plain_text: string;
  audio_block_idx: number;
}

interface BlockquoteBlock {
  type: "blockquote";
  id: string;
  blocks: ContentBlock[];
  plain_text: string;
  audio_block_idx: number;
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

function HeadingBlockView({ block, isActive, onClick }: BlockProps & { block: HeadingBlock }) {
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
    className,
    onClick,
    dangerouslySetInnerHTML: { __html: block.html },
  };

  // Use explicit elements to satisfy TypeScript
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
        "my-3 leading-relaxed py-1",
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

function BlockquoteBlockView({ block, isActive, onClick, currentAudioBlockIdx, onBlockClick }: BlockProps & {
  block: BlockquoteBlock;
  currentAudioBlockIdx: number;
  onBlockClick?: (audioIdx: number) => void;
}) {
  return (
    <blockquote
      className={cn(
        "my-4 border-l-4 border-muted-foreground/30 pl-4 italic text-muted-foreground py-1",
        onClick && clickableClass,
        isActive && activeBlockClass
      )}
      onClick={onClick}
    >
      {block.blocks.map((nestedBlock) => (
        <BlockView
          key={nestedBlock.id}
          block={nestedBlock}
          currentAudioBlockIdx={currentAudioBlockIdx}
          onBlockClick={onBlockClick}
        />
      ))}
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
  // Basic math display - could integrate KaTeX/MathJax later
  return (
    <div className="my-4 p-4 bg-muted/50 rounded border border-border text-center font-mono overflow-x-auto">
      <code className="text-sm">{block.content}</code>
    </div>
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

// === Main block renderer ===

interface BlockViewProps {
  block: ContentBlock;
  currentAudioBlockIdx: number;
  onBlockClick?: (audioIdx: number) => void;
}

function BlockView({ block, currentAudioBlockIdx, onBlockClick }: BlockViewProps) {
  const isActive = block.audio_block_idx === currentAudioBlockIdx && currentAudioBlockIdx >= 0;
  const handleClick = block.audio_block_idx !== null && onBlockClick
    ? () => onBlockClick(block.audio_block_idx as number)
    : undefined;

  const baseProps = { block, isActive, onClick: handleClick };

  switch (block.type) {
    case "heading":
      return <HeadingBlockView {...baseProps} block={block} />;
    case "paragraph":
      return <ParagraphBlockView {...baseProps} block={block} />;
    case "list":
      return <ListBlockView {...baseProps} block={block} />;
    case "blockquote":
      return (
        <BlockquoteBlockView
          {...baseProps}
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

export function StructuredDocumentView({
  structuredContent,
  title,
  currentAudioBlockIdx,
  onBlockClick,
  fallbackContent,
}: StructuredDocumentViewProps) {
  // Parse structured content or fall back to plain text
  let doc: StructuredDocument | null = null;

  if (structuredContent) {
    try {
      doc = JSON.parse(structuredContent) as StructuredDocument;
    } catch (e) {
      console.warn("Failed to parse structured content:", e);
    }
  }

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

  return (
    <article className="flex flex-col overflow-y-auto m-[10%] mt-[4%] prose-container">
      {title && (
        <h1 className="mb-6 text-4xl font-bold border-b border-b-border pb-2">
          {title}
        </h1>
      )}
      <div className="structured-content">
        {doc.blocks.map((block) => (
          <BlockView
            key={block.id}
            block={block}
            currentAudioBlockIdx={currentAudioBlockIdx}
            onBlockClick={onBlockClick}
          />
        ))}
      </div>

      {/* Inline styles for HTML content */}
      <style>{`
        .structured-content a {
          color: var(--primary);
          text-decoration: underline;
        }
        .structured-content a:hover {
          opacity: 0.8;
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
}

// Export types for use elsewhere
export type { StructuredDocument, ContentBlock, InlineContent };
