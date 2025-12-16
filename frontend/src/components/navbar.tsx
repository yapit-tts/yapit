import { Button } from "@/components/ui/button.tsx";
import { Settings, LogIn, LogOut } from "lucide-react";
import { useUser } from "@stackframe/react";
import { useNavigate } from "react-router";

const Navbar = () => {
  const user = useUser();
  const navigate = useNavigate();

  const handleAuth = () => {
    if (user) {
      user.signOut();
    } else {
      navigate("/handler/signin");
    }
  };

  return (
    <div className="flex flex-row fixed right-0 top-0 h-fit m-2 p-3 rounded-xl backdrop-blur-lg space-x-4 items-center">
      <h1 className="text-3xl">yapit</h1>
      <Button variant="outline" size="sm" onClick={handleAuth}>
        {user ? <LogOut className="h-4 w-4" /> : <LogIn className="h-4 w-4" />}
        <span className="ml-2">{user ? "Logout" : "Login"}</span>
      </Button>
      <Button variant="secondary" size="icon"><Settings className="h-4 w-4" /></Button>
    </div>
  )
}

export { Navbar }
