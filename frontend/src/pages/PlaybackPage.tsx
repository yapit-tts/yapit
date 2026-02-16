import { SoundControl } from '@/components/soundControl';
import { StructuredDocumentView } from '@/components/structuredDocument';
import { WebGPUWarningBanner } from '@/components/webGPUWarningBanner';
import { DocumentOutliner } from '@/components/documentOutliner';
import { OutlinerSidebar } from '@/components/outlinerSidebar';
import { useOutliner } from '@/hooks/useOutliner';
import { useSidebar } from '@/components/ui/sidebar';
import { useFilteredPlayback } from '@/hooks/useFilteredPlayback';
import { usePlaybackEngine, type Block } from '@/hooks/usePlaybackEngine';
import { useParams, useLocation, Link, useNavigate } from "react-router";
import { useRef, useState, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { useApi } from '@/api';
import { Loader2, FileQuestion, Download, X, AudioLines, AlertTriangle } from "lucide-react";
import { AxiosError } from "axios";
import { buildSectionIndex, findSectionForBlock, type Section } from '@/lib/sectionIndex';
import { buildSlugMap } from '@/components/structuredDocument';
import { type VoiceSelection, getVoiceSelection, getPlaybackSpeed, setPlaybackSpeed as savePlaybackSpeed, getVolume, setVolume as saveVolume } from '@/lib/voiceSelection';
import { useSettings } from '@/hooks/useSettings';
import { useUserPreferences } from '@/hooks/useUserPreferences';

const POSITION_KEY_PREFIX = "yapit_playback_position_";
const OUTLINER_STATE_KEY_PREFIX = "yapit_outliner_state_";

interface PlaybackPosition {
  block: number;
  progressMs: number;
}

function getPlaybackPosition(documentId: string): PlaybackPosition | null {
  try {
    const stored = localStorage.getItem(POSITION_KEY_PREFIX + documentId);
    if (stored) return JSON.parse(stored);
  } catch { /* ignore */ }
  return null;
}

function setPlaybackPosition(documentId: string, position: PlaybackPosition): void {
  localStorage.setItem(POSITION_KEY_PREFIX + documentId, JSON.stringify(position));
}

interface DocumentMetadata {
  content_type?: string;
  page_count?: number;
  title?: string;
  url?: string;
  file_name?: string;
  file_size?: number;
}

interface DocumentResponse {
  id: string;
  title: string | null;
  original_text: string;
  structured_content: string | null;
  metadata_dict: DocumentMetadata | null;
  last_block_idx: number | null;
}

interface PublicDocumentResponse {
  id: string;
  title: string | null;
  original_text: string;
  structured_content: string;
  metadata_dict: DocumentMetadata | null;
  block_count: number;
}

const PlaybackPage = () => {
  const { documentId } = useParams<{ documentId: string }>();
  const { state } = useLocation();
  const navigate = useNavigate();
  const initialTitle: string | undefined = state?.documentTitle;
  const failedPages: number[] | undefined = state?.failedPages;

  const { api, isAuthReady, isAnonymous } = useApi();
  const { settings } = useSettings();
  const { autoImportSharedDocuments } = useUserPreferences();
  const scrollBlockPosition: ScrollLogicalPosition = settings.scrollPosition === "top" ? "start"
    : settings.scrollPosition === "bottom" ? "end" : "center";
  const outliner = useOutliner();
  const sidebar = useSidebar();

  // Document data
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [documentBlocks, setDocumentBlocks] = useState<Block[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Public document viewing
  const [isPublicView, setIsPublicView] = useState(false);
  const [showImportBanner, setShowImportBanner] = useState(true);
  const [showFailedPagesBanner, setShowFailedPagesBanner] = useState(true);
  const [showKeybindings, setShowKeybindings] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  // Outliner state
  const [sections, setSections] = useState<Section[]>([]);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set());
  const [skippedSections, setSkippedSections] = useState<Set<string>>(new Set());
  const [slugMap, setSlugMap] = useState<Map<string, string>>(new Map());

  // Voice and playback settings (UI-owned, synced into engine)
  const [voiceSelection, setVoiceSelection] = useState<VoiceSelection>(getVoiceSelection);
  const [volume, setVolume_] = useState<number>(getVolume);
  const [playbackSpeed, setPlaybackSpeed_] = useState<number>(getPlaybackSpeed);

  const setVolume = useCallback((v: number) => { setVolume_(v); saveVolume(v); }, []);
  const setPlaybackSpeed = useCallback((s: number) => { setPlaybackSpeed_(s); savePlaybackSpeed(s); }, []);

  // Scroll detach state
  const [isScrollDetached, setIsScrollDetached] = useState(false);
  const [backToReadingDismissed, setBackToReadingDismissed] = useState(false);
  const scrollCooldownRef = useRef(false);
  const scrollCooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Derived
  const documentTitle = document?.title ?? initialTitle;
  const structuredContent = document?.structured_content ?? null;
  const fallbackContent = document?.original_text ?? "";
  const sourceUrl = document?.metadata_dict?.url ?? null;
  const markdownContent = document?.original_text ?? null;
  const estimated_ms = documentBlocks.reduce((sum, b) => sum + (b.est_duration_ms || 0), 0);

  // --- Playback engine ---
  const { snapshot, engine, ws, serverTTS, browserTTS } = usePlaybackEngine(
    documentId,
    documentBlocks,
    voiceSelection,
    sections,
    skippedSections,
  );

  const isPlaying = snapshot.status === "playing";
  const isBuffering = snapshot.status === "buffering";
  const currentBlock = snapshot.currentBlock;

  // Sync playback speed and volume into engine/audio
  useEffect(() => {
    engine.setPlaybackSpeed(playbackSpeed);
  }, [playbackSpeed, engine]);

  useEffect(() => {
    engine.setVolume(volume / 100);
  }, [volume, engine]);

  // --- DOM highlighting (imperative, no React state) ---

  const prevBlockIdxRef = useRef<number>(-1);
  const hoveredBlockRef = useRef<number | null>(null);
  const isDraggingProgressBarRef = useRef(false);
  const lastHoverScrollTimeRef = useRef<number>(0);

  const findElementsByAudioIdx = useCallback((idx: number) => {
    const innerSpans = window.document.querySelectorAll(`[data-audio-idx="${idx}"]`);
    if (innerSpans.length > 0) return innerSpans;
    return window.document.querySelectorAll(`[data-audio-block-idx="${idx}"]`);
  }, []);

  useLayoutEffect(() => {
    const ACTIVE_BLOCK_CLASS = "audio-block-active";
    if (prevBlockIdxRef.current >= 0) {
      findElementsByAudioIdx(prevBlockIdxRef.current).forEach(el => el.classList.remove(ACTIVE_BLOCK_CLASS));
    }
    if (currentBlock >= 0) {
      findElementsByAudioIdx(currentBlock).forEach(el => el.classList.add(ACTIVE_BLOCK_CLASS));
    }
    prevBlockIdxRef.current = currentBlock;
  }, [currentBlock, findElementsByAudioIdx]);

  const handleBlockHover = useCallback((idx: number | null, isDragging: boolean) => {
    const prevHovered = hoveredBlockRef.current;
    hoveredBlockRef.current = idx;
    isDraggingProgressBarRef.current = isDragging;
    const HOVER_BLOCK_CLASS = "audio-block-hovered";

    if (prevHovered !== null && prevHovered !== idx) {
      findElementsByAudioIdx(prevHovered).forEach(el => el.classList.remove(HOVER_BLOCK_CLASS));
    }
    if (idx !== null && idx !== currentBlock) {
      findElementsByAudioIdx(idx).forEach(el => el.classList.add(HOVER_BLOCK_CLASS));
    }
    if (idx === null || idx === currentBlock) {
      if (prevHovered !== null) {
        findElementsByAudioIdx(prevHovered).forEach(el => el.classList.remove(HOVER_BLOCK_CLASS));
      }
    }

    if (isDragging && idx !== null && idx !== currentBlock) {
      const SCROLL_THROTTLE_MS = 500;
      const now = Date.now();
      if (now - lastHoverScrollTimeRef.current >= SCROLL_THROTTLE_MS) {
        const element = findElementsByAudioIdx(idx)[0];
        if (element) {
          const rect = element.getBoundingClientRect();
          const margin = 50;
          const isVisible = rect.top >= margin && rect.bottom <= window.innerHeight - margin;
          if (!isVisible) {
            element.scrollIntoView({ behavior: "auto", block: "center" });
            lastHoverScrollTimeRef.current = now;
          }
        }
      }
    }
  }, [findElementsByAudioIdx, currentBlock]);

  // --- Document fetching ---

  useEffect(() => {
    if (!isAuthReady) return;
    if (!documentId) { setError("No document ID provided"); setIsLoading(false); return; }

    const fetchData = async () => {
      try {
        const [docResponse, blocksResponse] = await Promise.all([
          api.get<DocumentResponse>(`/v1/documents/${documentId}`),
          api.get<Block[]>(`/v1/documents/${documentId}/blocks`),
        ]);
        setDocument(docResponse.data);
        setDocumentBlocks(blocksResponse.data);
        setIsPublicView(false);
      } catch (err) {
        if (err instanceof AxiosError && err.response?.status === 403) {
          try {
            const [publicDocResponse, publicBlocksResponse] = await Promise.all([
              api.get<PublicDocumentResponse>(`/v1/documents/${documentId}/public`),
              api.get<Block[]>(`/v1/documents/${documentId}/public/blocks`),
            ]);
            setDocument({
              id: publicDocResponse.data.id,
              title: publicDocResponse.data.title,
              original_text: publicDocResponse.data.original_text,
              structured_content: publicDocResponse.data.structured_content,
              metadata_dict: publicDocResponse.data.metadata_dict,
              last_block_idx: null,
            });
            setDocumentBlocks(publicBlocksResponse.data);
            setIsPublicView(true);
            setShowImportBanner(true);
          } catch {
            setError("not_found");
          }
        } else if (err instanceof AxiosError && (err.response?.status === 404 || err.response?.status === 422)) {
          setError("not_found");
        } else {
          setError(err instanceof Error ? err.message : "Failed to fetch document");
        }
      } finally {
        setIsLoading(false);
      }
    };
    fetchData();
  }, [documentId, api, isAuthReady]);

  // --- Position persistence ---

  useEffect(() => {
    if (!documentId || documentBlocks.length === 0 || !document) return;

    const serverBlock = document.last_block_idx;
    const localSaved = getPlaybackPosition(documentId);

    let restoreBlock: number | null = null;
    let restoreProgressMs = 0;

    if (!isAnonymous && serverBlock !== null && serverBlock >= 0 && serverBlock < documentBlocks.length) {
      restoreBlock = serverBlock;
      for (let i = 0; i < serverBlock; i++) {
        restoreProgressMs += documentBlocks[i].est_duration_ms || 0;
      }
    } else if (localSaved && localSaved.block >= 0 && localSaved.block < documentBlocks.length) {
      restoreBlock = localSaved.block;
      restoreProgressMs = localSaved.progressMs;
    }

    if (restoreBlock !== null) {
      engine.restorePosition(restoreBlock, restoreProgressMs);

      if (settings.scrollOnRestore) {
        setTimeout(() => {
          const blockElement = window.document.querySelector(`[data-audio-idx="${restoreBlock}"]`)
            || window.document.querySelector(`[data-audio-block-idx="${restoreBlock}"]`);
          if (blockElement) blockElement.scrollIntoView({ behavior: "smooth", block: scrollBlockPosition });
        }, 100);
      }
    }
  }, [documentId, documentBlocks, document, isAnonymous, settings.scrollOnRestore, engine]);

  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;
  const isAnonymousRef = useRef(isAnonymous);
  isAnonymousRef.current = isAnonymous;

  useEffect(() => {
    if (!documentIdRef.current || currentBlock < 0) return;
    setPlaybackPosition(documentIdRef.current, {
      block: currentBlock,
      progressMs: engine.getBlockStartTime(),
    });
    if (!isAnonymousRef.current) {
      api.patch(`/v1/documents/${documentIdRef.current}/position`, {
        block_idx: currentBlock,
      }).catch(() => {});
    }
  }, [currentBlock, api, engine]);

  // --- Scroll handling ---

  const scrollToBlock = useCallback((blockIdx: number, behavior: ScrollBehavior = "smooth") => {
    if (blockIdx < 0) return;
    scrollCooldownRef.current = true;
    if (scrollCooldownTimerRef.current) clearTimeout(scrollCooldownTimerRef.current);
    const element = findElementsByAudioIdx(blockIdx)[0];
    if (element) element.scrollIntoView({ behavior, block: scrollBlockPosition });
    scrollCooldownTimerRef.current = setTimeout(() => { scrollCooldownRef.current = false; }, 1200);
  }, [findElementsByAudioIdx, scrollBlockPosition]);

  // Preview scroll position change immediately
  useEffect(() => {
    if (currentBlock >= 0) scrollToBlock(currentBlock);
  }, [scrollBlockPosition]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (currentBlock < 0 || !isPlaying) return;
    if (!settings.liveScrollTracking || isScrollDetached) return;
    if (scrollCooldownRef.current) return;
    scrollToBlock(currentBlock);
  }, [currentBlock, settings.liveScrollTracking, isScrollDetached, scrollToBlock, isPlaying]);

  useEffect(() => {
    if (!isPlaying || !settings.liveScrollTracking || isScrollDetached || currentBlock < 0) return;
    if (scrollCooldownRef.current) return;
    scrollToBlock(currentBlock);
  }, [isPlaying, settings.liveScrollTracking, isScrollDetached, currentBlock, scrollToBlock]);

  useEffect(() => {
    const handleScroll = () => {
      if (scrollCooldownRef.current) return;
      if (!isPlaying || !settings.liveScrollTracking) return;
      if (isScrollDetached) return;
      setIsScrollDetached(true);
      setBackToReadingDismissed(false);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [settings.liveScrollTracking, isScrollDetached, isPlaying]);

  useEffect(() => {
    if (isPlaying && isScrollDetached) {
      setIsScrollDetached(false);
      scrollToBlock(currentBlock);
    }
  }, [isPlaying]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleBackToReading = useCallback(() => {
    setIsScrollDetached(false);
    scrollToBlock(currentBlock, "smooth");
  }, [currentBlock, scrollToBlock]);

  // --- Keyboard and MediaSession ---

  const isPlayingRef = useRef(isPlaying);
  isPlayingRef.current = isPlaying;
  const speedRef = useRef(playbackSpeed);
  speedRef.current = playbackSpeed;
  const volumeRef = useRef(volume);
  volumeRef.current = volume;
  const prevVolumeRef = useRef(volume || 50);
  if (volume > 0) prevVolumeRef.current = volume;
  const scrollToBlockRef = useRef(scrollToBlock);
  scrollToBlockRef.current = scrollToBlock;
  const showKeybindingsRef = useRef(false);
  showKeybindingsRef.current = showKeybindings;
  const handleBackToReadingRef = useRef(handleBackToReading);
  handleBackToReadingRef.current = handleBackToReading;
  const toggleSidebarRef = useRef(sidebar.toggleSidebar);
  toggleSidebarRef.current = sidebar.toggleSidebar;
  const toggleOutlinerRef = useRef(outliner.toggleOutliner);
  toggleOutlinerRef.current = outliner.toggleOutliner;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName)) return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          if (isPlayingRef.current) engine.pause(); else engine.play();
          break;
        case "j": case "ArrowDown":
          e.preventDefault();
          engine.skipForward();
          scrollToBlockRef.current(engine.getSnapshot().currentBlock);
          break;
        case "k": case "ArrowUp":
          e.preventDefault();
          engine.skipBack();
          scrollToBlockRef.current(engine.getSnapshot().currentBlock);
          break;
        case "l": case "ArrowRight":
          e.preventDefault();
          setPlaybackSpeed(Math.min(3, Math.round((speedRef.current + 0.1) * 10) / 10));
          break;
        case "h": case "ArrowLeft":
          e.preventDefault();
          setPlaybackSpeed(Math.max(0.5, Math.round((speedRef.current - 0.1) * 10) / 10));
          break;
        case "m":
          e.preventDefault();
          setVolume(volumeRef.current > 0 ? 0 : prevVolumeRef.current);
          break;
        case "=": case "+":
          e.preventDefault();
          setVolume(Math.min(100, volumeRef.current + 5));
          break;
        case "-":
          e.preventDefault();
          setVolume(Math.max(0, volumeRef.current - 5));
          break;
        case "o":
          e.preventDefault();
          toggleOutlinerRef.current();
          break;
        case "r":
          e.preventDefault();
          handleBackToReadingRef.current();
          break;
        case "?":
          e.preventDefault();
          setShowKeybindings(prev => !prev);
          break;
        case "Escape":
          if (showKeybindingsRef.current) {
            e.preventDefault();
            setShowKeybindings(false);
          }
          break;
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [engine, setPlaybackSpeed, setVolume]);

  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
      ["play", () => engine.play()],
      ["pause", () => engine.pause()],
      ["nexttrack", () => engine.skipForward()],
      ["previoustrack", () => engine.skipBack()],
      ["seekforward", () => engine.skipForward()],
      ["seekbackward", () => engine.skipBack()],
    ];
    for (const [action, handler] of handlers) {
      try { navigator.mediaSession.setActionHandler(action, handler); }
      catch { /* unsupported action */ }
    }
    return () => {
      for (const [action] of handlers) {
        try { navigator.mediaSession.setActionHandler(action, null); }
        catch { /* unsupported action */ }
      }
    };
  }, [engine]);

  // MediaSession metadata — shows title/artwork in OS media controls (lock screen, dynamic island, etc.)
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: documentTitle ?? "Untitled",
      artist: "Yapit",
      artwork: [
        { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
        { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      ],
    });
  }, [documentTitle]);

  // MediaSession playback state + position — enables progress bar and play/pause icon in OS controls
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.playbackState = isPlaying ? "playing" : "paused";
    if (snapshot.totalDuration > 0) {
      try {
        const durationSec = snapshot.totalDuration / 1000;
        const positionSec = Math.min(snapshot.audioProgress / 1000, durationSec);
        navigator.mediaSession.setPositionState({
          duration: durationSec,
          playbackRate: playbackSpeed,
          position: positionSec,
        });
      } catch { /* setPositionState can throw on invalid values */ }
    }
  }, [isPlaying, snapshot.audioProgress, snapshot.totalDuration, playbackSpeed]);

  // --- Outliner ---

  useEffect(() => {
    if (!structuredContent || documentBlocks.length === 0 || !documentId) {
      setSections([]);
      return;
    }
    try {
      const parsed = JSON.parse(structuredContent);
      const sectionIndex = buildSectionIndex(parsed, documentBlocks);
      setSections(sectionIndex);
      setSlugMap(buildSlugMap(parsed.blocks ?? []));

      const savedState = localStorage.getItem(OUTLINER_STATE_KEY_PREFIX + documentId);
      if (savedState) {
        try {
          const { expanded, skipped } = JSON.parse(savedState);
          const validSectionIds = new Set(sectionIndex.map(s => s.id));
          setExpandedSections(new Set((expanded as string[]).filter(id => validSectionIds.has(id))));
          setSkippedSections(new Set((skipped as string[]).filter(id => validSectionIds.has(id))));
        } catch {
          setExpandedSections(new Set(sectionIndex.map(s => s.id)));
          setSkippedSections(new Set());
        }
      } else {
        setExpandedSections(new Set(sectionIndex.map(s => s.id)));
        setSkippedSections(new Set());
      }
    } catch {
      setSections([]);
    }
  }, [structuredContent, documentBlocks, documentId]);

  useEffect(() => {
    if (sections.length === 0 || currentBlock < 0) return;
    const currentSection = findSectionForBlock(sections, currentBlock);
    if (currentSection && !expandedSections.has(currentSection.id) && !skippedSections.has(currentSection.id)) {
      setExpandedSections(prev => new Set([...prev, currentSection.id]));
    }
  }, [currentBlock, sections, expandedSections, skippedSections]);

  useEffect(() => {
    if (!documentId || sections.length === 0) return;
    localStorage.setItem(OUTLINER_STATE_KEY_PREFIX + documentId, JSON.stringify({
      expanded: Array.from(expandedSections),
      skipped: Array.from(skippedSections),
    }));
  }, [documentId, sections.length, expandedSections, skippedSections]);

  const handleSectionToggle = useCallback((sectionId: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) next.delete(sectionId);
      else next.add(sectionId);
      return next;
    });
  }, []);

  const handleSectionSkip = useCallback((sectionId: string) => {
    setSkippedSections(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
        setExpandedSections(expanded => {
          const newExpanded = new Set(expanded);
          newExpanded.delete(sectionId);
          return newExpanded;
        });
      }
      return next;
    });
  }, []);

  const handleExpandAllSections = useCallback(() => {
    setExpandedSections(new Set(sections.map(s => s.id)));
  }, [sections]);

  const handleCollapseAllSections = useCallback(() => {
    const currentSection = currentBlock >= 0 ? findSectionForBlock(sections, currentBlock) : null;
    setExpandedSections(currentSection ? new Set([currentSection.id]) : new Set());
  }, [sections, currentBlock]);

  const handleOutlinerNavigate = useCallback((blockIdx: number) => {
    engine.seekToBlock(blockIdx);
    scrollToBlock(blockIdx);
    const section = sections.find(s => s.startBlockIdx === blockIdx)
      ?? sections.flatMap(s => s.subsections).find(s => s.blockIdx === blockIdx);
    const slug = section ? slugMap.get(section.id) : undefined;
    if (slug) {
      history.replaceState(null, "", `#${slug}`);
    }
  }, [engine, scrollToBlock, sections, slugMap]);

  const shouldShowOutliner = sections.length > 0 && documentBlocks.length >= 30;

  useEffect(() => {
    outliner.setEnabled(shouldShowOutliner);
    return () => outliner.setEnabled(false);
  }, [shouldShowOutliner, outliner]);

  // --- Progress bar values ---

  const handleBlockChange = useCallback((newBlock: number) => {
    engine.seekToBlock(newBlock);
  }, [engine]);

  const handleDocumentBlockClick = useCallback((audioBlockIdx: number) => {
    engine.seekToBlock(audioBlockIdx);
  }, [engine]);

  const filteredPlayback = useFilteredPlayback(
    documentBlocks,
    sections,
    expandedSections,
    snapshot.blockStates,
    currentBlock,
    skippedSections,
  );

  const progressBarValues = useMemo(() => {
    if (shouldShowOutliner) {
      return {
        estimated_ms: filteredPlayback.filteredDuration,
        numberOfBlocks: filteredPlayback.filteredBlockCount,
        currentBlock: filteredPlayback.visualCurrentBlock ?? 0,
        setCurrentBlock: handleBlockChange,
        onBlockHover: handleBlockHover,
        audioProgress: filteredPlayback.filteredElapsedMs,
        blockStates: filteredPlayback.filteredBlockStates,
        visualToAbsolute: filteredPlayback.visualToAbsolute,
      };
    }
    return {
      estimated_ms: snapshot.totalDuration > 0 ? snapshot.totalDuration : estimated_ms,
      numberOfBlocks: documentBlocks.length,
      currentBlock: currentBlock >= 0 ? currentBlock : 0,
      setCurrentBlock: handleBlockChange,
      onBlockHover: handleBlockHover,
      audioProgress: snapshot.audioProgress,
      blockStates: snapshot.blockStates,
    };
  }, [shouldShowOutliner, filteredPlayback, snapshot, estimated_ms, documentBlocks.length, currentBlock, handleBlockChange, handleBlockHover]);

  // --- Title / Import ---

  const handleTitleChange = useCallback(async (newTitle: string) => {
    if (!documentId) return;
    try {
      await api.patch(`/v1/documents/${documentId}`, { title: newTitle });
      setDocument(prev => prev ? { ...prev, title: newTitle } : prev);
      window.dispatchEvent(new CustomEvent('document-title-changed', {
        detail: { documentId, title: newTitle }
      }));
    } catch (err) {
      console.error("Failed to update title:", err);
      setDocument(prev => prev ? { ...prev } : prev);
      const errorMessage = err instanceof AxiosError && err.response?.status === 422
        ? "Title is too long (max 500 characters)"
        : "Failed to update title";
      alert(errorMessage);
    }
  }, [api, documentId]);

  const handleImportDocument = useCallback(async () => {
    if (!documentId || isImporting) return;
    setIsImporting(true);
    try {
      const response = await api.post<{ id: string; title: string | null }>(`/v1/documents/${documentId}/import`);
      navigate(`/listen/${response.data.id}`, { replace: true });
    } catch (err) {
      console.error("Failed to import document:", err);
      alert("Failed to add document to library");
      setIsImporting(false);
    }
  }, [api, documentId, isImporting, navigate]);

  useEffect(() => {
    if (isPublicView && autoImportSharedDocuments && !isImporting) handleImportDocument();
  }, [isPublicView, autoImportSharedDocuments, isImporting, handleImportDocument]);

  // --- Render ---

  if (isLoading) {
    return (
      <div className="flex grow items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    if (error === "not_found") {
      return (
        <div className="flex min-h-[80vh] flex-col items-center justify-center gap-6 text-muted-foreground">
          <FileQuestion className="h-20 w-20" />
          <h1 className="text-2xl font-semibold text-foreground">Document not found</h1>
          <p className="text-base">This document may have been deleted or the link is incorrect.</p>
          <Link to="/" className="text-lg text-primary hover:underline">← Back to home</Link>
        </div>
      );
    }
    return <div className="flex grow items-center justify-center text-destructive">{error}</div>;
  }

  return (
    <div className="flex grow flex-col">
      <WebGPUWarningBanner />

      {isPublicView && showImportBanner && (
        <div className="flex items-center justify-between gap-4 bg-muted px-4 py-2 border-b border-border">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Download className="h-4 w-4" />
            <span>Shared document</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleImportDocument}
              disabled={isImporting}
              className="flex items-center gap-1.5 rounded bg-primary px-3 py-1 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {isImporting ? (<><Loader2 className="h-3 w-3 animate-spin" />Adding...</>) : "Add to Library"}
            </button>
            <button onClick={() => setShowImportBanner(false)} className="p-1 text-muted-foreground hover:text-foreground" title="Dismiss">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {failedPages && failedPages.length > 0 && showFailedPagesBanner && (
        <div className="flex items-center justify-between gap-4 bg-destructive/10 px-4 py-3 border-b border-destructive/20">
          <div className="flex items-start gap-2.5 text-sm">
            <AlertTriangle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
            <p className="text-foreground">
              {failedPages.length === 1
                ? `Page ${failedPages[0] + 1} failed to extract.`
                : `Pages ${failedPages.map(p => p + 1).join(", ")} failed to extract.`}
              {" "}Please try again later. Successfully extracted pages are cached and won't count toward your usage again.
              {" "}If this keeps happening, {" "}
              <a href="https://github.com/yapit-tts/yapit/issues" target="_blank" rel="noopener noreferrer" className="text-primary font-medium hover:underline">
                let us know
              </a>.
            </p>
          </div>
          <button
            onClick={() => setShowFailedPagesBanner(false)}
            className="shrink-0 p-2 min-w-11 min-h-11 flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent rounded-md transition-colors"
            title="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="flex grow">
        <StructuredDocumentView
          structuredContent={structuredContent}
          title={documentTitle}
          sourceUrl={sourceUrl}
          markdownContent={markdownContent}
          onBlockClick={handleDocumentBlockClick}
          fallbackContent={fallbackContent}
          onTitleChange={isPublicView ? undefined : handleTitleChange}
          sections={shouldShowOutliner ? sections : undefined}
          expandedSections={shouldShowOutliner ? expandedSections : undefined}
          skippedSections={shouldShowOutliner ? skippedSections : undefined}
          onSectionExpand={shouldShowOutliner ? handleSectionToggle : undefined}
          currentBlockIdx={shouldShowOutliner ? currentBlock : undefined}
        />
        {isPlaying && isScrollDetached && !backToReadingDismissed && (
          <div className="fixed bottom-[200px] left-1/2 -translate-x-1/2 z-50">
            <div className="flex items-center gap-2 bg-background/95 backdrop-blur-sm border border-border rounded-full px-4 py-2 shadow-lg">
              <button onClick={handleBackToReading} className="flex items-center gap-2 text-sm font-medium text-foreground hover:text-primary transition-colors">
                <AudioLines className="h-4 w-4 text-primary" />
                Back to Reading
              </button>
              <button onClick={() => setBackToReadingDismissed(true)} className="p-1 text-muted-foreground hover:text-foreground transition-colors" aria-label="Dismiss">
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
        <SoundControl
          isPlaying={isPlaying}
          isBuffering={isBuffering}
          isSynthesizing={snapshot.isSynthesizingCurrent}
          isReconnecting={ws.isReconnecting}
          connectionError={ws.connectionError}
          onPlay={() => engine.play()}
          onPause={() => engine.pause()}
          onCancelSynthesis={() => engine.stop()}
          onSkipBack={() => { engine.skipBack(); scrollToBlockRef.current(engine.getSnapshot().currentBlock); }}
          onSkipForward={() => { engine.skipForward(); scrollToBlockRef.current(engine.getSnapshot().currentBlock); }}
          progressBarValues={progressBarValues}
          volume={volume}
          onVolumeChange={setVolume}
          playbackSpeed={playbackSpeed}
          onSpeedChange={setPlaybackSpeed}
          voiceSelection={voiceSelection}
          onVoiceChange={setVoiceSelection}
          serverTTSError={serverTTS.error}
          browserTTSError={browserTTS.error}
          browserTTSDevice={browserTTS.device}
        />
        {shouldShowOutliner && (
          <OutlinerSidebar>
            <DocumentOutliner
              sections={sections}
              expandedSections={expandedSections}
              skippedSections={skippedSections}
              currentBlockIdx={currentBlock}
              onSectionToggle={handleSectionToggle}
              onSectionSkip={handleSectionSkip}
              onExpandAll={handleExpandAllSections}
              onCollapseAll={handleCollapseAllSections}
              onNavigate={handleOutlinerNavigate}
            />
          </OutlinerSidebar>
        )}
      </div>

      {showKeybindings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowKeybindings(false)}>
          <div className="bg-background border rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Keyboard shortcuts</h2>
              <button onClick={() => setShowKeybindings(false)} className="p-1 text-muted-foreground hover:text-foreground"><X className="h-4 w-4" /></button>
            </div>
            <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              {([
                ["Space", "Play / pause"],
                ["j ↓", "Next block"],
                ["k ↑", "Previous block"],
                ["l →", "Speed up"],
                ["h ←", "Speed down"],
                ["m", "Mute / unmute"],
                ["+ / =", "Volume up"],
                ["-", "Volume down"],
                ["s", "Toggle sidebar"],
                ["o", "Toggle outliner"],
                ["r", "Back to reading"],
                ["?", "This dialog"],
              ] as const).map(([keys, action]) => (
                <div key={keys} className="contents">
                  <kbd className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded text-center">{keys}</kbd>
                  <span className="text-muted-foreground">{action}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PlaybackPage;
