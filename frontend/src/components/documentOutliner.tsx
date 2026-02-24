import * as React from "react";
import { ChevronRight, ChevronDown, Minus, Plus } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Section, formatDuration } from "@/lib/sectionIndex";
import { cn } from "@/lib/utils";

interface DocumentOutlinerProps {
  sections: Section[];
  expandedSections: Set<string>;
  currentBlockIdx: number;
  onSectionToggle: (sectionId: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onNavigate: (blockIdx: number) => void;
}

export function DocumentOutliner({
  sections,
  expandedSections,
  currentBlockIdx,
  onSectionToggle,
  onExpandAll,
  onCollapseAll,
  onNavigate,
}: DocumentOutlinerProps) {
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
          const isCollapsed = !isExpanded;
          const isCurrent = section.id === currentSectionId;
          const hasSubsections = section.subsections.length > 0;
          // Can't collapse the current section (playback is in it)
          const canCollapse = !isCurrent || !isExpanded;

          const sectionContent = (
            <div
              className={cn(
                "flex items-center gap-1.5 pl-1 pr-3 py-2 hover:bg-accent/50 rounded-md mx-0.5 cursor-default",
                isCurrent && isExpanded && "bg-accent",
                isCollapsed && "opacity-50"
              )}
            >
              {hasSubsections ? (
                <CollapsibleTrigger
                  className={cn(
                    "p-0.5 hover:bg-accent rounded shrink-0",
                    !canCollapse && "pointer-events-none opacity-30"
                  )}
                  disabled={!canCollapse}
                >
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  )}
                </CollapsibleTrigger>
              ) : (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (canCollapse) onSectionToggle(section.id);
                  }}
                  className={cn(
                    "p-0.5 hover:bg-accent rounded shrink-0",
                    !canCollapse && "pointer-events-none opacity-30"
                  )}
                  disabled={!canCollapse}
                >
                  {isExpanded ? (
                    <Minus className="w-4 h-4 text-muted-foreground" />
                  ) : (
                    <Plus className="w-4 h-4 text-muted-foreground" />
                  )}
                </button>
              )}

              <span
                onClick={() => {
                  if (isCollapsed) {
                    onSectionToggle(section.id);
                  } else {
                    onNavigate(section.startBlockIdx);
                  }
                }}
                className={cn(
                  "flex-1 text-left truncate min-w-0 cursor-pointer",
                  isExpanded && "hover:underline",
                  isCollapsed && "line-through"
                )}
                title={section.title}
              >
                {section.title}
              </span>

              <span className="text-sm text-muted-foreground whitespace-nowrap shrink-0 pl-2">
                {formatDuration(section.durationMs)}
              </span>
            </div>
          );

          if (!hasSubsections) {
            return <div key={section.id}>{sectionContent}</div>;
          }

          return (
            <Collapsible
              key={section.id}
              open={isExpanded}
              onOpenChange={() => {
                onSectionToggle(section.id);
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
