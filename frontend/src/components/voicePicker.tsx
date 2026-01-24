import { useState, useEffect, useMemo, memo, startTransition, useRef, useCallback } from "react";
import { ChevronDown, Star, ChevronRight, Monitor, Cloud, Loader2, Info, Play, Square } from "lucide-react";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  type VoiceSelection,
  type ModelType,
  type KokoroLanguageCode,
  type InworldLanguageCode,
  INWORLD_SLUG,
  INWORLD_MAX_SLUG,
  KOKORO_VOICES,
  LANGUAGE_INFO,
  INWORLD_LANGUAGE_INFO,
  groupKokoroVoicesByLanguage,
  groupInworldVoicesByLanguage,
  isHighQualityVoice,
  setVoiceSelection,
} from "@/lib/voiceSelection";
import { useInworldVoices } from "@/hooks/useInworldVoices";
import { useSubscription } from "@/hooks/useSubscription";
import { useUserPreferences } from "@/hooks/useUserPreferences";

interface VoicePickerProps {
  value: VoiceSelection;
  onChange: (selection: VoiceSelection) => void;
}

export function VoicePicker({ value, onChange }: VoicePickerProps) {
  const [open, setOpen] = useState(false);
  // Track which language sections are expanded (user manages, we just remember)
  const [expandedKokoroLangs, setExpandedKokoroLangs] = useState<Set<KokoroLanguageCode>>(new Set(["a"]));
  const [expandedInworldLangs, setExpandedInworldLangs] = useState<Set<InworldLanguageCode>>(new Set(["en"]));

  // Fetch Inworld voices from API
  const { voices: inworldVoices, isLoading: inworldLoading } = useInworldVoices();

  // Subscription state for auto-switching subscribers to Cloud
  const { canUseCloudKokoro, isLoading: subLoading } = useSubscription();

  // Use synced preferences (cross-device sync for authenticated users)
  const { pinnedVoices, togglePinnedVoice } = useUserPreferences();

  // Voice preview audio playback
  const { api } = useApi();
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null); // "model:voice" key
  const sentenceIdxRef = useRef(0);
  const requestIdRef = useRef(0);

  const playPreview = useCallback(async (modelSlug: string, voiceSlug: string) => {
    const key = `${modelSlug}:${voiceSlug}`;
    const currentRequestId = ++requestIdRef.current;

    // Stop current preview if any
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      URL.revokeObjectURL(previewAudioRef.current.src);
      previewAudioRef.current = null;
    }

    // If clicking same voice that's playing, just stop
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

      // Ignore stale response if user clicked another voice
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

  // Default subscribers to Cloud on first load
  useEffect(() => {
    if (subLoading) return;
    if (canUseCloudKokoro && value.model === "kokoro") {
      const newSelection: VoiceSelection = { ...value, model: "kokoro-server" };
      onChange(newSelection);
      setVoiceSelection(newSelection);
    }
  }, [canUseCloudKokoro, subLoading]); // Only run when subscription state resolves

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

  const toggleInworldLangExpanded = (lang: InworldLanguageCode) => {
    setExpandedInworldLangs(prev => {
      const next = new Set(prev);
      if (next.has(lang)) {
        next.delete(lang);
      } else {
        next.add(lang);
      }
      return next;
    });
  };

  // Track model type for tab logic
  const isKokoroServer = value.model === "kokoro-server";
  const isKokoroModel = value.model === "kokoro" || value.model === "kokoro-server";
  const isInworldMax = value.model === INWORLD_MAX_SLUG;
  const activeTab = isKokoroModel ? "kokoro" : "inworld";

  const handleVoiceSelect = (voiceSlug: string) => {
    // Preserve current model variant when selecting voice
    let model: ModelType;
    if (activeTab === "kokoro") {
      model = isKokoroServer ? "kokoro-server" : "kokoro";
    } else {
      model = isInworldMax ? INWORLD_MAX_SLUG : INWORLD_SLUG;
    }
    const newSelection: VoiceSelection = {
      ...value,
      model,
      voiceSlug,
    };
    onChange(newSelection);
    setVoiceSelection(newSelection);
    setOpen(false);
  };

  const handleModelChange = (tab: string) => {
    // When switching tabs, select default voice for that model
    let defaultVoice: string;
    let model: ModelType;

    if (tab === "kokoro") {
      defaultVoice = "af_heart";
      model = isKokoroServer ? "kokoro-server" : "kokoro";
    } else {
      defaultVoice = inworldVoices.length > 0 ? inworldVoices[0].slug : "Ashley";
      model = isInworldMax ? INWORLD_MAX_SLUG : INWORLD_SLUG;
    }

    const newSelection: VoiceSelection = { model, voiceSlug: defaultVoice };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  const handleKokoroSourceToggle = () => {
    const newModel: ModelType = isKokoroServer ? "kokoro" : "kokoro-server";

    // When switching to Local, auto-switch to English voice if current voice isn't English
    let voiceSlug = value.voiceSlug;
    if (newModel === "kokoro") {
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
    // Mark as non-urgent transition so UI stays responsive during cache clearing
    startTransition(() => {
      onChange(newSelection);
    });
    setVoiceSelection(newSelection);
  };

  const handleInworldModelToggle = () => {
    const newModel: ModelType = isInworldMax ? INWORLD_SLUG : INWORLD_MAX_SLUG;
    const newSelection: VoiceSelection = { ...value, model: newModel };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  // Get display name for current selection
  let currentVoiceName: string;
  if (isKokoroModel) {
    currentVoiceName = KOKORO_VOICES.find(v => v.index === value.voiceSlug)?.name ?? value.voiceSlug;
  } else {
    currentVoiceName = inworldVoices.find(v => v.slug === value.voiceSlug)?.name ?? value.voiceSlug;
  }

  let modelLabel: string;
  if (isKokoroModel) {
    modelLabel = `Kokoro${isKokoroServer ? "" : " (Local)"}`;
  } else {
    modelLabel = isInworldMax ? "Inworld Max" : "Inworld";
  }

  // Local mode only supports English (browser WASM limitation)
  const englishOnly = !isKokoroServer;
  const isEnglishLang = (lang: KokoroLanguageCode) => lang === "a" || lang === "b";

  // Memoize computed values to prevent unnecessary re-renders
  const kokoroVoiceGroups = useMemo(() => groupKokoroVoicesByLanguage(KOKORO_VOICES), []);
  const inworldVoiceGroups = useMemo(() => groupInworldVoicesByLanguage(inworldVoices), [inworldVoices]);

  // Pinned voices filtered for Local mode
  const pinnedKokoro = useMemo(
    () => KOKORO_VOICES.filter(v => pinnedVoices.includes(v.index) && (!englishOnly || isEnglishLang(v.language))),
    [pinnedVoices, englishOnly]
  );
  const pinnedInworld = useMemo(() => inworldVoices.filter(v => pinnedVoices.includes(v.slug)), [inworldVoices, pinnedVoices]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-9 gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <span className="font-medium">{modelLabel}</span>
          <span className="text-muted-foreground">·</span>
          <span>{currentVoiceName}</span>
          <ChevronDown className="h-4 w-4 ml-0.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-96 p-0" align="start">
        <Tabs value={activeTab} onValueChange={handleModelChange}>
          <TabsList className="w-full h-11 rounded-none border-b">
            <TabsTrigger value="kokoro" className="flex-1 text-sm py-2.5">Kokoro</TabsTrigger>
            <TabsTrigger value="inworld" className="flex-1 text-sm py-2.5">Inworld</TabsTrigger>
          </TabsList>

          <TabsContent value="kokoro" className="m-0 max-h-[28rem] overflow-y-auto">
            {/* Local/Cloud toggle */}
            <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
              <div className="flex items-center gap-1.5">
                <span className="text-sm text-muted-foreground">Run on</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p><strong>Local:</strong> English voices only.</p>
                    <p><strong>Cloud:</strong> All available languages and voices.</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex rounded-md border bg-background">
                <button
                  onClick={() => isKokoroServer && handleKokoroSourceToggle()}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-l-md transition-colors ${
                    !isKokoroServer ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
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

            {/* Language sections (non-English hidden in Local mode via CSS to avoid flicker) */}
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

          <TabsContent value="inworld" className="m-0 max-h-[28rem] overflow-y-auto">
            {/* Model toggle: TTS-1.5 vs TTS-1.5-Max */}
            <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
              <div className="flex items-center gap-1.5">
                <span className="text-sm text-muted-foreground">Quality</span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button className="text-muted-foreground hover:text-foreground">
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p>TTS-1.5-Max uses a larger model for more natural speech and better multilingual pronunciation. Uses 2× your voice quota.</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex rounded-md border bg-background">
                <button
                  onClick={() => isInworldMax && handleInworldModelToggle()}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-l-md transition-colors ${
                    !isInworldMax ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  TTS-1.5
                </button>
                <button
                  onClick={() => !isInworldMax && handleInworldModelToggle()}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-r-md transition-colors ${
                    isInworldMax ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  TTS-1.5-Max
                </button>
              </div>
            </div>

            {inworldLoading ? (
              <div className="flex items-center justify-center py-8 text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                <span className="text-sm">Loading voices...</span>
              </div>
            ) : (
              <>
                {/* Starred section */}
                {pinnedInworld.length > 0 && (
                  <div className="border-b">
                    <div className="px-4 py-2 text-sm font-medium text-muted-foreground">Starred</div>
                    {pinnedInworld.map(voice => (
                      <VoiceRow
                        key={voice.slug}
                        name={voice.name}
                        flag={INWORLD_LANGUAGE_INFO[voice.lang]?.flag}
                        detail={voice.description ?? undefined}
                        isPinned={true}
                        isSelected={value.voiceSlug === voice.slug}
                        isPlaying={previewingVoice === `${INWORLD_SLUG}:${voice.slug}`}
                        onSelect={() => handleVoiceSelect(voice.slug)}
                        onPinToggle={() => togglePinnedVoice(voice.slug)}
                        onPreviewClick={() => playPreview(INWORLD_SLUG, voice.slug)}
                      />
                    ))}
                  </div>
                )}

                {/* Language sections */}
                {inworldVoiceGroups.map(group => (
                  <Collapsible
                    key={group.language}
                    open={expandedInworldLangs.has(group.language)}
                    onOpenChange={() => toggleInworldLangExpanded(group.language)}
                    className="border-b last:border-b-0"
                  >
                    <CollapsibleTrigger className="flex w-full items-center gap-2 px-4 py-2.5 text-sm font-medium hover:bg-accent">
                      <ChevronRight className={`h-4 w-4 transition-transform ${expandedInworldLangs.has(group.language) ? "rotate-90" : ""}`} />
                      <span>{group.flag}</span>
                      <span className="flex-1 text-left">{group.label}</span>
                      <span className="text-muted-foreground">({group.voices.length})</span>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      {group.voices.map(voice => (
                        <VoiceRow
                          key={voice.slug}
                          name={voice.name}
                          detail={voice.description ?? undefined}
                          isPinned={pinnedVoices.includes(voice.slug)}
                          isSelected={value.voiceSlug === voice.slug}
                          isPlaying={previewingVoice === `${INWORLD_SLUG}:${voice.slug}`}
                          onSelect={() => handleVoiceSelect(voice.slug)}
                          onPinToggle={() => togglePinnedVoice(voice.slug)}
                          onPreviewClick={() => playPreview(INWORLD_SLUG, voice.slug)}
                        />
                      ))}
                    </CollapsibleContent>
                  </Collapsible>
                ))}
              </>
            )}
          </TabsContent>
        </Tabs>
      </PopoverContent>
    </Popover>
  );
}

interface VoiceRowProps {
  name: string;
  flag?: string; // language flag for starred section
  detail?: string; // voice description
  isHighQuality?: boolean; // for Kokoro A/B tier
  gender?: "Female" | "Male"; // for Kokoro
  isPinned: boolean;
  isSelected: boolean;
  isPlaying?: boolean; // preview is playing
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
  // Custom comparison: ignore function props since they're recreated every render
  return prev.name === next.name &&
    prev.flag === next.flag &&
    prev.detail === next.detail &&
    prev.isHighQuality === next.isHighQuality &&
    prev.gender === next.gender &&
    prev.isPinned === next.isPinned &&
    prev.isSelected === next.isSelected &&
    prev.isPlaying === next.isPlaying;
});
