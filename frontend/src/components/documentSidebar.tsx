import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarGroupAction,
  SidebarFooter,
} from "@/components/ui/sidebar";
import { ChevronUp, FileText, Plus, Loader2 } from "lucide-react";
import { useApi } from "@/api";

interface DocumentItem {
  id: string;
  title: string | null;
  created: string;
}

function DocumentSidebar() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const { api } = useApi();
  const navigate = useNavigate();

  useEffect(() => {
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
  }, [api]);

  const handleDocumentClick = (doc: DocumentItem) => {
    navigate("/playback", {
      state: { apiResponse: { id: doc.id, title: doc.title } },
    });
  };

  return (
    <Sidebar>
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
                    <SidebarMenuButton onClick={() => handleDocumentClick(doc)}>
                      <FileText className="shrink-0" />
                      <span className="truncate">
                        {doc.title || "Untitled"}
                      </span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenuButton>
          dev
          <ChevronUp className="ml-auto" />
        </SidebarMenuButton>
      </SidebarFooter>
    </Sidebar>
  );
}

export { DocumentSidebar };
