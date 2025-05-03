import { Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarGroupAction, } from "@/components/ui/sidebar"
import { FileText, Plus } from "lucide-react"

const documents = [
	{
		title: "Attention Is All You Need",
		url: "#",
		icon: FileText,
	},
	{
		title: "Omniscient Reader's Viewpoint",
		url: "#",
		icon: FileText,
	},
	{
		title: "The Complete Sherlock Holmes Collection",
		url: "#",
		icon: FileText,
	},
]

const DocumentSidebar = () => {
	return (
		<Sidebar>
      <SidebarContent>
        <SidebarGroup>
					<SidebarGroupLabel>Documents</SidebarGroupLabel>
					<SidebarGroupAction title="Add Document">
						<Plus /> <span className="sr-only">Add Document</span>
					</SidebarGroupAction>
					<SidebarGroupContent>
						<SidebarMenu>
							{documents.map((doc) => (
								<SidebarMenuItem key={doc.title}>
									<SidebarMenuButton asChild>
										<a href={doc.url}>
											<doc.icon />
											<span>{doc.title}</span>
										</a>
									</SidebarMenuButton>
								</SidebarMenuItem>
							))}
						</SidebarMenu>
					</SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
	)
}

export { DocumentSidebar }
