import { useState, useEffect } from "react";
import { ChevronDown, Star, ChevronRight, Monitor, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Slider } from "@/components/ui/slider";
import {
  type VoiceSelection,
  type ModelType,
  type KokoroLanguageCode,
  KOKORO_VOICES,
  HIGGS_PRESETS,
  HIGGS_SCENES,
  LANGUAGE_INFO,
  groupKokoroVoicesByLanguage,
  isHighQualityVoice,
  setVoiceSelection,
  getPinnedVoices,
  togglePinnedVoice,
} from "@/lib/voiceSelection";

interface VoicePickerProps {
  value: VoiceSelection;
  onChange: (selection: VoiceSelection) => void;
}

export function VoicePicker({ value, onChange }: VoicePickerProps) {
  const [open, setOpen] = useState(false);
  const [pinnedVoices, setPinnedVoices] = useState<string[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  // Track which language sections are expanded (user manages, we just remember)
  const [expandedLanguages, setExpandedLanguages] = useState<Set<KokoroLanguageCode>>(new Set(["a"]));

  useEffect(() => {
    setPinnedVoices(getPinnedVoices());
  }, []);

  const toggleLanguageExpanded = (lang: KokoroLanguageCode) => {
    setExpandedLanguages(prev => {
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

  // Track whether Kokoro should use server (vs browser)
  const isKokoroServer = value.model === "kokoro-server";
  const isKokoroModel = value.model === "kokoro" || value.model === "kokoro-server";
  const activeTab = isKokoroModel ? "kokoro" : "higgs";

  const handleVoiceSelect = (voiceSlug: string) => {
    // Preserve current Kokoro source (browser/server) when selecting voice
    const model = activeTab === "kokoro" ? (isKokoroServer ? "kokoro-server" : "kokoro") : "higgs";
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
    const defaultVoice = tab === "kokoro" ? "af_heart" : "en-man";
    // Preserve server preference when switching to Kokoro tab
    const model: ModelType = tab === "higgs" ? "higgs" : (isKokoroServer ? "kokoro-server" : "kokoro");
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
  const currentVoiceName = isKokoroModel
    ? KOKORO_VOICES.find(v => v.index === value.voiceSlug)?.name ?? value.voiceSlug
    : HIGGS_PRESETS.find(p => p.slug === value.voiceSlug)?.name ?? value.voiceSlug;

  const modelLabel = isKokoroModel
    ? `Kokoro${isKokoroServer ? " (Server)" : ""}`
    : "HIGGS";

  const voiceGroups = groupKokoroVoicesByLanguage(KOKORO_VOICES);

  // Get pinned voices for current model
  const pinnedKokoro = KOKORO_VOICES.filter(v => pinnedVoices.includes(v.index));
  const pinnedHiggs = HIGGS_PRESETS.filter(p => pinnedVoices.includes(p.slug));

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs text-muted-foreground hover:text-foreground">
          <span className="font-medium">{modelLabel}</span>
          <span className="text-muted-foreground">·</span>
          <span>{currentVoiceName}</span>
          <ChevronDown className="h-3 w-3 ml-0.5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Tabs value={activeTab} onValueChange={handleModelChange}>
          <TabsList className="w-full rounded-none border-b">
            <TabsTrigger value="kokoro" className="flex-1">Kokoro</TabsTrigger>
            <TabsTrigger value="higgs" className="flex-1">HIGGS</TabsTrigger>
          </TabsList>

          <TabsContent value="kokoro" className="m-0 max-h-80 overflow-y-auto">
            {/* Browser/Server toggle */}
            <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
              <span className="text-xs text-muted-foreground">Run on</span>
              <div className="flex rounded-md border bg-background">
                <button
                  onClick={() => isKokoroServer && handleKokoroSourceToggle()}
                  className={`flex items-center gap-1 px-2 py-1 text-xs rounded-l-md transition-colors ${
                    !isKokoroServer ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Monitor className="h-3 w-3" />
                  Browser
                </button>
                <button
                  onClick={() => !isKokoroServer && handleKokoroSourceToggle()}
                  className={`flex items-center gap-1 px-2 py-1 text-xs rounded-r-md transition-colors ${
                    isKokoroServer ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Server className="h-3 w-3" />
                  Server
                </button>
              </div>
            </div>
            {/* Starred section */}
            {pinnedKokoro.length > 0 && (
              <div className="border-b">
                <div className="px-3 py-1.5 text-xs font-medium text-muted-foreground">Starred</div>
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
            {voiceGroups.map(group => (
              <Collapsible
                key={group.language}
                open={expandedLanguages.has(group.language)}
                onOpenChange={() => toggleLanguageExpanded(group.language)}
                className="border-b last:border-b-0"
              >
                <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium hover:bg-accent">
                  <ChevronRight className={`h-3 w-3 transition-transform ${expandedLanguages.has(group.language) ? "rotate-90" : ""}`} />
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

          <TabsContent value="higgs" className="m-0 max-h-80 overflow-y-auto">
            {/* Pinned section */}
            {pinnedHiggs.length > 0 && (
              <div className="border-b">
                <div className="px-3 py-1.5 text-xs font-medium text-muted-foreground">Pinned</div>
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
              <div className="px-3 py-1.5 text-xs font-medium text-muted-foreground">Presets</div>
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
                <button className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-accent">
                  <ChevronRight className={`h-3 w-3 transition-transform ${advancedOpen ? "rotate-90" : ""}`} />
                  Advanced Settings
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent className="px-3 pb-3 space-y-3">
                {/* Temperature */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
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
                <div className="space-y-1.5">
                  <span className="text-xs text-muted-foreground">Scene</span>
                  <select
                    value={value.scene ?? HIGGS_SCENES[0].value}
                    onChange={(e) => handleSceneChange(e.target.value)}
                    className="w-full rounded-md border bg-background px-2 py-1 text-xs"
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
      className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-accent ${isSelected ? "bg-accent" : ""}`}
      onClick={onSelect}
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          onPinToggle();
        }}
        className="text-muted-foreground hover:text-foreground"
      >
        <Star className={`h-3 w-3 ${isPinned ? "fill-current text-yellow-500" : ""}`} />
      </button>
      <span className="text-sm flex-1 flex items-center gap-1.5">
        {flag && <span className="text-xs">{flag}</span>}
        {name}
        {isHighQuality && <span className="text-xs" title="High quality">✨</span>}
      </span>
      {gender && <span className="text-xs text-muted-foreground">{gender === "Female" ? "♀" : "♂"}</span>}
      {detail && <span className="text-xs text-muted-foreground">{detail}</span>}
    </div>
  );
}
