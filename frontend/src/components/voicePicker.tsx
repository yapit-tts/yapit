import { useState, useMemo, memo, useRef, useCallback, useEffect } from "react";
import { ChevronDown, Star, ChevronRight, Monitor, Cloud, Loader2, Info, Play, Square } from "lucide-react";
import { Link } from "react-router";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTrigger, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useIsMobile } from "@/hooks/use-mobile";
import { useCanUseLocalTTS } from "@/hooks/useCanUseLocalTTS";
import {
  type VoiceSelection,
  type ModelType,
  type KokoroLanguageCode,
  KOKORO_BROWSER_SLUG,
  KOKORO_SLUG,
  isKokoroModel,
  KOKORO_VOICES,
  LANGUAGE_INFO,
  groupKokoroVoicesByLanguage,
  isHighQualityVoice,
  setVoiceSelection,
  getKokoroSelection,
  getServerSelection,
} from "@/lib/voiceSelection";
import { usePremiumModel } from "@/hooks/usePremiumModel";

import { useUserPreferences } from "@/hooks/useUserPreferences";

interface VoicePickerProps {
  value: VoiceSelection;
  onChange: (selection: VoiceSelection) => void;
}

export function VoicePicker({ value, onChange }: VoicePickerProps) {
  const [open, setOpen] = useState(false);
  const isMobile = useIsMobile();
  const [expandedKokoroLangs, setExpandedKokoroLangs] = useState<Set<KokoroLanguageCode>>(new Set(["a"]));
  const canUseLocalTTS = useCanUseLocalTTS();
  const [localUnavailableOpen, setLocalUnavailableOpen] = useState(false);

  const { model: premiumModel, isLoading: premiumLoading } = usePremiumModel();

  // Auto-switch away from local if device can't run it
  useEffect(() => {
    if (canUseLocalTTS === false && value.model === KOKORO_BROWSER_SLUG) {
      const fallback: VoiceSelection = { ...value, model: KOKORO_SLUG };
      onChange(fallback);
      setVoiceSelection(fallback);
    }
  }, [canUseLocalTTS]);

  // Auto-switch to Kokoro if saved selection references a model that's no longer available
  useEffect(() => {
    if (premiumLoading) return;
    if (isKokoroModel(value.model)) return;
    const isValidPremium = premiumModel && value.model === premiumModel.slug;
    if (!isValidPremium) {
      const fallback: VoiceSelection = getKokoroSelection() ?? { model: KOKORO_SLUG, voiceSlug: "af_heart" };
      onChange(fallback);
      setVoiceSelection(fallback);
    }
  }, [premiumLoading, premiumModel]);

  const valueRef = useRef(value);
  valueRef.current = value;
  const premiumVoices = premiumModel?.voices ?? [];

  const { pinnedVoices, togglePinnedVoice } = useUserPreferences();

  // Voice preview audio playback
  const { api } = useApi();
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null);
  const sentenceIdxRef = useRef(0);
  const requestIdRef = useRef(0);

  const playPreview = useCallback(async (modelSlug: string, voiceSlug: string) => {
    const key = `${modelSlug}:${voiceSlug}`;
    const currentRequestId = ++requestIdRef.current;

    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      URL.revokeObjectURL(previewAudioRef.current.src);
      previewAudioRef.current = null;
    }

    if (previewingVoice === key) {
      setPreviewingVoice(null);
      return;
    }

    setPreviewingVoice(key);
    const idx = sentenceIdxRef.current;
    sentenceIdxRef.current = (idx + 1) % 5;

    try {
      const { data } = await api.get<{ audio_url: string | null; error: string | null }>(`/v1/models/${modelSlug}/voices/${voiceSlug}/preview`, {
        params: { sentence_idx: idx },
      });

      if (currentRequestId !== requestIdRef.current) return;

      if (!data.audio_url) {
        console.error("Voice preview failed:", data.error);
        setPreviewingVoice(null);
        return;
      }
      const audioResponse = await api.get(data.audio_url, { responseType: "blob" });

      if (currentRequestId !== requestIdRef.current) return;

      const blobUrl = URL.createObjectURL(audioResponse.data);
      const audio = new Audio(blobUrl);
      previewAudioRef.current = audio;
      audio.onended = () => {
        setPreviewingVoice(null);
        URL.revokeObjectURL(blobUrl);
      };
      audio.onerror = () => {
        setPreviewingVoice(null);
        URL.revokeObjectURL(blobUrl);
      };
      await audio.play();
    } catch {
      if (currentRequestId === requestIdRef.current) {
        setPreviewingVoice(null);
      }
    }
  }, [api, previewingVoice]);

  const toggleKokoroLangExpanded = (lang: KokoroLanguageCode) => {
    setExpandedKokoroLangs(prev => {
      const next = new Set(prev);
      if (next.has(lang)) {
        next.delete(lang);
      } else {
        next.add(lang);
      }
      return next;
    });
  };

  const isKokoroServer = value.model === KOKORO_SLUG;
  const isKokoroModelSelected = isKokoroModel(value.model);
  const activeTab = isKokoroModelSelected ? "kokoro" : "premium";
  const premiumSlug = premiumModel?.slug ?? "";

  const handleVoiceSelect = (voiceSlug: string) => {
    const current = valueRef.current;
    const newSelection: VoiceSelection = {
      ...current,
      voiceSlug,
    };
    onChange(newSelection);
    setVoiceSelection(newSelection);
    setOpen(false);
  };

  const handleModelChange = (tab: string) => {
    let newSelection: VoiceSelection;
    if (tab === "kokoro") {
      newSelection = getKokoroSelection() ?? { model: KOKORO_SLUG, voiceSlug: "af_heart" };
    } else {
      const saved = getServerSelection();
      const voiceExists = saved && premiumVoices.some(v => v.slug === saved.voiceSlug);
      const savedModelValid = saved && saved.model === premiumSlug;
      newSelection = {
        model: savedModelValid ? saved!.model : premiumSlug,
        voiceSlug: voiceExists ? saved!.voiceSlug : premiumVoices[0]?.slug ?? "",
      };
    }
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  const handleKokoroSourceToggle = () => {
    const newModel: ModelType = isKokoroServer ? KOKORO_BROWSER_SLUG : KOKORO_SLUG;

    let voiceSlug = value.voiceSlug;
    if (newModel === KOKORO_BROWSER_SLUG) {
      const currentVoice = KOKORO_VOICES.find(v => v.index === value.voiceSlug);
      const isEnglish = currentVoice && (currentVoice.language === "a" || currentVoice.language === "b");
      if (!isEnglish) {
        voiceSlug = "af_heart";
      }
    }

    const newSelection: VoiceSelection = {
      ...value,
      model: newModel,
      voiceSlug,
    };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  // Get display name for current selection
  let currentVoiceName: string;
  if (isKokoroModelSelected) {
    currentVoiceName = KOKORO_VOICES.find(v => v.index === value.voiceSlug)?.name ?? value.voiceSlug;
  } else {
    currentVoiceName = premiumVoices.find(v => v.slug === value.voiceSlug)?.name ?? value.voiceSlug;
  }

  let modelLabel: string;
  if (isKokoroModelSelected) {
    modelLabel = `Kokoro${isKokoroServer ? "" : " (Local)"}`;
  } else {
    modelLabel = premiumModel?.name ?? "Server";
  }

  // Local mode only supports English
  const englishOnly = !isKokoroServer;
  const isEnglishLang = (lang: KokoroLanguageCode) => lang === "a" || lang === "b";

  const kokoroVoiceGroups = useMemo(() => groupKokoroVoicesByLanguage(KOKORO_VOICES), []);

  const pinnedKokoro = useMemo(
    () => KOKORO_VOICES.filter(v => pinnedVoices.includes(v.index) && (!englishOnly || isEnglishLang(v.language))),
    [pinnedVoices, englishOnly]
  );
  const pinnedPremium = useMemo(() => premiumVoices.filter(v => pinnedVoices.includes(v.slug)), [premiumVoices, pinnedVoices]);

  const triggerButton = (
    <Button variant="ghost" size="sm" className="h-9 gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <span className="font-medium">{modelLabel}</span>
      <span className="text-muted-foreground">·</span>
      <span>{currentVoiceName}</span>
      <ChevronDown className="h-4 w-4 ml-0.5" />
    </Button>
  );

  const voicePickerContent = (
    <Tabs value={activeTab} onValueChange={handleModelChange}>
      <TabsList className="w-full h-11 rounded-none border-b">
        <TabsTrigger value="kokoro" className="flex-1 text-sm py-2.5">Kokoro</TabsTrigger>
        {premiumModel && <TabsTrigger value="premium" className="flex-1 text-sm py-2.5">{premiumModel.name}</TabsTrigger>}
      </TabsList>

      <TabsContent value="kokoro" className="m-0 max-h-[60vh] sm:max-h-[28rem] overflow-y-auto">
        {/* Local/Cloud toggle */}
        <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-sm text-muted-foreground">Run on</span>
            <InfoTip isMobile={isMobile}>
              <p><strong>Local:</strong> English voices only.</p>
              <p><strong>Cloud:</strong> All available languages and voices.</p>
            </InfoTip>
          </div>
          <div className="flex rounded-md border bg-background relative">
            <button
              onClick={() => {
                if (canUseLocalTTS === false) {
                  setLocalUnavailableOpen(v => !v);
                } else if (isKokoroServer) {
                  handleKokoroSourceToggle();
                }
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-l-md transition-colors ${
                canUseLocalTTS === false
                  ? "text-muted-foreground/50 cursor-not-allowed"
                  : !isKokoroServer
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Monitor className="h-4 w-4" />
              Local
            </button>
            <button
              onClick={() => !isKokoroServer && handleKokoroSourceToggle()}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-r-md transition-colors ${
                isKokoroServer ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Cloud className="h-4 w-4" />
              Cloud
            </button>
          </div>
        </div>
        {canUseLocalTTS === false && localUnavailableOpen && (
          <div className="px-4 py-2.5 border-b bg-muted/50 text-sm text-muted-foreground">
            Requires a desktop browser with WebGPU support.{" "}
            <Link to="/tips#local-tts" className="text-primary font-medium hover:underline" onClick={() => setOpen(false)}>
              Learn more
            </Link>
          </div>
        )}
        {/* Starred section */}
        {pinnedKokoro.length > 0 && (
          <div className="border-b">
            <div className="px-4 py-2 text-sm font-medium text-muted-foreground">Starred</div>
            {pinnedKokoro.map(voice => (
              <VoiceRow
                key={voice.index}
                name={voice.name}
                flag={LANGUAGE_INFO[voice.language].flag}
                isHighQuality={isHighQualityVoice(voice)}
                gender={voice.gender}
                isPinned={true}
                isSelected={value.voiceSlug === voice.index}
                isPlaying={previewingVoice === `kokoro:${voice.index}`}
                onSelect={() => handleVoiceSelect(voice.index)}
                onPinToggle={() => togglePinnedVoice(voice.index)}
                onPreviewClick={() => playPreview("kokoro", voice.index)}
              />
            ))}
          </div>
        )}

        {/* Language sections */}
        {kokoroVoiceGroups.map(group => (
          <Collapsible
            key={group.language}
            open={expandedKokoroLangs.has(group.language)}
            onOpenChange={() => toggleKokoroLangExpanded(group.language)}
            className={`border-b last:border-b-0 ${englishOnly && !isEnglishLang(group.language) ? "hidden" : ""}`}
          >
            <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2.5 text-sm font-medium hover:bg-accent">
              <ChevronRight className={`h-4 w-4 transition-transform ${expandedKokoroLangs.has(group.language) ? "rotate-90" : ""}`} />
              <span>{group.flag}</span>
              <span className="flex-1 text-left">{group.label}</span>
              <span className="text-muted-foreground">({group.voices.length})</span>
            </CollapsibleTrigger>
            <CollapsibleContent>
              {group.voices.map(voice => (
                <VoiceRow
                  key={voice.index}
                  name={voice.name}
                  isHighQuality={isHighQualityVoice(voice)}
                  gender={voice.gender}
                  isPinned={pinnedVoices.includes(voice.index)}
                  isSelected={value.voiceSlug === voice.index}
                  isPlaying={previewingVoice === `kokoro:${voice.index}`}
                  onSelect={() => handleVoiceSelect(voice.index)}
                  onPinToggle={() => togglePinnedVoice(voice.index)}
                  onPreviewClick={() => playPreview("kokoro", voice.index)}
                />
              ))}
            </CollapsibleContent>
          </Collapsible>
        ))}
      </TabsContent>

      <TabsContent value="premium" className="m-0 max-h-[60vh] sm:max-h-[28rem] overflow-y-auto">
        {premiumLoading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            <span className="text-sm">Loading voices...</span>
          </div>
        ) : (
          <>
            {pinnedPremium.length > 0 && (
              <div className="border-b">
                <div className="px-4 py-2 text-sm font-medium text-muted-foreground">Starred</div>
                {pinnedPremium.map(voice => (
                  <VoiceRow
                    key={voice.slug}
                    name={voice.name}
                    isPinned={true}
                    isSelected={value.voiceSlug === voice.slug}
                    isPlaying={previewingVoice === `${premiumSlug}:${voice.slug}`}
                    onSelect={() => handleVoiceSelect(voice.slug)}
                    onPinToggle={() => togglePinnedVoice(voice.slug)}
                    onPreviewClick={() => playPreview(premiumSlug, voice.slug)}
                  />
                ))}
              </div>
            )}
            {premiumVoices.filter(v => !pinnedVoices.includes(v.slug)).map(voice => (
              <VoiceRow
                key={voice.slug}
                name={voice.name}
                isPinned={false}
                isSelected={value.voiceSlug === voice.slug}
                isPlaying={previewingVoice === `${premiumSlug}:${voice.slug}`}
                onSelect={() => handleVoiceSelect(voice.slug)}
                onPinToggle={() => togglePinnedVoice(voice.slug)}
                onPreviewClick={() => playPreview(premiumSlug, voice.slug)}
              />
            ))}
          </>
        )}
      </TabsContent>
    </Tabs>
  );

  if (isMobile) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          {triggerButton}
        </SheetTrigger>
        <SheetContent side="bottom" className="p-0 gap-0 max-h-[85vh]">
          <SheetTitle className="sr-only">Voice Selection</SheetTitle>
          {voicePickerContent}
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        {triggerButton}
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="start">
        {voicePickerContent}
      </PopoverContent>
    </Popover>
  );
}

/** Info icon: hover tooltip on desktop, tap-to-toggle inline text on mobile. */
function InfoTip({ children, isMobile }: { children: React.ReactNode; isMobile: boolean }) {
  const [open, setOpen] = useState(false);
  if (isMobile) {
    return (
      <>
        <button className="text-muted-foreground hover:text-foreground" onClick={() => setOpen(v => !v)}>
          <Info className="h-3.5 w-3.5" />
        </button>
        {open && <div className="basis-full text-xs text-muted-foreground pt-1">{children}</div>}
      </>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button className="text-muted-foreground hover:text-foreground">
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs">{children}</TooltipContent>
    </Tooltip>
  );
}

interface VoiceRowProps {
  name: string;
  flag?: string;
  detail?: string;
  isHighQuality?: boolean;
  gender?: "Female" | "Male";
  isPinned: boolean;
  isSelected: boolean;
  isPlaying?: boolean;
  onSelect: () => void;
  onPinToggle: () => void;
  onPreviewClick?: () => void;
}

const VoiceRow = memo(function VoiceRow({ name, flag, detail, isHighQuality, gender, isPinned, isSelected, isPlaying, onSelect, onPinToggle, onPreviewClick }: VoiceRowProps) {
  return (
    <div
      className={`flex gap-1 px-2 py-1 cursor-pointer hover:bg-accent ${isSelected ? "bg-accent" : ""} items-center`}
      onClick={onSelect}
    >
      {onPreviewClick && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onPreviewClick();
          }}
          className="p-1 text-muted-foreground hover:text-foreground flex-shrink-0 touch-manipulation"
          title="Preview voice"
        >
          {isPlaying ? <Square className="h-4 w-4 fill-current" /> : <Play className="h-4 w-4" />}
        </button>
      )}
      {detail ? (
        <div className="flex-1 min-w-0 py-0.5">
          <div className="flex items-center gap-2">
            {flag && <span className="text-sm">{flag}</span>}
            <span className="text-sm font-medium">{name}</span>
          </div>
          <p className="text-xs text-muted-foreground leading-snug">{detail}</p>
        </div>
      ) : (
        <div className="flex-1 flex items-center gap-2 py-0.5">
          {flag && <span className="text-sm">{flag}</span>}
          <span className="text-sm">{name}</span>
          {isHighQuality && <span className="text-xs" title="High quality">✨</span>}
          {gender && <span className="text-xs text-muted-foreground">{gender === "Female" ? "♀" : "♂"}</span>}
        </div>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onPinToggle();
        }}
        className="p-1.5 text-muted-foreground hover:text-foreground flex-shrink-0 touch-manipulation"
      >
        <Star className={`h-5 w-5 ${isPinned ? "fill-current text-yellow-500" : ""}`} />
      </button>
    </div>
  );
}, (prev, next) => {
  return prev.name === next.name &&
    prev.flag === next.flag &&
    prev.detail === next.detail &&
    prev.isHighQuality === next.isHighQuality &&
    prev.gender === next.gender &&
    prev.isPinned === next.isPinned &&
    prev.isSelected === next.isSelected &&
    prev.isPlaying === next.isPlaying;
});
