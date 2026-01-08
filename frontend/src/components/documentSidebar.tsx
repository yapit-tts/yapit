import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useLocation } from "react-router";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuAction,
  SidebarGroupAction,
  SidebarHeader,
  SidebarFooter,
} from "@/components/ui/sidebar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { ChevronUp, FileText, Plus, Loader2, MoreHorizontal, User2, LogOut, LogIn, Trash2, Pencil, CreditCard, Lightbulb, Settings, Info } from "lucide-react";
import { useApi } from "@/api";
import { useUser } from "@stackframe/react";
import { useIsMobile } from "@/hooks/use-mobile";

const CHARS_PER_HOUR = 61200;

interface DocumentItem {
  id: string;
  title: string | null;
  created: string;
}

interface SubscriptionSummary {
  plan: { tier: string; name: string };
  subscription: { status: string } | null;
  limits: { premium_voice_characters: number | null; ocr_pages: number | null };
  usage: { premium_voice_characters: number; ocr_pages: number };
}

function DocumentSidebar() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [renameDoc, setRenameDoc] = useState<DocumentItem | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionSummary | null>(null);
  const { api, isAuthReady, isAnonymous } = useApi();
  const navigate = useNavigate();
  const { documentId } = useParams();
  const location = useLocation();
  const user = useUser();
  const isMobile = useIsMobile();

  useEffect(() => {
    if (!isAuthReady) return;

    const fetchDocuments = async () => {
      try {
        const response = await api.get<DocumentItem[]>("/v1/documents");
        setDocuments(response.data);
      } catch (error) {
        console.error("Failed to fetch documents:", error);
      } finally {
        setIsLoading(false);
      }
    };

    const fetchSubscription = async () => {
      if (isAnonymous) return;
      try {
        const response = await api.get<SubscriptionSummary>("/v1/users/me/subscription");
        setSubscription(response.data);
      } catch {
        // Subscription not available
      }
    };

    fetchDocuments();
    fetchSubscription();
  }, [api, isAuthReady, isAnonymous, user, location.pathname]);

  // Listen for title changes from PlaybackPage
  useEffect(() => {
    const handleTitleChanged = (e: Event) => {
      const { documentId: docId, title } = (e as CustomEvent).detail;
      setDocuments(prev => prev.map(d => d.id === docId ? { ...d, title } : d));
    };
    window.addEventListener('document-title-changed', handleTitleChanged);
    return () => window.removeEventListener('document-title-changed', handleTitleChanged);
  }, []);

  const handleDeleteDocument = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation();
    try {
      await api.delete(`/v1/documents/${docId}`);
      setDocuments(prev => prev.filter(d => d.id !== docId));
      if (documentId === docId) {
        navigate("/");
      }
    } catch (error) {
      console.error("Failed to delete document:", error);
    }
  };

  const openRenameDialog = (e: React.MouseEvent, doc: DocumentItem) => {
    e.stopPropagation();
    setOpenMenuId(null); // Close dropdown before opening dialog
    setRenameDoc(doc);
    setNewTitle(doc.title || "");
  };

  const handleRenameDocument = async () => {
    if (!renameDoc) return;
    try {
      await api.patch(`/v1/documents/${renameDoc.id}`, { title: newTitle || null });
      setDocuments(prev =>
        prev.map(d => (d.id === renameDoc.id ? { ...d, title: newTitle || null } : d))
      );
      setRenameDoc(null);
    } catch (error) {
      console.error("Failed to rename document:", error);
      alert("Failed to rename document");
    }
  };

  const handleAuth = () => {
    if (user) {
      user.signOut();
    } else {
      navigate("/handler/signin");
    }
  };

  return (
    <Sidebar>
      <SidebarHeader className="border-b border-sidebar-border">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg">
              <Link to="/">
                <img src="/favicon.svg" alt="Yapit" className="size-10" />
                <div className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold text-lg">yapit</span>
                  <span className="text-sm text-muted-foreground">text to speech</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Documents</SidebarGroupLabel>
          {location.pathname !== "/" && (
            <SidebarGroupAction title="Add Document" asChild>
              <Link to="/">
                <Plus /> <span className="sr-only">Add Document</span>
              </Link>
            </SidebarGroupAction>
          )}
          <SidebarGroupContent>
            <SidebarMenu>
              {isLoading ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              ) : documents.length === 0 ? (
                <div className="px-3 py-4 text-sm text-muted-foreground">
                  No documents yet
                </div>
              ) : (
                documents.map((doc) => (
                  <SidebarMenuItem key={doc.id}>
                    <SidebarMenuButton
                      asChild
                      isActive={documentId === doc.id}
                      size="lg"
                    >
                      <Link to={`/listen/${doc.id}`} state={{ documentTitle: doc.title }}>
                        <FileText className="shrink-0" />
                        <span className="truncate" title={doc.title || "Untitled"}>
                          {doc.title || "Untitled"}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                    <DropdownMenu
                      open={openMenuId === doc.id}
                      onOpenChange={(open) => setOpenMenuId(open ? doc.id : null)}
                    >
                      <DropdownMenuTrigger asChild>
                        <SidebarMenuAction>
                          <MoreHorizontal />
                          <span className="sr-only">Actions</span>
                        </SidebarMenuAction>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent side="right" align="start">
                        <DropdownMenuItem onClick={(e) => openRenameDialog(e, doc)}>
                          <Pencil className="mr-2 h-4 w-4" />
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={(e) => handleDeleteDocument(e, doc.id)}
                          className="text-destructive focus:text-destructive"
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </SidebarMenuItem>
                ))
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border">
        <SidebarMenu>
          {/* Subscription / Plan button */}
          <SidebarMenuItem>
            <Tooltip>
              <TooltipTrigger asChild>
                <SidebarMenuButton asChild size="lg" className="h-auto py-3">
                  <Link to="/subscription">
                    <div className="flex flex-col w-full gap-1">
                      <div className="flex items-center gap-2">
                        <CreditCard className="h-4 w-4 text-primary shrink-0" />
                        <span className="truncate font-medium">
                          {subscription?.plan.name ?? "Free"} Plan
                        </span>
                      </div>
                      {subscription?.subscription && subscription.limits.premium_voice_characters !== null && subscription.limits.premium_voice_characters > 0 && (() => {
                        const usagePct = (subscription.usage.premium_voice_characters / subscription.limits.premium_voice_characters) * 100;
                        const isNearLimit = usagePct >= 95;
                        return (
                          <div className="w-full pl-6">
                            <Progress
                              value={Math.min(100, usagePct)}
                              className="h-1.5"
                              indicatorClassName={isNearLimit ? "bg-[oklch(0.7_0.12_70)]" : undefined}
                            />
                          </div>
                        );
                      })()}
                    </div>
                  </Link>
                </SidebarMenuButton>
              </TooltipTrigger>
              <TooltipContent side="right" hidden={isMobile}>
                {subscription?.subscription ? (
                  <div className="space-y-1">
                    {subscription.limits.premium_voice_characters !== null && subscription.limits.premium_voice_characters > 0 && (
                      <p>Premium Voice: ~{Math.round(subscription.usage.premium_voice_characters / CHARS_PER_HOUR)} / ~{Math.round(subscription.limits.premium_voice_characters / CHARS_PER_HOUR)} hrs</p>
                    )}
                    {subscription.limits.ocr_pages !== null && subscription.limits.ocr_pages > 0 && (
                      <p>OCR: {subscription.usage.ocr_pages} / {subscription.limits.ocr_pages} pages</p>
                    )}
                  </div>
                ) : (
                  <p>Click to view plans</p>
                )}
              </TooltipContent>
            </Tooltip>
          </SidebarMenuItem>

          {/* Tips button */}
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg">
              <Link to="/tips">
                <Lightbulb className="h-4 w-4 text-muted-foreground" />
                <span>Tips</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>

          {/* User button */}
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg">
                  <User2 />
                  <span className="truncate">
                    {user?.displayName || user?.primaryEmail || "Guest"}
                  </span>
                  <ChevronUp className="ml-auto" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                side="top"
                className="min-w-[var(--radix-popper-anchor-width)]"
              >
                {user && (
                  <DropdownMenuItem onClick={() => navigate("/account")}>
                    <Settings className="mr-2 h-4 w-4" />
                    Account
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => navigate("/about")}>
                  <Info className="mr-2 h-4 w-4" />
                  About
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleAuth}
                  className={user ? "hover:bg-muted-warm focus:bg-muted-warm" : ""}
                >
                  {user ? (
                    <>
                      <LogOut className="mr-2 h-4 w-4" />
                      Sign out
                    </>
                  ) : (
                    <>
                      <LogIn className="mr-2 h-4 w-4" />
                      Sign in
                    </>
                  )}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <Dialog open={renameDoc !== null} onOpenChange={(open) => !open && setRenameDoc(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Document</DialogTitle>
          </DialogHeader>
          <Input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Document title"
            maxLength={500}
            onKeyDown={(e) => e.key === "Enter" && handleRenameDocument()}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameDoc(null)}>
              Cancel
            </Button>
            <Button onClick={handleRenameDocument}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sidebar>
  );
}

export { DocumentSidebar };
