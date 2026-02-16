import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Settings, Sun, Moon, Monitor } from "lucide-react";
import { useSettings, type ContentWidth, type ScrollPosition, type Theme } from "@/hooks/useSettings";
import { cn } from "@/lib/utils";
import { useUserPreferences } from "@/hooks/useUserPreferences";
import { useApi } from "@/api";
import { useIsMobile } from "@/hooks/use-mobile";

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
  const isMobile = useIsMobile();
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
            label="Appearance"
            description="Light, dark, or match your system"
          >
            <div className="flex gap-1">
              {([
                { value: "light" as Theme, icon: Sun, label: "Light" },
                { value: "dark" as Theme, icon: Moon, label: "Dark" },
                { value: "system" as Theme, icon: Monitor, label: "System" },
              ]).map(({ value, icon: Icon, label }) => (
                <button
                  key={value}
                  onClick={() => setSettings({ theme: value })}
                  className={cn(
                    "px-2 py-1 text-xs rounded transition-colors flex items-center gap-1",
                    settings.theme === value
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted hover:bg-muted/80 text-muted-foreground"
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>
          </SettingRow>

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

          {!isMobile && (
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
          )}

          <SettingRow
            label="Scroll position"
            description="Where the current block appears on screen"
          >
            <div className="flex gap-1">
              {(["top", "center", "bottom"] as ScrollPosition[]).map((pos) => (
                <button
                  key={pos}
                  onClick={() => setSettings({ scrollPosition: pos })}
                  className={cn(
                    "px-2 py-1 text-xs rounded transition-colors capitalize",
                    settings.scrollPosition === pos
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted hover:bg-muted/80 text-muted-foreground"
                  )}
                >
                  {pos}
                </button>
              ))}
            </div>
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
