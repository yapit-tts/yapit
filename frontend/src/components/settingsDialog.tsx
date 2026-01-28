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
import { useSettings, type ContentWidth } from "@/hooks/useSettings";
import { cn } from "@/lib/utils";
import { useUserPreferences } from "@/hooks/useUserPreferences";
import { useApi } from "@/api";

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
  const { isAnonymous } = useApi();
  const {
    autoImportSharedDocuments,
    setAutoImportSharedDocuments,
    defaultDocumentsPublic,
    setDefaultDocumentsPublic,
  } = useUserPreferences();

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
            label="Content width"
            description="Maximum width of document text"
          >
            <div className="flex gap-1">
              {(["narrow", "medium", "wide", "full"] as ContentWidth[]).map((width) => (
                <button
                  key={width}
                  onClick={() => setSettings({ contentWidth: width })}
                  className={cn(
                    "px-2 py-1 text-xs rounded transition-colors capitalize",
                    settings.contentWidth === width
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted hover:bg-muted/80 text-muted-foreground"
                  )}
                >
                  {width}
                </button>
              ))}
            </div>
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

          {/* Sharing settings - only for signed-in users */}
          {!isAnonymous && (
            <>
              <div className="mt-4 mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Sharing
              </div>

              <SettingRow
                label="Auto-import shared documents"
                description="Add to library automatically when opening"
              >
                <Switch
                  checked={autoImportSharedDocuments}
                  onCheckedChange={setAutoImportSharedDocuments}
                />
              </SettingRow>

              <SettingRow
                label="New documents shareable"
                description="Make new documents shareable by default"
              >
                <Switch
                  checked={defaultDocumentsPublic}
                  onCheckedChange={setDefaultDocumentsPublic}
                />
              </SettingRow>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
