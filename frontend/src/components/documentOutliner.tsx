import * as React from "react";
import { ChevronRight, ChevronDown, Minus, Plus, EyeOff, Eye } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Popover,
  PopoverContent,
  PopoverAnchor,
} from "@/components/ui/popover";
import { Section, formatDuration } from "@/lib/sectionIndex";
import { cn } from "@/lib/utils";

interface DocumentOutlinerProps {
  sections: Section[];
  expandedSections: Set<string>;
  skippedSections: Set<string>;
  currentBlockIdx: number;
  onSectionToggle: (sectionId: string) => void;
  onSectionSkip: (sectionId: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onNavigate: (blockIdx: number) => void;
}

export function DocumentOutliner({
  sections,
  expandedSections,
  skippedSections,
  currentBlockIdx,
  onSectionToggle,
  onSectionSkip,
  onExpandAll,
  onCollapseAll,
  onNavigate,
}: DocumentOutlinerProps) {
  const [popoverOpen, setPopoverOpen] = React.useState<string | null>(null);
  const longPressTimerRef = React.useRef<number | null>(null);
  const longPressFiredRef = React.useRef(false);

  const currentSectionId = React.useMemo(() => {
    for (const section of sections) {
      if (
        currentBlockIdx >= section.startBlockIdx &&
        currentBlockIdx <= section.endBlockIdx
      ) {
        return section.id;
      }
    }
    return null;
  }, [sections, currentBlockIdx]);

  const handleContextMenu = (e: React.MouseEvent, sectionId: string) => {
    e.preventDefault();
    setPopoverOpen(sectionId);
  };

  const handleTouchStart = (sectionId: string) => {
    longPressFiredRef.current = false;
    longPressTimerRef.current = window.setTimeout(() => {
      longPressFiredRef.current = true;
      setPopoverOpen(sectionId);
    }, 500);
  };

  const handleTouchEnd = () => {
    if (longPressTimerRef.current) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  };

  const handleSkipToggle = (sectionId: string) => {
    onSectionSkip(sectionId);
    setPopoverOpen(null);
  };

  if (sections.length === 0) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        No chapters found in this document.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="font-medium text-muted-foreground">
          Outline
        </span>
        <div className="flex gap-1">
          <button
            onClick={onCollapseAll}
            className="p-1.5 rounded hover:bg-accent"
            aria-label="Collapse all sections"
            title="Collapse all"
          >
            <Minus className="w-4 h-4" />
          </button>
          <button
            onClick={onExpandAll}
            className="p-1.5 rounded hover:bg-accent"
            aria-label="Expand all sections"
            title="Expand all"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {sections.map((section) => {
          const isExpanded = expandedSections.has(section.id);
          const isSkipped = skippedSections.has(section.id);
          const isCurrent = section.id === currentSectionId;
          const hasSubsections = section.subsections.length > 0;
          // Can't collapse the current section (playback is in it)
          const canCollapse = !isCurrent || !isExpanded;

          const sectionContent = (
            <Popover open={popoverOpen === section.id} onOpenChange={(open) => setPopoverOpen(open ? section.id : null)}>
              <PopoverAnchor asChild>
                <div
                  className={cn(
                    "flex items-center gap-1.5 pl-1 pr-3 py-2 hover:bg-accent/50 rounded-md mx-0.5 cursor-default",
                    isCurrent && !isSkipped && "bg-accent",
                    isSkipped && "opacity-50"
                  )}
                  onContextMenu={(e) => handleContextMenu(e, section.id)}
                  onTouchStart={() => handleTouchStart(section.id)}
                  onTouchEnd={handleTouchEnd}
                  onTouchCancel={handleTouchEnd}
                >
                  {/* Collapse toggle: chevron for sections with subsections, +/- for those without */}
                  {/* Hidden/disabled when: skipped, or can't collapse (current section) */}
                  {hasSubsections ? (
                    <CollapsibleTrigger
                      className={cn(
                        "p-0.5 hover:bg-accent rounded shrink-0",
                        (isSkipped || !canCollapse) && "pointer-events-none opacity-30"
                      )}
                      disabled={isSkipped || !canCollapse}
                    >
                      {isExpanded && !isSkipped ? (
                        <ChevronDown className="w-4 h-4 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-muted-foreground" />
                      )}
                    </CollapsibleTrigger>
                  ) : (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (!isSkipped && canCollapse) onSectionToggle(section.id);
                      }}
                      className={cn(
                        "p-0.5 hover:bg-accent rounded shrink-0",
                        (isSkipped || !canCollapse) && "pointer-events-none opacity-30"
                      )}
                      disabled={isSkipped || !canCollapse}
                    >
                      {isExpanded && !isSkipped ? (
                        <Minus className="w-4 h-4 text-muted-foreground" />
                      ) : (
                        <Plus className="w-4 h-4 text-muted-foreground" />
                      )}
                    </button>
                  )}

                  <span
                    onClick={() => {
                      if (longPressFiredRef.current) {
                        longPressFiredRef.current = false;
                        return;
                      }
                      if (!isSkipped) onNavigate(section.startBlockIdx);
                    }}
                    className={cn(
                      "flex-1 text-left truncate min-w-0 cursor-pointer",
                      !isSkipped && "hover:underline",
                      isSkipped && "line-through cursor-default"
                    )}
                    title={section.title}
                  >
                    {section.title}
                  </span>

                  <span className="text-sm text-muted-foreground whitespace-nowrap shrink-0 pl-2">
                    {formatDuration(section.durationMs)}
                  </span>
                </div>
              </PopoverAnchor>
              <PopoverContent
                className="w-auto p-1"
                side="bottom"
                align="start"
              >
                <button
                  onClick={() => handleSkipToggle(section.id)}
                  className="flex items-center gap-2 px-3 py-2 text-sm rounded hover:bg-accent w-full text-left"
                >
                  {isSkipped ? (
                    <>
                      <Eye className="w-4 h-4" />
                      Include in playback
                    </>
                  ) : (
                    <>
                      <EyeOff className="w-4 h-4" />
                      Exclude from playback
                    </>
                  )}
                </button>
              </PopoverContent>
            </Popover>
          );

          if (!hasSubsections) {
            return <div key={section.id}>{sectionContent}</div>;
          }

          return (
            <Collapsible
              key={section.id}
              open={isExpanded && !isSkipped}
              onOpenChange={() => {
                if (!isSkipped) onSectionToggle(section.id);
              }}
            >
              {sectionContent}

              <CollapsibleContent>
                <div className="ml-5 border-l border-border/50">
                  {section.subsections.map((subsection) => {
                    const isSubsectionCurrent =
                      currentBlockIdx >= subsection.blockIdx &&
                      currentBlockIdx <
                        (section.subsections.find(
                          (s) => s.blockIdx > subsection.blockIdx
                        )?.blockIdx ?? section.endBlockIdx + 1);

                    return (
                      <button
                        key={subsection.id}
                        onClick={() => onNavigate(subsection.blockIdx)}
                        className={cn(
                          "w-full text-left py-1.5 pl-2 pr-3 hover:bg-accent/50 truncate text-sm",
                          isSubsectionCurrent && "bg-accent/30"
                        )}
                        title={subsection.title}
                      >
                        {subsection.title}
                      </button>
                    );
                  })}
                </div>
              </CollapsibleContent>
            </Collapsible>
          );
        })}
      </div>
    </div>
  );
}
