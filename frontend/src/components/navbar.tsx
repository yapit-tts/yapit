import { SettingsDialog } from "@/components/settingsDialog";

const Navbar = () => {
  return (
    <div className="flex flex-row fixed right-0 top-0 h-fit m-2 p-3 rounded-xl backdrop-blur-lg">
      <SettingsDialog />
    </div>
  );
};

export { Navbar };
