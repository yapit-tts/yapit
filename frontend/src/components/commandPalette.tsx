import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router";
import {
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandShortcut,
} from "@/components/ui/command";
import { FileText, Plus, Settings, Lightbulb, CreditCard, Info } from "lucide-react";
import { useDocuments } from "@/hooks/useDocuments";
import { useIsMobile } from "@/hooks/use-mobile";

const NAV_ITEMS = [
  { label: "New Document", path: "/", icon: Plus },
  { label: "Account", path: "/account", icon: Settings },
  { label: "Tips", path: "/tips", icon: Lightbulb },
  { label: "Pricing", path: "/pricing", icon: CreditCard },
  { label: "About", path: "/about", icon: Info },
] as const;

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const { documents } = useDocuments();
  const navigate = useNavigate();
  const location = useLocation();
  const isMobile = useIsMobile();

  useEffect(() => {
    if (isMobile) return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isMobile]);

  const go = (path: string) => {
    setOpen(false);
    if (location.pathname === path && path === "/") {
      window.dispatchEvent(new CustomEvent("reset-input"));
    } else {
      navigate(path);
    }
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title="Search"
      description="Search documents and navigation"
      showCloseButton={false}
    >
      <CommandInput placeholder="Search documents..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        <CommandGroup heading="Documents">
          {documents.map((doc) => (
            <CommandItem key={doc.id} value={doc.id} keywords={[doc.title || "Untitled"]} onSelect={() => go(`/listen/${doc.id}`)}>
              <FileText />
              <span className="truncate">{doc.title || "Untitled"}</span>
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Navigation">
          {NAV_ITEMS.map(({ label, path, icon: Icon }) => (
            <CommandItem key={path} value={label} onSelect={() => go(path)}>
              <Icon />
              {label}
              {label === "New Document" && <CommandShortcut>Home</CommandShortcut>}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
