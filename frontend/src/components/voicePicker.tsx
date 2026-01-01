import { useState, useEffect } from "react";
import { ChevronDown, Star, ChevronRight, Monitor, Cloud, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Slider } from "@/components/ui/slider";
import {
  type VoiceSelection,
  type ModelType,
  type KokoroLanguageCode,
  type InworldLanguageCode,
  KOKORO_VOICES,
  HIGGS_PRESETS,
  HIGGS_SCENES,
  LANGUAGE_INFO,
  INWORLD_LANGUAGE_INFO,
  groupKokoroVoicesByLanguage,
  groupInworldVoicesByLanguage,
  isHighQualityVoice,
  setVoiceSelection,
  getPinnedVoices,
  togglePinnedVoice,
} from "@/lib/voiceSelection";
import { useInworldVoices } from "@/hooks/useInworldVoices";

interface VoicePickerProps {
  value: VoiceSelection;
  onChange: (selection: VoiceSelection) => void;
}

export function VoicePicker({ value, onChange }: VoicePickerProps) {
  const [open, setOpen] = useState(false);
  const [pinnedVoices, setPinnedVoices] = useState<string[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // Track which language sections are expanded (user manages, we just remember)
  const [expandedKokoroLangs, setExpandedKokoroLangs] = useState<Set<KokoroLanguageCode>>(new Set(["a"]));
  const [expandedInworldLangs, setExpandedInworldLangs] = useState<Set<InworldLanguageCode>>(new Set(["en"]));

  // Fetch Inworld voices from API
  const { voices: inworldVoices, isLoading: inworldLoading } = useInworldVoices();

  useEffect(() => {
    setPinnedVoices(getPinnedVoices());
  }, []);

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

  const handlePinToggle = (slug: string) => {
    const newPinned = togglePinnedVoice(slug);
    setPinnedVoices(newPinned);
  };

  // Track model type for tab logic
  const isKokoroServer = value.model === "kokoro-server";
  const isKokoroModel = value.model === "kokoro" || value.model === "kokoro-server";
  const isInworldModel = value.model === "inworld" || value.model === "inworld-max";
  const isInworldMax = value.model === "inworld-max";
  const activeTab = isKokoroModel ? "kokoro" : isInworldModel ? "inworld" : "higgs";

  const handleVoiceSelect = (voiceSlug: string) => {
    // Preserve current model variant when selecting voice
    let model: ModelType;
    if (activeTab === "kokoro") {
      model = isKokoroServer ? "kokoro-server" : "kokoro";
    } else if (activeTab === "inworld") {
      model = isInworldMax ? "inworld-max" : "inworld";
    } else {
      model = "higgs";
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
    } else if (tab === "inworld") {
      defaultVoice = inworldVoices.length > 0 ? inworldVoices[0].slug : "Ashley";
      model = isInworldMax ? "inworld-max" : "inworld";
    } else {
      defaultVoice = "en-man";
      model = "higgs";
    }

    const newSelection: VoiceSelection = {
      model,
      voiceSlug: defaultVoice,
      temperature: tab === "higgs" ? value.temperature ?? 0.3 : undefined,
      scene: tab === "higgs" ? value.scene : undefined,
    };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  const handleKokoroSourceToggle = () => {
    const newModel: ModelType = isKokoroServer ? "kokoro" : "kokoro-server";
    const newSelection: VoiceSelection = {
      ...value,
      model: newModel,
    };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  const handleInworldModelToggle = () => {
    const newModel: ModelType = isInworldMax ? "inworld" : "inworld-max";
    const newSelection: VoiceSelection = {
      ...value,
      model: newModel,
    };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  const handleTemperatureChange = (temp: number) => {
    const newSelection = { ...value, temperature: temp };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  const handleSceneChange = (scene: string) => {
    const newSelection = { ...value, scene };
    onChange(newSelection);
    setVoiceSelection(newSelection);
  };

  // Get display name for current selection
  let currentVoiceName: string;
  if (isKokoroModel) {
    currentVoiceName = KOKORO_VOICES.find(v => v.index === value.voiceSlug)?.name ?? value.voiceSlug;
  } else if (isInworldModel) {
    currentVoiceName = inworldVoices.find(v => v.slug === value.voiceSlug)?.name ?? value.voiceSlug;
  } else {
    currentVoiceName = HIGGS_PRESETS.find(p => p.slug === value.voiceSlug)?.name ?? value.voiceSlug;
  }

  let modelLabel: string;
  if (isKokoroModel) {
    modelLabel = `Kokoro${isKokoroServer ? " (Cloud)" : ""}`;
  } else if (isInworldModel) {
    modelLabel = isInworldMax ? "Inworld Max" : "Inworld";
  } else {
    modelLabel = "HIGGS";
  }

  const kokoroVoiceGroups = groupKokoroVoicesByLanguage(KOKORO_VOICES);
  const inworldVoiceGroups = groupInworldVoicesByLanguage(inworldVoices);

  // Get pinned voices for current model
  const pinnedKokoro = KOKORO_VOICES.filter(v => pinnedVoices.includes(v.index));
  const pinnedHiggs = HIGGS_PRESETS.filter(p => pinnedVoices.includes(p.slug));
  const pinnedInworld = inworldVoices.filter(v => pinnedVoices.includes(v.slug));

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
            <TabsTrigger value="higgs" className="flex-1 text-sm py-2.5">HIGGS</TabsTrigger>
          </TabsList>

          <TabsContent value="kokoro" className="m-0 max-h-[28rem] overflow-y-auto">
            {/* Local/Cloud toggle */}
            <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
              <span className="text-sm text-muted-foreground">Run on</span>
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
                    onSelect={() => handleVoiceSelect(voice.index)}
                    onPinToggle={() => handlePinToggle(voice.index)}
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
                className="border-b last:border-b-0"
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
                      onSelect={() => handleVoiceSelect(voice.index)}
                      onPinToggle={() => handlePinToggle(voice.index)}
                    />
                  ))}
                </CollapsibleContent>
              </Collapsible>
            ))}
          </TabsContent>

          <TabsContent value="inworld" className="m-0 max-h-[28rem] overflow-y-auto">
            {/* Model toggle: inworld vs inworld-max */}
            <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
              <span className="text-sm text-muted-foreground">Quality</span>
              <div className="flex rounded-md border bg-background">
                <button
                  onClick={() => isInworldMax && handleInworldModelToggle()}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-l-md transition-colors ${
                    !isInworldMax ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  TTS-1
                </button>
                <button
                  onClick={() => !isInworldMax && handleInworldModelToggle()}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-r-md transition-colors ${
                    isInworldMax ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  TTS-1-Max
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
                        onSelect={() => handleVoiceSelect(voice.slug)}
                        onPinToggle={() => handlePinToggle(voice.slug)}
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
                          onSelect={() => handleVoiceSelect(voice.slug)}
                          onPinToggle={() => handlePinToggle(voice.slug)}
                        />
                      ))}
                    </CollapsibleContent>
                  </Collapsible>
                ))}
              </>
            )}
          </TabsContent>

          <TabsContent value="higgs" className="m-0 max-h-[28rem] overflow-y-auto">
            {/* Pinned section */}
            {pinnedHiggs.length > 0 && (
              <div className="border-b">
                <div className="px-4 py-2 text-sm font-medium text-muted-foreground">Pinned</div>
                {pinnedHiggs.map(preset => (
                  <VoiceRow
                    key={preset.slug}
                    name={preset.name}
                    detail={preset.description}
                    isPinned={true}
                    isSelected={value.voiceSlug === preset.slug}
                    onSelect={() => handleVoiceSelect(preset.slug)}
                    onPinToggle={() => handlePinToggle(preset.slug)}
                  />
                ))}
              </div>
            )}

            {/* Presets */}
            <div className="border-b">
              <div className="px-4 py-2 text-sm font-medium text-muted-foreground">Presets</div>
              {HIGGS_PRESETS.map(preset => (
                <VoiceRow
                  key={preset.slug}
                  name={preset.name}
                  detail={preset.description}
                  isPinned={pinnedVoices.includes(preset.slug)}
                  isSelected={value.voiceSlug === preset.slug}
                  onSelect={() => handleVoiceSelect(preset.slug)}
                  onPinToggle={() => handlePinToggle(preset.slug)}
                />
              ))}
            </div>

            {/* Advanced settings */}
            <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
              <CollapsibleTrigger asChild>
                <button className="flex w-full items-center gap-2 px-4 py-2.5 text-sm font-medium text-muted-foreground hover:bg-accent">
                  <ChevronRight className={`h-4 w-4 transition-transform ${advancedOpen ? "rotate-90" : ""}`} />
                  Advanced Settings
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent className="px-4 pb-4 space-y-4">
                {/* Temperature */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Temperature</span>
                    <span className="font-mono tabular-nums">{(value.temperature ?? 0.3).toFixed(1)}</span>
                  </div>
                  <Slider
                    value={[value.temperature ?? 0.3]}
                    min={0.1}
                    max={1.0}
                    step={0.1}
                    onValueChange={([v]) => handleTemperatureChange(v)}
                  />
                </div>

                {/* Scene */}
                <div className="space-y-2">
                  <span className="text-sm text-muted-foreground">Scene</span>
                  <select
                    value={value.scene ?? HIGGS_SCENES[0].value}
                    onChange={(e) => handleSceneChange(e.target.value)}
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  >
                    {HIGGS_SCENES.map(scene => (
                      <option key={scene.value} value={scene.value}>{scene.label}</option>
                    ))}
                  </select>
                </div>
              </CollapsibleContent>
            </Collapsible>
          </TabsContent>
        </Tabs>
      </PopoverContent>
    </Popover>
  );
}

interface VoiceRowProps {
  name: string;
  flag?: string; // language flag for starred section
  detail?: string; // for HIGGS
  isHighQuality?: boolean; // for Kokoro A/B tier
  gender?: "Female" | "Male"; // for Kokoro
  isPinned: boolean;
  isSelected: boolean;
  onSelect: () => void;
  onPinToggle: () => void;
}

function VoiceRow({ name, flag, detail, isHighQuality, gender, isPinned, isSelected, onSelect, onPinToggle }: VoiceRowProps) {
  return (
    <div
      className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-accent ${isSelected ? "bg-accent" : ""}`}
      onClick={onSelect}
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          onPinToggle();
        }}
        className="text-muted-foreground hover:text-foreground"
      >
        <Star className={`h-4 w-4 ${isPinned ? "fill-current text-yellow-500" : ""}`} />
      </button>
      <span className="text-base flex-1 flex items-center gap-2">
        {flag && <span className="text-sm">{flag}</span>}
        {name}
        {isHighQuality && <span className="text-sm" title="High quality">✨</span>}
      </span>
      {gender && <span className="text-sm text-muted-foreground">{gender === "Female" ? "♀" : "♂"}</span>}
      {detail && <span className="text-sm text-muted-foreground">{detail}</span>}
    </div>
  );
}
