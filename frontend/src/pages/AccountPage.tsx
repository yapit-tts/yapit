import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useUser } from "@stackframe/react";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
import { Loader2, ArrowLeft, FileText, Clock, Type, Trash2, AlertTriangle, Mail, Settings, Share2, Calendar } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { useUserPreferences } from "@/hooks/useUserPreferences";

// LOTR trilogy stats for comparisons (Rob Inglis unabridged, trilogy only)
const LOTR_TRILOGY_MS = 194_400_000; // ~54 hours
const LOTR_TRILOGY_CHARS = 2_730_000; // ~455k words × ~6 chars

interface UserStats {
  total_audio_ms: number;
  total_characters: number;
  document_count: number;
}

const AccountPage = () => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const navigate = useNavigate();
  const user = useUser();
  const {
    autoImportSharedDocuments,
    setAutoImportSharedDocuments,
    defaultDocumentsPublic,
    setDefaultDocumentsPublic,
  } = useUserPreferences();

  const [stats, setStats] = useState<UserStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false);
  const [bulkDeleteDays, setBulkDeleteDays] = useState<number | null>(null);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);

  useEffect(() => {
    if (!isAuthReady) return;
    if (isAnonymous) {
      setIsLoading(false);
      return;
    }

    const fetchStats = async () => {
      try {
        const response = await api.get<UserStats>("/v1/users/me/stats");
        setStats(response.data);
      } catch (error) {
        console.error("Failed to fetch user stats:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchStats();
  }, [api, isAuthReady, isAnonymous]);

  const handleDeleteAccount = async () => {
    setIsDeleting(true);
    try {
      await api.delete("/v1/users/me");
      // Redirect to home after deletion - Stack Auth session will be invalid
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
      const statsResponse = await api.get<UserStats>("/v1/users/me/stats");
      setStats(statsResponse.data);
      setBulkDeleteDialogOpen(false);
      setBulkDeleteDays(null);
    } catch (error) {
      console.error("Failed to delete documents:", error);
    } finally {
      setIsBulkDeleting(false);
    }
  };

  const openBulkDeleteDialog = (days: number | null) => {
    setBulkDeleteDays(days);
    setBulkDeleteDialogOpen(true);
  };

  const formatDuration = (ms: number): string => {
    const hours = Math.floor(ms / 3_600_000);
    const minutes = Math.floor((ms % 3_600_000) / 60_000);

    if (hours === 0) {
      return `${minutes} minute${minutes !== 1 ? "s" : ""}`;
    }
    if (minutes === 0) {
      return `${hours} hour${hours !== 1 ? "s" : ""}`;
    }
    return `${hours} hour${hours !== 1 ? "s" : ""} ${minutes} min`;
  };

  const formatCharacters = (chars: number): string => {
    if (chars >= 1_000_000) {
      return `${(chars / 1_000_000).toFixed(1)}M`;
    }
    if (chars >= 1_000) {
      return `${(chars / 1_000).toFixed(1)}K`;
    }
    return chars.toLocaleString();
  };

  const getCharacterComparison = (chars: number): string | null => {
    if (chars < 1000) return null;

    const trilogies = chars / LOTR_TRILOGY_CHARS;
    const books = trilogies * 3; // 3 books in trilogy

    if (books < 0.01) {
      return "A few pages of the Fellowship";
    }
    if (books < 0.1) {
      return "A chapter of the Fellowship";
    }
    if (books < 1) {
      const percent = (books * 100).toFixed(0);
      return `${percent}% of the Fellowship`;
    }
    if (trilogies < 1) {
      return `${books.toFixed(1)} LOTR books`;
    }
    if (trilogies < 10) {
      return `${trilogies.toFixed(1)}× the LOTR trilogy`;
    }
    return `${Math.round(trilogies)}× the LOTR trilogy`;
  };

  const getDocumentComparison = (count: number): string | null => {
    if (count === 0) return null;
    if (count === 1) return "Your first scroll";
    if (count < 10) return "A hobbit's reading list";
    if (count < 30) return "Bilbo's study";
    if (count < 50) return "A corner of Rivendell's library";
    if (count < 100) return "The library of Rivendell";
    return "The archives of Minas Tirith";
  };

  const getLotrComparison = (ms: number): string | null => {
    if (ms < 60_000) return null; // Less than 1 minute, skip comparison

    // LOTR unabridged audiobook: ~57 hours total, ~19 hours per book
    const trilogies = ms / LOTR_TRILOGY_MS;
    const audiobooks = trilogies * 3;

    if (trilogies < 0.01) {
      // Less than 1% of trilogy (~34 min)
      const percent = (ms / (LOTR_TRILOGY_MS / 3)) * 100;
      return `${percent.toFixed(0)}% of the Fellowship audiobook`;
    }
    if (audiobooks < 1) {
      // Less than one audiobook
      const percent = audiobooks * 100;
      return `${percent.toFixed(0)}% of an LOTR audiobook`;
    }
    if (trilogies < 1) {
      // 1-3 audiobooks
      return `${audiobooks.toFixed(1)} LOTR audiobooks`;
    }
    if (trilogies < 10) {
      return `${trilogies.toFixed(1)}× the LOTR trilogy`;
    }
    return `${Math.round(trilogies)}× the LOTR trilogy`;
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

  const lotrComparison = stats ? getLotrComparison(stats.total_audio_ms) : null;
  const charComparison = stats ? getCharacterComparison(stats.total_characters) : null;
  const docComparison = stats ? getDocumentComparison(stats.document_count) : null;

  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back
      </Button>

      <h1 className="text-4xl font-bold mb-2">Account</h1>
      <p className="text-lg text-muted-foreground mb-8">Your listening journey so far</p>

      {/* Profile Section */}
      <Card className="mb-8">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            Profile
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-muted-foreground">Email</p>
              <p className="font-medium">{user?.primaryEmail ?? "—"}</p>
            </div>
            <Button variant="outline" onClick={() => navigate("/account/settings")}>
              <Settings className="h-4 w-4 mr-2" />
              Manage
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Sharing Preferences */}
      <Card className="mb-8">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Share2 className="h-5 w-5" />
            Sharing
          </CardTitle>
          <CardDescription>Control how documents are shared</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <p className="font-medium">Auto-import shared documents</p>
              <p className="text-sm text-muted-foreground">
                Automatically add shared documents to your library when you open them
              </p>
            </div>
            <Switch
              checked={autoImportSharedDocuments}
              onCheckedChange={setAutoImportSharedDocuments}
            />
          </div>
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <p className="font-medium">Make new documents shareable by default</p>
              <p className="text-sm text-muted-foreground">
                New documents will be shareable via link when created
              </p>
            </div>
            <Switch
              checked={defaultDocumentsPublic}
              onCheckedChange={setDefaultDocumentsPublic}
            />
          </div>
        </CardContent>
      </Card>

      {/* Stats Section */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Time Listened
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{formatDuration(stats?.total_audio_ms ?? 0)}</div>
            {lotrComparison && (
              <p className="text-sm text-muted-foreground mt-1 italic">{lotrComparison}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <Type className="h-4 w-4" />
              Characters
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{formatCharacters(stats?.total_characters ?? 0)}</div>
            {charComparison && (
              <p className="text-sm text-muted-foreground mt-1 italic">{charComparison}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Documents
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{stats?.document_count ?? 0}</div>
            {docComparison && (
              <p className="text-sm text-muted-foreground mt-1 italic">{docComparison}</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive flex items-center gap-2">
            <AlertTriangle className="h-5 w-5" />
            Danger Zone
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Delete Documents */}
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Delete Documents</p>
              <p className="text-sm text-muted-foreground">
                Delete all or old documents from your library
              </p>
            </div>
            <DropdownMenu>
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

          {/* Delete Account */}
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

      {/* Delete Confirmation Dialog */}
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
              {stats && stats.document_count > 0 && (
                <p className="font-medium">
                  You have {stats.document_count} document{stats.document_count !== 1 ? "s" : ""} that will be
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

      {/* Bulk Delete Confirmation Dialog */}
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
