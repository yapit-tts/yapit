import * as TooltipPrimitive from "@radix-ui/react-tooltip";

/** The house overlay: the page's own ground, a hairline, no shadow. */
export const overlayClass = "z-50 max-w-72 rounded-md border bg-background px-3 py-2 text-sm text-foreground data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=instant-open]:animate-in data-[state=instant-open]:fade-in-0 data-[state=open]:animate-in data-[state=open]:fade-in-0";

interface HintProps {
  content: React.ReactNode;
  children: React.ReactNode;
  align?: "start" | "center" | "end";
}

/**
 * The house tooltip: an overlay that opens below the element it wraps after half a second of hover, and at once on
 * keyboard focus. That element is the trigger itself, so a disabled button needs a span around it, which still gets
 * the pointer. Focus that is not keyboard focus (a dialog focusing its first control after a click) leaves it shut.
 */
export function Hint({ content, children, align = "center" }: HintProps) {
  return (
    <TooltipPrimitive.Provider delayDuration={500}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild onFocus={skipUnlessKeyboardFocus}>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content align={align} sideOffset={6} collisionPadding={8} className={`${overlayClass} flex flex-col gap-1.5`}>
            {content}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

function skipUnlessKeyboardFocus(e: React.FocusEvent) {
  if (!(e.target as HTMLElement).matches(":focus-visible")) e.preventDefault();
}

/** A tooltip's line naming an action, with its key at the right in a mono chip, as the shortcuts dialog shows keys. */
export function ActionLine({ action, keys }: { action: React.ReactNode; keys: string }) {
  return (
    <span className="flex items-center justify-between gap-4">
      <span className="font-medium">{action}</span>
      <kbd className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{keys}</kbd>
    </span>
  );
}
