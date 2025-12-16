import { Button } from "@/components/ui/button.tsx";
import { Settings } from "lucide-react";

const Navbar = () => {
  return (
    <div className="flex flex-row fixed right-0 top-0 h-fit m-2 p-3 rounded-xl backdrop-blur-lg">
      <Button variant="ghost" size="icon">
        <Settings className="h-4 w-4" />
      </Button>
    </div>
  )
}

export { Navbar }
