import * as React from "react";
import { useIsMobile } from "@/hooks/use-mobile";
import { useSidebar } from "@/components/ui/sidebar";

const OUTLINER_COOKIE_NAME = "outliner_state";
const OUTLINER_COOKIE_MAX_AGE = 60 * 60 * 24 * 7; // 7 days

function getOutlinerCookieValue(): boolean | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`${OUTLINER_COOKIE_NAME}=([^;]+)`)
  );
  return match ? match[1] === "true" : null;
}

type OutlinerContextProps = {
  state: "expanded" | "collapsed";
  open: boolean;
  setOpen: (open: boolean) => void;
  openMobile: boolean;
  setOpenMobile: (open: boolean) => void;
  isMobile: boolean;
  toggleOutliner: () => void;
  // Whether outliner should be shown (set by PlaybackPage when document has sections)
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
};

const OutlinerContext = React.createContext<OutlinerContextProps | null>(null);

export function useOutliner() {
  const context = React.useContext(OutlinerContext);
  if (!context) {
    throw new Error("useOutliner must be used within an OutlinerProvider.");
  }
  return context;
}

// Optional hook that returns null instead of throwing if used outside provider
export function useOutlinerOptional() {
  return React.useContext(OutlinerContext);
}

export function OutlinerProvider({
  defaultOpen = false,
  children,
}: {
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const isMobile = useIsMobile();
  const leftSidebar = useSidebar();

  const [openMobile, setOpenMobileInternal] = React.useState(false);
  const [_open, _setOpen] = React.useState(
    () => getOutlinerCookieValue() ?? defaultOpen
  );
  const [enabled, setEnabled] = React.useState(false);

  // Mobile mutex: when outliner opens, close left sidebar
  const setOpenMobile = React.useCallback(
    (open: boolean) => {
      if (open && isMobile) {
        leftSidebar.setOpenMobile(false);
      }
      setOpenMobileInternal(open);
    },
    [isMobile, leftSidebar]
  );

  const setOpen = React.useCallback((value: boolean) => {
    _setOpen(value);
  }, []);

  // Persist state to cookie
  const isInitialMount = React.useRef(true);
  React.useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    document.cookie = `${OUTLINER_COOKIE_NAME}=${_open}; path=/; max-age=${OUTLINER_COOKIE_MAX_AGE}`;
  }, [_open]);

  const toggleOutliner = React.useCallback(() => {
    if (isMobile) {
      setOpenMobile(!openMobile);
    } else {
      setOpen(!_open);
    }
  }, [isMobile, openMobile, _open, setOpen, setOpenMobile]);

  // Mobile mutex reverse: when left sidebar opens, close outliner
  React.useEffect(() => {
    if (isMobile && leftSidebar.openMobile && openMobile) {
      setOpenMobileInternal(false);
    }
  }, [isMobile, leftSidebar.openMobile, openMobile]);

  const state = _open ? "expanded" : "collapsed";

  const contextValue = React.useMemo<OutlinerContextProps>(
    () => ({
      state,
      open: _open,
      setOpen,
      openMobile,
      setOpenMobile,
      isMobile,
      toggleOutliner,
      enabled,
      setEnabled,
    }),
    [state, _open, setOpen, openMobile, setOpenMobile, isMobile, toggleOutliner, enabled]
  );

  return (
    <OutlinerContext.Provider value={contextValue}>
      {children}
    </OutlinerContext.Provider>
  );
}
