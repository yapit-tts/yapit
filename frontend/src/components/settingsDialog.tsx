import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { Settings } from "lucide-react";
import { useSettings } from "@/hooks/useSettings";

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0">
      <div className="flex flex-col gap-0.5">
        <Label className="text-sm font-medium">{label}</Label>
        {description && (
          <span className="text-xs text-muted-foreground">{description}</span>
        )}
      </div>
      {children}
    </div>
  );
}

interface SettingsDialogProps {
  size?: "default" | "lg";
}

export function SettingsDialog({ size = "default" }: SettingsDialogProps) {
  const { settings, setSettings } = useSettings();

  const buttonClass = size === "lg" ? "h-10 w-10" : "";
  const iconClass = size === "lg" ? "h-5 w-5" : "h-4 w-4";

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon" className={buttonClass}>
          <Settings className={iconClass} />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col">
          <SettingRow
            label="Scroll on restore"
            description="Scroll to saved position when opening a document"
          >
            <Switch
              checked={settings.scrollOnRestore}
              onCheckedChange={(checked) =>
                setSettings({ scrollOnRestore: checked })
              }
            />
          </SettingRow>

          <SettingRow
            label="Live scroll tracking"
            description="Keep current block centered during playback"
          >
            <Switch
              checked={settings.liveScrollTracking}
              onCheckedChange={(checked) =>
                setSettings({ liveScrollTracking: checked })
              }
            />
          </SettingRow>

          <SettingRow
            label="Default playback speed"
            description={`${settings.defaultSpeed.toFixed(1)}x`}
          >
            <Slider
              className="w-24"
              value={[settings.defaultSpeed]}
              onValueChange={([value]) => setSettings({ defaultSpeed: value })}
              min={0.5}
              max={3}
              step={0.1}
            />
          </SettingRow>
        </div>
      </DialogContent>
    </Dialog>
  );
}
