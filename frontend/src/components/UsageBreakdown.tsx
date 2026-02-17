import { useEffect, useRef, useState } from "react";
import { useApi } from "@/api";
import { Progress } from "@/components/ui/progress";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface VoiceUsageItem {
  voice_slug: string | null;
  voice_name: string | null;
  model_slug: string | null;
  total_chars: number;
  event_count: number;
}

interface DocumentUsageItem {
  document_id: string | null;
  document_title: string | null;
  content_hash: string;
  total_tokens: number;
  page_count: number;
}

interface BreakdownData {
  premium_voice: VoiceUsageItem[];
  ocr: DocumentUsageItem[];
}

interface UsageBarProps {
  label: string;
  used: number;
  limit: number;
  extraBalance: number;
  balanceDetail: React.ReactNode;
  breakdown: React.ReactNode | null;
  isLoading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  formatNumber: (n: number | null, isLimit?: boolean) => string;
}

function UsageBar({
  label,
  used,
  limit,
  extraBalance,
  balanceDetail,
  breakdown,
  isLoading,
  open,
  onOpenChange,
  formatNumber,
}: UsageBarProps) {
  const percent = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;

  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <CollapsibleTrigger asChild>
        <button className="w-full text-left cursor-pointer group">
          <div className="flex justify-between text-sm mb-1.5">
            <span className="flex items-center gap-1.5">
              {label}
              <ChevronDown
                className={cn(
                  "h-3.5 w-3.5 text-muted-foreground transition-transform duration-200",
                  open && "rotate-180",
                )}
              />
            </span>
            <span className="text-muted-foreground">
              {formatNumber(used)} / {formatNumber(limit, true)}
            </span>
          </div>
          <Progress value={percent} />
          {extraBalance !== 0 && (
            <p
              className={cn(
                "text-sm mt-0.5 text-right",
                extraBalance > 0 ? "text-accent-success" : "text-accent-warning",
              )}
            >
              {extraBalance > 0 ? "+" : ""}
              {formatNumber(extraBalance)}
            </p>
          )}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-3 space-y-2">
          <div className="text-xs text-muted-foreground">{balanceDetail}</div>
          {isLoading ? (
            <div className="flex justify-center py-3">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : (
            breakdown
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function VoiceBreakdownList({
  items,
  formatNumber,
}: {
  items: VoiceUsageItem[];
  formatNumber: (n: number | null) => string;
}) {
  if (items.length === 0)
    return <p className="text-xs text-muted-foreground py-2">No premium voice usage this period</p>;

  return (
    <div className="space-y-1">
      {items.map((item, i) => {
        const name = item.voice_name ?? item.voice_slug ?? "Other";
        const modelLabel =
          item.model_slug && item.voice_name ? ` (${item.model_slug})` : "";
        return (
          <div key={i} className="flex justify-between text-xs py-0.5">
            <span className="truncate mr-4">
              {name}
              <span className="text-muted-foreground">{modelLabel}</span>
            </span>
            <span className="text-muted-foreground shrink-0">
              {formatNumber(item.total_chars)} chars
            </span>
          </div>
        );
      })}
    </div>
  );
}

function DocumentBreakdownList({
  items,
  formatNumber,
}: {
  items: DocumentUsageItem[];
  formatNumber: (n: number | null) => string;
}) {
  if (items.length === 0)
    return <p className="text-xs text-muted-foreground py-2">No AI transform usage this period</p>;

  return (
    <div className="space-y-1">
      {items.map((item, i) => {
        const title = item.document_title ?? "Deleted document";
        return (
          <div key={i} className="flex justify-between text-xs py-0.5">
            <span className={cn("truncate mr-4", !item.document_title && "text-muted-foreground italic")}>
              {title}
            </span>
            <span className="text-muted-foreground shrink-0">
              {formatNumber(item.total_tokens)} tokens
              {item.page_count > 0 && (
                <span className="ml-1">({item.page_count} pg)</span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

interface UsageBreakdownProps {
  usage: {
    server_kokoro_characters: number;
    premium_voice_characters: number;
    ocr_tokens: number;
  };
  limits: {
    server_kokoro_characters: number | null;
    premium_voice_characters: number | null;
    ocr_tokens: number | null;
  };
  extraBalances?: {
    rollover_tokens: number;
    rollover_voice_chars: number;
    purchased_tokens: number;
    purchased_voice_chars: number;
  };
  formatNumber: (n: number | null, isLimit?: boolean) => string;
}

export function UsageBreakdown({ usage, limits, extraBalances, formatNumber }: UsageBreakdownProps) {
  const { api } = useApi();
  const [breakdown, setBreakdown] = useState<BreakdownData | null>(null);
  const [loading, setLoading] = useState(false);
  const fetched = useRef(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [ocrOpen, setOcrOpen] = useState(false);

  const shouldFetch = (voiceOpen || ocrOpen) && !fetched.current;

  useEffect(() => {
    if (!shouldFetch) return;
    fetched.current = true;
    setLoading(true);
    api
      .get<BreakdownData>("/v1/users/me/usage-breakdown")
      .then((res) => setBreakdown(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [shouldFetch, api]);

  const showVoice =
    limits.premium_voice_characters !== null && limits.premium_voice_characters > 0;
  const showOcr = limits.ocr_tokens !== null && limits.ocr_tokens > 0;

  if (!showVoice && !showOcr) return null;

  const voiceExtra =
    (extraBalances?.rollover_voice_chars ?? 0) + (extraBalances?.purchased_voice_chars ?? 0);
  const ocrExtra =
    (extraBalances?.rollover_tokens ?? 0) + (extraBalances?.purchased_tokens ?? 0);

  return (
    <div className="space-y-4">
      {showVoice && (
        <UsageBar
          label="Premium Voice"
          used={usage.premium_voice_characters}
          limit={limits.premium_voice_characters!}
          extraBalance={voiceExtra}
          balanceDetail={
            <BalanceDetail
              label="voice chars"
              used={usage.premium_voice_characters}
              limit={limits.premium_voice_characters!}
              rollover={extraBalances?.rollover_voice_chars ?? 0}
              purchased={extraBalances?.purchased_voice_chars ?? 0}
              formatNumber={formatNumber}
            />
          }
          breakdown={
            breakdown ? (
              <VoiceBreakdownList items={breakdown.premium_voice} formatNumber={formatNumber} />
            ) : null
          }
          isLoading={loading}
          open={voiceOpen}
          onOpenChange={setVoiceOpen}
          formatNumber={formatNumber}
        />
      )}

      {showOcr && (
        <UsageBar
          label="AI Transform"
          used={usage.ocr_tokens}
          limit={limits.ocr_tokens!}
          extraBalance={ocrExtra}
          balanceDetail={
            <BalanceDetail
              label="tokens"
              used={usage.ocr_tokens}
              limit={limits.ocr_tokens!}
              rollover={extraBalances?.rollover_tokens ?? 0}
              purchased={extraBalances?.purchased_tokens ?? 0}
              formatNumber={formatNumber}
            />
          }
          breakdown={
            breakdown ? (
              <DocumentBreakdownList items={breakdown.ocr} formatNumber={formatNumber} />
            ) : null
          }
          isLoading={loading}
          open={ocrOpen}
          onOpenChange={setOcrOpen}
          formatNumber={formatNumber}
        />
      )}
    </div>
  );
}

function BalanceDetail({
  label,
  used,
  limit,
  rollover,
  purchased,
  formatNumber,
}: {
  label: string;
  used: number;
  limit: number;
  rollover: number;
  purchased: number;
  formatNumber: (n: number | null) => string;
}) {
  return (
    <div className="space-y-0.5">
      <p>
        Subscription: {formatNumber(used)} / {formatNumber(limit)} {label}
      </p>
      {rollover !== 0 && (
        <p>
          Rollover: {rollover > 0 ? "+" : ""}
          {formatNumber(rollover)}
        </p>
      )}
      {purchased > 0 && <p>Top-up: +{formatNumber(purchased)}</p>}
    </div>
  );
}
