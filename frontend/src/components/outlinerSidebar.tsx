import * as React from "react";
import { useOutlinerOptional } from "@/hooks/useOutliner";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const SIDEBAR_WIDTH = "18rem"; // Slightly wider than left sidebar for readability
const SIDEBAR_WIDTH_MOBILE = "20rem";

interface OutlinerSidebarProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Right sidebar for the document outliner.
 * Uses OutlinerProvider context for open/close state.
 * Similar to shadcn Sidebar but wired to outliner context.
 */
export function OutlinerSidebar({ children, className }: OutlinerSidebarProps) {
  const outliner = useOutlinerOptional();

  // Don't render if no outliner context
  if (!outliner) return null;

  const { isMobile, state, openMobile, setOpenMobile } = outliner;

  // Mobile: use Sheet component
  if (isMobile) {
    return (
      <Sheet open={openMobile} onOpenChange={setOpenMobile}>
        <SheetContent
          data-slot="outliner-sidebar"
          data-mobile="true"
          className="bg-sidebar text-sidebar-foreground p-0 [&>button]:hidden"
          style={{ "--sidebar-width": SIDEBAR_WIDTH_MOBILE } as React.CSSProperties}
          side="right"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>Document Outline</SheetTitle>
            <SheetDescription>Document structure and navigation.</SheetDescription>
          </SheetHeader>
          <div className="flex h-full w-full flex-col">{children}</div>
        </SheetContent>
      </Sheet>
    );
  }

  // Desktop: fixed sidebar with collapse animation
  return (
    <div
      className="group peer text-sidebar-foreground hidden md:block"
      data-state={state}
      data-collapsible={state === "collapsed" ? "offcanvas" : ""}
      data-side="right"
      data-slot="outliner-sidebar"
    >
      {/* Gap element - pushes content when sidebar opens */}
      <div
        data-slot="outliner-sidebar-gap"
        className={cn(
          "relative bg-transparent transition-[width] duration-200 ease-linear",
          state === "collapsed" ? "w-0" : "w-[var(--sidebar-width)]"
        )}
        style={{ "--sidebar-width": SIDEBAR_WIDTH } as React.CSSProperties}
      />
      {/* Fixed sidebar container */}
      <div
        data-slot="outliner-sidebar-container"
        className={cn(
          "fixed inset-y-0 right-0 z-10 hidden h-svh transition-[right,width] duration-200 ease-linear md:flex",
          state === "collapsed"
            ? "right-[calc(var(--sidebar-width)*-1)]"
            : "right-0",
          "border-l",
          className
        )}
        style={{ "--sidebar-width": SIDEBAR_WIDTH, width: SIDEBAR_WIDTH } as React.CSSProperties}
      >
        <div
          data-slot="outliner-sidebar-inner"
          className="bg-sidebar flex h-full w-full flex-col"
        >
          {children}
        </div>
      </div>
    </div>
  );
}
