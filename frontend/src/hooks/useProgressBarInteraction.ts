import { useCallback, useRef, useState, type RefObject } from "react";

const DRAG_THRESHOLD = 5;

interface UseProgressBarInteractionParams {
  numBlocks: number;
  onBlockClick: (idx: number) => void;
  onBlockHover?: (idx: number | null, isDragging: boolean) => void;
  visualToAbsolute?: (visualIdx: number) => number;
}

export function useProgressBarInteraction({
  numBlocks,
  onBlockClick,
  onBlockHover,
  visualToAbsolute,
}: UseProgressBarInteractionParams) {
  const barRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [seekPosition, setSeekPosition] = useState<number | null>(null);
  const dragStartXRef = useRef<number | null>(null);
  const lastHoverBlockRef = useRef<number | null>(null);

  const getBlockFromX = useCallback((clientX: number) => {
    if (!barRef.current) return 0;
    const rect = barRef.current.getBoundingClientRect();
    const x = clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    return Math.min(numBlocks - 1, Math.floor(pct * numBlocks));
  }, [numBlocks]);

  const toAbsolute = (visualIdx: number) =>
    visualToAbsolute ? visualToAbsolute(visualIdx) : visualIdx;

  const handleStart = (clientX: number) => {
    dragStartXRef.current = clientX;
  };

  const handleMove = (clientX: number) => {
    const visualIdx = getBlockFromX(clientX);

    let currentlyDragging = isDragging;
    if (dragStartXRef.current !== null && !isDragging) {
      if (Math.abs(clientX - dragStartXRef.current) > DRAG_THRESHOLD) {
        setIsDragging(true);
        currentlyDragging = true;
      }
    }

    setSeekPosition(visualIdx);
    onBlockHover?.(toAbsolute(visualIdx), currentlyDragging);
  };

  const handleEnd = (clientX: number) => {
    const visualIdx = getBlockFromX(clientX);
    onBlockClick(toAbsolute(visualIdx));
    setIsDragging(false);
    setSeekPosition(null);
    dragStartXRef.current = null;
    onBlockHover?.(null, false);
  };

  const handleCancel = () => {
    setIsDragging(false);
    setSeekPosition(null);
    dragStartXRef.current = null;
    onBlockHover?.(null, false);
  };

  const getClientX = (e: React.TouchEvent): number =>
    e.touches[0]?.clientX ?? e.changedTouches[0]?.clientX ?? 0;

  const handlers = {
    onMouseDown: (e: React.MouseEvent) => {
      e.preventDefault();
      handleStart(e.clientX);
    },
    onMouseMove: (e: React.MouseEvent) => {
      if (dragStartXRef.current !== null) {
        handleMove(e.clientX);
      } else {
        const visualIdx = getBlockFromX(e.clientX);
        if (visualIdx !== lastHoverBlockRef.current) {
          lastHoverBlockRef.current = visualIdx;
          setSeekPosition(visualIdx);
          onBlockHover?.(toAbsolute(visualIdx), false);
        }
      }
    },
    onMouseUp: (e: React.MouseEvent) => {
      handleEnd(e.clientX);
    },
    onMouseLeave: () => {
      lastHoverBlockRef.current = null;
      handleCancel();
    },
    onTouchStart: (e: React.TouchEvent) => {
      e.preventDefault();
      handleStart(getClientX(e));
    },
    onTouchMove: (e: React.TouchEvent) => {
      e.preventDefault();
      handleMove(getClientX(e));
    },
    onTouchEnd: (e: React.TouchEvent) => {
      handleEnd(getClientX(e));
    },
    onTouchCancel: handleCancel,
  };

  return { barRef: barRef as RefObject<HTMLDivElement>, seekPosition, isDragging, handlers };
}
