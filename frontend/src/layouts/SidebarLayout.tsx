import { SidebarProvider } from "@/components/ui/sidebar"
import { DocumentSidebar } from "@/components/documentSidebar"
import { SidebarEdgeTrigger } from "@/components/sidebarEdgeTrigger"
import { OutlinerProvider } from "@/hooks/useOutliner"
import { OutlinerEdgeTrigger } from "@/components/outlinerEdgeTrigger"

const SidebarLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <SidebarProvider>
      <OutlinerProvider>
        <DocumentSidebar />
        <main className="flex-1 min-w-0 overflow-x-hidden">
          <SidebarEdgeTrigger />
          {children}
          <OutlinerEdgeTrigger />
        </main>
        {/* OutlinerSidebar rendered by PlaybackPage when document has sections */}
      </OutlinerProvider>
    </SidebarProvider>
  )
}

export default SidebarLayout;
