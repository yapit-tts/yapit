import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar"
import { DocumentSidebar } from "@/components/documentSidebar"

const SidebarLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <SidebarProvider>
      <DocumentSidebar />
      <main className="w-full">
        <SidebarTrigger className="fixed backdrop-blur-lg" />
        {children}
      </main>
    </SidebarProvider>
  )
}

export default SidebarLayout;
