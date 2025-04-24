import { Button } from "@/components/ui/button.tsx";
import { Settings } from "lucide-react";

const Navbar = () => {
  return (
    <div className="flex flex-row fixed right-0 top-0 h-fit m-2 p-3 rounded-xl backdrop-blur-lg space-x-6">
      <h1 className="text-3xl">yapit</h1>
      <Button><Settings /></Button>
    </div>
  )
}

export { Navbar }
