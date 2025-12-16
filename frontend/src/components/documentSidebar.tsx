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
import { ChevronUp, FileText, Plus, Loader2, MoreHorizontal, User2, LogOut, LogIn, Trash2, Pencil, Settings } from "lucide-react";
import { useApi } from "@/api";
import { useUser } from "@stackframe/react";

interface DocumentItem {
  id: string;
  title: string | null;
  created: string;
}

function DocumentSidebar() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [renameDoc, setRenameDoc] = useState<DocumentItem | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const { api, isAuthReady } = useApi();
  const navigate = useNavigate();
  const { documentId } = useParams();
  const location = useLocation();
  const user = useUser();

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

    fetchDocuments();
  }, [api, isAuthReady, user, location.pathname]);

  const handleDocumentClick = (doc: DocumentItem) => {
    navigate(`/playback/${doc.id}`, {
      state: { documentTitle: doc.title },
    });
  };

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
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-semibold">
                  Y
                </div>
                <div className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold">yapit</span>
                  <span className="text-xs text-muted-foreground">text to speech</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Documents</SidebarGroupLabel>
          <SidebarGroupAction title="Add Document" asChild>
            <Link to="/">
              <Plus /> <span className="sr-only">Add Document</span>
            </Link>
          </SidebarGroupAction>
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
                      onClick={() => handleDocumentClick(doc)}
                      isActive={documentId === doc.id}
                    >
                      <FileText className="shrink-0" />
                      <span className="truncate">
                        {doc.title || "Untitled"}
                      </span>
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
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton>
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
                <DropdownMenuItem>
                  <Settings className="mr-2 h-4 w-4" />
                  Settings
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleAuth}>
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
