import { SidebarProvider } from "@/components/ui/sidebar"
import { DocumentSidebar } from "@/components/documentSidebar"
import { SidebarEdgeTrigger } from "@/components/sidebarEdgeTrigger"

const SidebarLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <SidebarProvider>
      <DocumentSidebar />
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <SidebarEdgeTrigger />
        {children}
      </main>
    </SidebarProvider>
  )
}

export default SidebarLayout;
