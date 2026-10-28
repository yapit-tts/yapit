import { Link } from "react-router";
import { Header } from "@/components/header";
import { UnifiedInput } from "@/components/unifiedInput";
import { GettingStarted } from "@/components/gettingStarted";
import { useAuth } from "@/hooks/useAuthUser";

const TextInputPage = () => {
  const { authEnabled } = useAuth();
  return (
    <div className="flex flex-col w-full px-4 min-h-[100dvh]">
      <Header />
      <UnifiedInput />
      <div className="w-full max-w-2xl mx-auto">
        <GettingStarted />
      </div>
      {authEnabled && (
        <Link
          to="/about#imprint"
          className="mt-auto block text-center py-6 text-sm text-muted-foreground/60 hover:text-foreground transition-colors"
        >
          Imprint
        </Link>
      )}
    </div>
  );
};

export default TextInputPage;
