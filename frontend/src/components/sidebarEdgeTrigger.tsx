import { useRef, useCallback, useEffect, useState } from "react";
import { useSidebar } from "@/components/ui/sidebar";
import { useIsMobile } from "@/hooks/use-mobile";

const EDGE_WIDTH = 60; // Trigger zone width (px)
const SWIPE_THRESHOLD = 50; // Mobile swipe distance to trigger (px)
const REVEAL_DELAY = 150; // ms cursor must stay in zone before reveal

export function SidebarEdgeTrigger() {
  const { toggleSidebar, open, openMobile } = useSidebar();
  const isMobile = useIsMobile();
  const [revealed, setRevealed] = useState(false);
  const revealTimeoutRef = useRef<number | null>(null);

  // Track cursor entering/leaving edge zone
  const handleMouseMove = useCallback((e: MouseEvent) => {
    const inZone = e.clientX <= EDGE_WIDTH;

    if (inZone && !revealed && revealTimeoutRef.current === null) {
      // Start reveal timer
      revealTimeoutRef.current = window.setTimeout(() => {
        setRevealed(true);
        revealTimeoutRef.current = null;
      }, REVEAL_DELAY);
    } else if (!inZone) {
      // Cancel pending reveal
      if (revealTimeoutRef.current !== null) {
        clearTimeout(revealTimeoutRef.current);
        revealTimeoutRef.current = null;
      }
      // Hide if revealed
      if (revealed) {
        setRevealed(false);
      }
    }
  }, [revealed]);

  const handleMouseLeave = useCallback(() => {
    if (revealTimeoutRef.current !== null) {
      clearTimeout(revealTimeoutRef.current);
      revealTimeoutRef.current = null;
    }
    setRevealed(false);
  }, []);

  useEffect(() => {
    if (isMobile || open) {
      // Clean up when switching to mobile or opening sidebar
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
  }, [isMobile, open, handleMouseMove, handleMouseLeave]);

  // Mobile swipe tracking
  const touchStartX = useRef<number | null>(null);
  const touchStartY = useRef<number | null>(null);

  const handleTouchStart = useCallback((e: TouchEvent) => {
    const touch = e.touches[0];
    if (touch.clientX <= EDGE_WIDTH) {
      touchStartX.current = touch.clientX;
      touchStartY.current = touch.clientY;
    }
  }, []);

  const handleTouchMove = useCallback((e: TouchEvent) => {
    if (touchStartX.current === null || touchStartY.current === null) return;

    const touch = e.touches[0];
    const deltaX = touch.clientX - touchStartX.current;
    const deltaY = Math.abs(touch.clientY - touchStartY.current);

    if (deltaX > SWIPE_THRESHOLD && deltaX > deltaY * 2) {
      toggleSidebar();
      touchStartX.current = null;
      touchStartY.current = null;
    }
  }, [toggleSidebar]);

  const handleTouchEnd = useCallback(() => {
    touchStartX.current = null;
    touchStartY.current = null;
  }, []);

  useEffect(() => {
    if (!isMobile) return;

    document.addEventListener("touchstart", handleTouchStart, { passive: true });
    document.addEventListener("touchmove", handleTouchMove, { passive: true });
    document.addEventListener("touchend", handleTouchEnd, { passive: true });

    return () => {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchend", handleTouchEnd);
    };
  }, [isMobile, handleTouchStart, handleTouchMove, handleTouchEnd]);

  // Mobile: subtle notch in thumb zone (lower on screen)
  // Swipe gesture is primary; this is just for discoverability
  if (isMobile) {
    return (
      <button
        onClick={toggleSidebar}
        className="fixed left-0 z-20
          w-1.5 h-10 flex items-center justify-center
          bg-muted-foreground/20 rounded-r-full
          active:bg-muted-foreground/40 transition-colors"
        style={{ top: '65%' }}
        aria-label="Toggle sidebar"
      />
    );
  }

  // Desktop: when sidebar is open, show a close button at the edge of the sidebar
  if (open) {
    return (
      <button
        onClick={toggleSidebar}
        className="fixed top-1/2 -translate-y-1/2 z-20
          w-6 h-16 flex items-center justify-center
          bg-background/70 backdrop-blur-sm
          border-y border-r border-border rounded-r-lg
          shadow-sm hover:bg-muted/80 transition-colors"
        style={{ left: 'var(--sidebar-width, 256px)' }}
        aria-label="Close sidebar"
      >
        <span className="text-muted-foreground text-xl font-light">
          ‹
        </span>
      </button>
    );
  }

  // Desktop closed: edge-triggered reveal
  return (
    <>
      {/* Invisible trigger zone - full height */}
      <div
        className="fixed left-0 top-0 h-full z-20"
        style={{ width: `${EDGE_WIDTH}px` }}
      />

      {/* Chevron - revealed after delay, stable position */}
      <button
        onClick={toggleSidebar}
        className={`fixed left-0 top-1/2 -translate-y-1/2 z-20
          w-8 h-20 flex items-center justify-center
          bg-background/70 backdrop-blur-md
          border-y border-r border-border rounded-r-xl
          shadow-lg hover:bg-muted/80
          transition-all duration-200 ease-out
          focus:outline-none focus-visible:ring-2 focus-visible:ring-ring
          ${revealed ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-4 pointer-events-none'}`}
        aria-label="Open sidebar"
      >
        <span className="text-muted-foreground text-2xl font-extralight">
          ‹
        </span>
      </button>
    </>
  );
}
