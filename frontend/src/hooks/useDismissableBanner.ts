import { useEffect, useRef, useState } from "react";

export function useDismissableBanner(resetDep: unknown): [boolean, (dismissed: boolean) => void] {
  const [dismissed, setDismissed] = useState(false);
  const prevRef = useRef(resetDep);

  useEffect(() => {
    if (resetDep !== prevRef.current) {
      setDismissed(false);
    }
    prevRef.current = resetDep;
  }, [resetDep]);

  return [dismissed, setDismissed];
}
