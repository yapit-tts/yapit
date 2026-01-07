import { useNavigate } from "react-router";
import { AccountSettings } from "@stackframe/react";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

const AccountSettingsPage = () => {
  const navigate = useNavigate();

  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate("/account")}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back to Account
      </Button>

      <AccountSettings />
    </div>
  );
};

export default AccountSettingsPage;
