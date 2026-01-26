import * as React from "react";
import { ChevronRight, ChevronDown, Minus, Plus } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  // Find current section for highlighting
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
      {/* Header with expand/collapse all */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="font-medium text-muted-foreground">
          Outline
        </span>
        <div className="flex gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={onCollapseAll}
                className="p-1.5 rounded hover:bg-accent"
                aria-label="Collapse all sections"
              >
                <Minus className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Collapse all</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={onExpandAll}
                className="p-1.5 rounded hover:bg-accent"
                aria-label="Expand all sections"
              >
                <Plus className="w-4 h-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">Expand all</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Sections list */}
      <div className="flex-1 overflow-y-auto py-2">
        {sections.map((section) => {
          const isExpanded = expandedSections.has(section.id);
          const isCurrent = section.id === currentSectionId;
          const hasSubsections = section.subsections.length > 0;

          // Section header content (shared between collapsible and non-collapsible)
          const sectionHeader = (
            <div
              className={cn(
                "flex items-center gap-2 pl-2 pr-4 py-2.5 hover:bg-accent/50 rounded-md mx-1",
                isCurrent && "bg-accent"
              )}
            >
              {/* Chevron only if has subsections, otherwise invisible placeholder */}
              {hasSubsections ? (
                <CollapsibleTrigger className="p-1 hover:bg-accent rounded">
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  )}
                </CollapsibleTrigger>
              ) : (
                <span className="w-6 h-6" /> // Placeholder for alignment
              )}

              <button
                onClick={() => onNavigate(section.startBlockIdx)}
                className="flex-1 text-left truncate hover:underline"
                title={section.title}
              >
                {section.title}
              </button>

              <span className="text-sm text-muted-foreground whitespace-nowrap">
                {formatDuration(section.durationMs)}
              </span>
            </div>
          );

          // If no subsections, don't wrap in Collapsible (cleaner)
          if (!hasSubsections) {
            return <div key={section.id}>{sectionHeader}</div>;
          }

          return (
            <Collapsible
              key={section.id}
              open={isExpanded}
              onOpenChange={() => onSectionToggle(section.id)}
            >
              {sectionHeader}

              {/* Subsections */}
              <CollapsibleContent>
                <div className="ml-7 border-l border-border/50">
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
                          "w-full text-left py-2 pl-3 pr-5 hover:bg-accent/50 truncate",
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
