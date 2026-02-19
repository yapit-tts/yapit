import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useUser } from "@stackframe/react";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Loader2, ArrowLeft, Trash2, AlertTriangle, Calendar, Sun, Moon, Monitor, Settings } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { SettingRow, darkThemes } from "@/components/settingsDialog";
import { useSettings, useIsDark, type ContentWidth, type ScrollPosition, type Theme } from "@/hooks/useSettings";
import { useUserPreferences } from "@/hooks/useUserPreferences";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

// LOTR trilogy stats for comparisons (Rob Inglis unabridged, trilogy only)
const LOTR_TRILOGY_MS = 194_400_000; // ~54 hours

interface VoiceEngagement {
  voice_slug: string;
  voice_name: string | null;
  model_slug: string;
  total_duration_ms: number;
  total_characters: number;
  synth_count: number;
}

interface EngagementStats {
  total_duration_ms: number;
  total_characters: number;
  total_synths: number;
  document_count: number;
  voices: VoiceEngagement[];
}

const AccountPage = () => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const navigate = useNavigate();
  const user = useUser();
  const { settings, setSettings } = useSettings();
  const isDark = useIsDark();
  const isMobile = useIsMobile();
  const {
    autoImportSharedDocuments,
    setAutoImportSharedDocuments,
    defaultDocumentsPublic,
    setDefaultDocumentsPublic,
  } = useUserPreferences();

  const [engagement, setEngagement] = useState<EngagementStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);
  const [bulkDeleteDays, setBulkDeleteDays] = useState<number | null>(null);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [bulkDeleteDropdownOpen, setBulkDeleteDropdownOpen] = useState(false);

  useEffect(() => {
    if (!isAuthReady) return;
    if (isAnonymous) {
      setIsLoading(false);
      return;
    }

    api.get<EngagementStats>("/v1/users/me/engagement")
      .then((r) => setEngagement(r.data))
      .catch((e) => console.error("Failed to fetch engagement stats:", e))
      .finally(() => setIsLoading(false));
  }, [api, isAuthReady, isAnonymous]);

  // Group voices by model for display
  const voicesByModel = useMemo(() => {
    if (!engagement?.voices.length) return new Map<string, VoiceEngagement[]>();
    const grouped = new Map<string, VoiceEngagement[]>();
    for (const v of engagement.voices) {
      const existing = grouped.get(v.model_slug) ?? [];
      existing.push(v);
      grouped.set(v.model_slug, existing);
    }
    return grouped;
  }, [engagement?.voices]);

  const handleDeleteAccount = async () => {
    setIsDeleting(true);
    try {
      await api.delete("/v1/users/me");
      window.location.href = "/";
    } catch (error) {
      console.error("Failed to delete account:", error);
      setIsDeleting(false);
    }
  };

  const handleBulkDelete = async () => {
    setIsBulkDeleting(true);
    try {
      const params = bulkDeleteDays ? `?older_than_days=${bulkDeleteDays}` : "";
      await api.delete<{ deleted_count: number }>(`/v1/documents/bulk${params}`);
      const r = await api.get<EngagementStats>("/v1/users/me/engagement");
      setEngagement(r.data);
      setBulkDeleteDialogOpen(false);
      setBulkDeleteDays(null);
    } catch (error) {
      console.error("Failed to delete documents:", error);
    } finally {
      setIsBulkDeleting(false);
    }
  };

  const openBulkDeleteDialog = (days: number | null) => {
    setBulkDeleteDropdownOpen(false);
    setBulkDeleteDays(days);
    setBulkDeleteDialogOpen(true);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isAnonymous) {
    return (
      <div className="container max-w-4xl mx-auto py-8 px-6">
        <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
          <ArrowLeft className="mr-2 h-5 w-5" />
          Back
        </Button>

        <h1 className="text-4xl font-bold mb-2">Account</h1>
        <p className="text-lg text-muted-foreground mb-8">
          Sign in to view your account settings and usage stats.
        </p>

        <Button onClick={() => navigate("/handler/signin")}>Sign In</Button>
      </div>
    );
  }

  const hasEngagement = engagement && engagement.total_synths > 0;
  const maxVoiceDuration = engagement?.voices[0]?.total_duration_ms ?? 0;
  const multipleModels = voicesByModel.size > 1;

  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back
      </Button>

      {/* Header */}
      <div className="flex items-baseline justify-between mb-10">
        <div>
          <h1 className="text-4xl font-bold mb-1">Account</h1>
          <p className="text-muted-foreground">{user?.primaryEmail ?? ""}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => navigate("/account/settings")}>
          <Settings className="h-4 w-4 mr-2" />
          Manage
        </Button>
      </div>

      {/* Listening Journey */}
      {hasEngagement ? (
        <>
          <div className="mb-6">
            <div className="text-4xl font-bold">{formatDuration(engagement.total_duration_ms)} listened</div>
            <p className="text-muted-foreground mt-1">
              {[
                getLotrComparison(engagement.total_duration_ms),
                formatCharacters(engagement.total_characters),
              ].filter(Boolean).join(" · ")}
            </p>
          </div>

          {/* Voices by model */}
          {voicesByModel.size > 0 && (
            <Card className="mb-10">
              <CardContent className="pt-6">
                {[...voicesByModel.entries()].map(([modelSlug, voices]) => (
                  <div key={modelSlug} className={multipleModels ? "mb-6 last:mb-0" : ""}>
                    {multipleModels && (
                      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3">
                        {modelSlug}
                      </div>
                    )}
                    <div className="space-y-2.5">
                      {voices.map((v) => (
                        <div key={v.voice_slug} className="flex items-center gap-3">
                          <span className="w-20 shrink-0 text-sm font-medium truncate">
                            {v.voice_name ?? v.voice_slug}
                          </span>
                          <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full transition-all"
                              style={{ width: `${(v.total_duration_ms / maxVoiceDuration) * 100}%` }}
                            />
                          </div>
                          <span className="text-xs text-muted-foreground w-16 text-right shrink-0">
                            {formatDuration(v.total_duration_ms)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <Card className="mb-10">
          <CardContent className="py-8 text-center">
            <p className="text-muted-foreground">
              {engagement && engagement.document_count > 0
                ? `${engagement.document_count} document${engagement.document_count !== 1 ? "s" : ""} in your library. Listening stats will appear as you use Yapit.`
                : "Your listening stats will appear here as you use Yapit."}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Settings */}
      <Card className="mb-10">
        <CardHeader>
          <CardTitle className="text-base">Settings</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Appearance */}
          <div className="mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">Appearance</div>
          <div className="flex flex-col">
            <SettingRow label="Theme" description="Light, dark, or match your system">
              <div className="flex gap-1">
                {([
                  { value: "light" as Theme, icon: Sun, label: "Light" },
                  { value: "dark" as Theme, icon: Moon, label: "Dark" },
                  { value: "system" as Theme, icon: Monitor, label: "System" },
                ] as const).map(({ value, icon: Icon, label }) => (
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

            {isDark && (
              <SettingRow label="Dark theme">
                <div className="flex gap-1.5">
                  {darkThemes.map(({ value, label, bg, accent }) => (
                    <button
                      key={value}
                      onClick={() => setSettings({ darkTheme: value })}
                      className={cn(
                        "relative flex items-center gap-1.5 px-2 py-1 text-xs rounded transition-colors",
                        settings.darkTheme === value
                          ? "ring-1 ring-primary"
                          : "opacity-70 hover:opacity-100"
                      )}
                      style={{ backgroundColor: bg, color: "oklch(0.9 0.02 80)" }}
                    >
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: accent }}
                      />
                      {label}
                    </button>
                  ))}
                </div>
              </SettingRow>
            )}
          </div>

          {/* Reading */}
          <div className="mt-6 mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">Reading</div>
          <div className="flex flex-col">
            <SettingRow label="Scroll on restore" description="Scroll to saved position when opening a document">
              <Switch
                checked={settings.scrollOnRestore}
                onCheckedChange={(checked) => setSettings({ scrollOnRestore: checked })}
              />
            </SettingRow>

            <SettingRow label="Live scroll tracking" description="Keep current block centered during playback">
              <Switch
                checked={settings.liveScrollTracking}
                onCheckedChange={(checked) => setSettings({ liveScrollTracking: checked })}
              />
            </SettingRow>

            {!isMobile && (
              <SettingRow label="Content width" description="Maximum width of document text">
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

            <SettingRow label="Scroll position" description="Where the current block appears on screen">
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
          </div>

          {/* Sharing */}
          <div className="mt-6 mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">Sharing</div>
          <div className="flex flex-col">
            <SettingRow label="Auto-import shared documents" description="Add to library automatically when opening">
              <Switch
                checked={autoImportSharedDocuments}
                onCheckedChange={setAutoImportSharedDocuments}
              />
            </SettingRow>

            <SettingRow label="New documents shareable" description="Make new documents shareable by default">
              <Switch
                checked={defaultDocumentsPublic}
                onCheckedChange={setDefaultDocumentsPublic}
              />
            </SettingRow>
          </div>
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive flex items-center gap-2">
            <AlertTriangle className="h-5 w-5" />
            Danger Zone
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Delete Documents</p>
              <p className="text-sm text-muted-foreground">
                Delete all or old documents from your library
              </p>
            </div>
            <DropdownMenu open={bulkDeleteDropdownOpen} onOpenChange={setBulkDeleteDropdownOpen}>
              <DropdownMenuTrigger asChild>
                <Button variant="outline">
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete Documents...
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => openBulkDeleteDialog(7)}>
                  <Calendar className="h-4 w-4 mr-2" />
                  Older than 7 days
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => openBulkDeleteDialog(30)}>
                  <Calendar className="h-4 w-4 mr-2" />
                  Older than 30 days
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => openBulkDeleteDialog(90)}>
                  <Calendar className="h-4 w-4 mr-2" />
                  Older than 90 days
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => openBulkDeleteDialog(365)}>
                  <Calendar className="h-4 w-4 mr-2" />
                  Older than 1 year
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => openBulkDeleteDialog(null)}
                  className="text-destructive focus:text-destructive"
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete all documents
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Delete Account</p>
              <p className="text-sm text-muted-foreground">
                Permanently delete your account and all associated data
              </p>
            </div>
            <Button variant="destructive" onClick={() => setDeleteDialogOpen(true)}>
              <Trash2 className="h-4 w-4 mr-2" />
              Delete Account
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Delete Account Confirmation */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Delete Account
            </DialogTitle>
            <DialogDescription className="pt-4 space-y-3">
              <p>This action is irreversible. The following will be permanently deleted:</p>
              <ul className="list-disc list-inside space-y-1 text-sm">
                <li>All your documents and their audio</li>
                <li>Your preferences and settings</li>
              </ul>
              {engagement && engagement.document_count > 0 && (
                <p className="font-medium">
                  You have {engagement.document_count} document{engagement.document_count !== 1 ? "s" : ""} that will be
                  deleted.
                </p>
              )}
              <p className="text-sm">
                If you have an active subscription, you will lose access immediately (even if your billing period hasn't ended).
              </p>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)} disabled={isDeleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteAccount} disabled={isDeleting}>
              {isDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                "Yes, delete my account"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk Delete Confirmation */}
      <Dialog open={bulkDeleteDialogOpen} onOpenChange={setBulkDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Delete Documents
            </DialogTitle>
            <DialogDescription className="pt-4 space-y-3">
              <p>
                {bulkDeleteDays
                  ? `This will permanently delete all documents older than ${bulkDeleteDays} days.`
                  : "This will permanently delete all your documents."}
              </p>
              <p className="text-sm">This action cannot be undone.</p>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setBulkDeleteDialogOpen(false)} disabled={isBulkDeleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleBulkDelete} disabled={isBulkDeleting}>
              {isBulkDeleting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Deleting...
                </>
              ) : (
                "Yes, delete"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AccountPage;

// --- Helpers ---

function formatDuration(ms: number): string {
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.floor((ms % 3_600_000) / 60_000);

  if (hours === 0 && minutes === 0) return "< 1 min";
  if (hours === 0) return `${minutes} min`;
  if (minutes === 0) return `${hours} hour${hours !== 1 ? "s" : ""}`;
  return `${hours}h ${minutes}m`;
}

function formatCharacters(chars: number): string {
  if (chars >= 1_000_000) return `${(chars / 1_000_000).toFixed(1)}M characters`;
  if (chars >= 1_000) return `${(chars / 1_000).toFixed(1)}K characters`;
  return `${chars.toLocaleString()} characters`;
}

function getLotrComparison(ms: number): string | null {
  if (ms < 60_000) return null;

  const trilogies = ms / LOTR_TRILOGY_MS;
  const audiobooks = trilogies * 3;

  if (trilogies < 0.01) {
    return `${((ms / (LOTR_TRILOGY_MS / 3)) * 100).toFixed(0)}% of the Fellowship audiobook`;
  }
  if (audiobooks < 1) return `${(audiobooks * 100).toFixed(0)}% of an LOTR audiobook`;
  if (trilogies < 1) return `${audiobooks.toFixed(1)} LOTR audiobooks`;
  if (trilogies < 10) return `${trilogies.toFixed(1)}× the LOTR trilogy`;
  return `${Math.round(trilogies)}× the LOTR trilogy`;
}
