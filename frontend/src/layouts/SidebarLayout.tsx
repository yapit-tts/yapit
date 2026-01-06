import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { DocumentSidebar } from "@/components/documentSidebar"

const SidebarLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <SidebarProvider>
      <DocumentSidebar />
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <SidebarTrigger className="fixed backdrop-blur-lg" />
        {children}
      </main>
    </SidebarProvider>
  )
}

export default SidebarLayout;
