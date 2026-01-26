import { useRef, useCallback, useEffect, useState } from "react";
import { useOutlinerOptional } from "@/hooks/useOutliner";
import { useIsMobile } from "@/hooks/use-mobile";

const EDGE_WIDTH = 60;
const SWIPE_THRESHOLD = 50;
const REVEAL_DELAY = 150;
const MOBILE_EDGE_INSET = 20;
const OUTLINER_WIDTH = "18rem"; // Must match outlinerSidebar.tsx SIDEBAR_WIDTH

export function OutlinerEdgeTrigger() {
  const outliner = useOutlinerOptional();
  const isMobile = useIsMobile();
  const [revealed, setRevealed] = useState(false);
  const revealTimeoutRef = useRef<number | null>(null);
  const touchStartX = useRef<number | null>(null);
  const touchStartY = useRef<number | null>(null);

  // Extract values with defaults for when outliner is null
  const enabled = outliner?.enabled ?? false;
  const open = outliner?.open ?? false;
  const toggleOutliner = outliner?.toggleOutliner ?? (() => {});

  // Track cursor entering/leaving right edge zone
  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      const windowWidth = window.innerWidth;
      const inZone = e.clientX >= windowWidth - EDGE_WIDTH;

      if (inZone && !revealed && revealTimeoutRef.current === null) {
        revealTimeoutRef.current = window.setTimeout(() => {
          setRevealed(true);
          revealTimeoutRef.current = null;
        }, REVEAL_DELAY);
      } else if (!inZone) {
        if (revealTimeoutRef.current !== null) {
          clearTimeout(revealTimeoutRef.current);
          revealTimeoutRef.current = null;
        }
        if (revealed) {
          setRevealed(false);
        }
      }
    },
    [revealed]
  );

  const handleMouseLeave = useCallback(() => {
    if (revealTimeoutRef.current !== null) {
      clearTimeout(revealTimeoutRef.current);
      revealTimeoutRef.current = null;
    }
    setRevealed(false);
  }, []);

  useEffect(() => {
    if (!enabled || isMobile || open) {
      setRevealed(false);
      if (revealTimeoutRef.current !== null) {
        clearTimeout(revealTimeoutRef.current);
        revealTimeoutRef.current = null;
      }
      return;
    }

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseleave", handleMouseLeave);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseleave", handleMouseLeave);
      if (revealTimeoutRef.current !== null) {
        clearTimeout(revealTimeoutRef.current);
        revealTimeoutRef.current = null;
      }
    };
  }, [enabled, isMobile, open, handleMouseMove, handleMouseLeave]);

  const handleTouchStart = useCallback((e: TouchEvent) => {
    const touch = e.touches[0];
    const windowWidth = window.innerWidth;
    // Inset from right edge to avoid browser forward gesture
    const inSwipeZone =
      touch.clientX <= windowWidth - MOBILE_EDGE_INSET &&
      touch.clientX >= windowWidth - MOBILE_EDGE_INSET - EDGE_WIDTH;
    if (inSwipeZone) {
      touchStartX.current = touch.clientX;
      touchStartY.current = touch.clientY;
    }
  }, []);

  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      if (touchStartX.current === null || touchStartY.current === null) return;

      const touch = e.touches[0];
      const deltaX = touchStartX.current - touch.clientX; // Swipe left = positive
      const deltaY = Math.abs(touch.clientY - touchStartY.current);

      if (deltaX > SWIPE_THRESHOLD && deltaX > deltaY * 2) {
        toggleOutliner();
        touchStartX.current = null;
        touchStartY.current = null;
      }
    },
    [toggleOutliner]
  );

  const handleTouchEnd = useCallback(() => {
    touchStartX.current = null;
    touchStartY.current = null;
  }, []);

  useEffect(() => {
    if (!enabled || !isMobile) return;

    document.addEventListener("touchstart", handleTouchStart, { passive: true });
    document.addEventListener("touchmove", handleTouchMove, { passive: true });
    document.addEventListener("touchend", handleTouchEnd, { passive: true });

    return () => {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchend", handleTouchEnd);
    };
  }, [enabled, isMobile, handleTouchStart, handleTouchMove, handleTouchEnd]);

  // Don't render if not enabled
  if (!enabled) return null;

  // Mobile: visible button on right side (larger for easier tapping)
  if (isMobile) {
    return (
      <button
        onClick={toggleOutliner}
        className="fixed right-0 z-20
          w-6 h-14 flex items-center justify-center
          bg-background/60 backdrop-blur-sm
          border-y border-l border-border rounded-l-lg
          active:bg-muted/80 transition-colors"
        style={{ top: "65%" }}
        aria-label="Toggle outline"
      >
        <span className="text-muted-foreground text-base font-light">‹</span>
      </button>
    );
  }

  // Desktop: when outliner is open, show close button (larger to avoid scrollbar overlap)
  if (open) {
    return (
      <button
        onClick={toggleOutliner}
        className="fixed top-1/2 -translate-y-1/2 z-20
          w-8 h-20 flex items-center justify-center
          bg-background/70 backdrop-blur-sm
          border-y border-l border-border rounded-l-xl
          shadow-sm hover:bg-muted/80
          transition-[right] duration-200 ease-out"
        style={{
          right: OUTLINER_WIDTH,
        }}
        aria-label="Close outline"
      >
        <span className="text-muted-foreground text-2xl font-extralight">›</span>
      </button>
    );
  }

  // Desktop closed: edge-triggered reveal on right side
  return (
    <>
      <div
        className="fixed right-0 top-0 h-full z-20"
        style={{ width: `${EDGE_WIDTH}px` }}
      />

      <button
        onClick={toggleOutliner}
        className={`fixed right-0 top-1/2 -translate-y-1/2 z-20
          w-8 h-20 flex items-center justify-center
          bg-background/70 backdrop-blur-md
          border-y border-l border-border rounded-l-xl
          shadow-lg hover:bg-muted/80
          transition-all duration-200 ease-out
          focus:outline-none focus-visible:ring-2 focus-visible:ring-ring
          ${revealed ? "opacity-100 translate-x-0" : "opacity-0 translate-x-4 pointer-events-none"}`}
        aria-label="Open outline"
      >
        <span className="text-muted-foreground text-2xl font-extralight">›</span>
      </button>
    </>
  );
}
