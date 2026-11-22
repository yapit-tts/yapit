import * as TooltipPrimitive from "@radix-ui/react-tooltip";

/** The house overlay: the page's own ground, a hairline, no shadow. */
const overlayClass = "z-50 max-w-72 rounded-md border bg-background px-3 py-2 text-sm text-foreground data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=instant-open]:animate-in data-[state=instant-open]:fade-in-0 data-[state=open]:animate-in data-[state=open]:fade-in-0";

interface HintProps {
  content: React.ReactNode;
  children: React.ReactNode;
  align?: "start" | "center" | "end";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * The house tooltip: an overlay under its control after half a second of hover, and at once on keyboard focus. The
 * trigger is the child itself, so a wrapper around a disabled button still opens it. Focus that is not keyboard focus
 * (a dialog focusing its first control after a click) leaves it shut.
 */
export function Hint({ content, children, align = "center", open, onOpenChange }: HintProps) {
  return (
    <TooltipPrimitive.Provider delayDuration={500}>
      <TooltipPrimitive.Root open={open} onOpenChange={onOpenChange}>
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
