import { Header } from "@/components/header";
import { UnifiedInput } from "@/components/unifiedInput";
import { GettingStarted } from "@/components/gettingStarted";

const TextInputPage = () => {
  return (
    <div className="flex flex-col justify-center w-full px-4">
      <Header />
      <UnifiedInput />
      <div className="w-full max-w-2xl mx-auto">
        <GettingStarted />
      </div>
    </div>
  );
};

export default TextInputPage;
