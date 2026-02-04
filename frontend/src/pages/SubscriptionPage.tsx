import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Loader2, ArrowLeft, Check, Clock } from "lucide-react";

type PlanTier = "free" | "basic" | "plus" | "max";
type BillingInterval = "monthly" | "yearly";

interface Plan {
  tier: PlanTier;
  name: string;
  server_kokoro_characters: number | null;
  premium_voice_characters: number | null;
  ocr_tokens: number | null;
  price_cents_monthly: number;
  price_cents_yearly: number;
  trial_days: number;
}

interface SubscriptionInfo {
  status: "active" | "trialing" | "past_due" | "canceled" | "incomplete";
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  cancel_at: string | null;
  is_canceling: boolean;
  grace_tier: PlanTier | null;
  grace_until: string | null;
}

interface UsageSummary {
  plan: { tier: PlanTier; name: string };
  subscribed_tier: PlanTier;
  subscription: SubscriptionInfo | null;
  limits: {
    server_kokoro_characters: number | null;
    premium_voice_characters: number | null;
    ocr_tokens: number | null;
  };
  usage: {
    server_kokoro_characters: number;
    premium_voice_characters: number;
    ocr_tokens: number;
  };
  extra_balances?: {
    rollover_tokens: number;
    rollover_voice_chars: number;
    purchased_tokens: number;
    purchased_voice_chars: number;
  };
  period: { start: string; end: string } | null;
}

const TIER_ORDER: PlanTier[] = ["free", "basic", "plus", "max"];

const tipLink = (text: string, hash: string) => (
  <a href={`/tips#${hash}`} className="underline decoration-dotted underline-offset-2 decoration-muted-foreground/50 hover:decoration-foreground">{text}</a>
);

const PLAN_FEATURES: Record<PlanTier, React.ReactNode[]> = {
  free: [tipLink("Kokoro TTS (local, English)", "local-tts"), "100 documents"],
  basic: ["Unlimited Kokoro TTS", "1,000 documents", tipLink("~500 AI-transformed pages*", "ai-transform"), tipLink("Unused quota accumulates**", "billing"), "Cancel anytime during trial"],
  plus: ["Everything in Basic", tipLink("~20 hrs premium voices*", "premium-voices"), tipLink("~1,000 AI-transformed pages*", "ai-transform"), "Cancel anytime during trial"],
  max: ["Everything in Plus", tipLink("~60 hrs premium voices*", "premium-voices"), tipLink("~1,500 AI-transformed pages*", "ai-transform")],
};

const SubscriptionPage = () => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const navigate = useNavigate();

  const [plans, setPlans] = useState<Plan[]>([]);
  const [subscription, setSubscription] = useState<UsageSummary | null>(null);
  const [interval, setInterval] = useState<BillingInterval>("monthly");
  const [isLoading, setIsLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthReady) return;

    const fetchData = async () => {
      try {
        const [plansRes, subRes] = await Promise.all([
          api.get<Plan[]>("/v1/billing/plans"),
          isAnonymous ? null : api.get<UsageSummary>("/v1/users/me/subscription"),
        ]);
        setPlans(plansRes.data);
        if (subRes) {
          setSubscription(subRes.data);
        }
      } catch (error) {
        console.error("Failed to fetch subscription data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [api, isAuthReady, isAnonymous]);

  const handleSubscribe = async (tier: PlanTier) => {
    if (isAnonymous) {
      localStorage.setItem("returnAfterSignIn", "/subscription");
      navigate("/handler/signin");
      return;
    }

    setActionLoading(tier);
    try {
      const response = await api.post<{ checkout_url: string }>("/v1/billing/subscribe", {
        tier,
        interval,
      });
      window.location.href = response.data.checkout_url;
    } catch (error) {
      console.error("Failed to create checkout session:", error);
      setActionLoading(null);
    }
  };

  const handleManageSubscription = async () => {
    setActionLoading("portal");
    try {
      const response = await api.post<{ portal_url: string }>("/v1/billing/portal");
      window.location.href = response.data.portal_url;
    } catch (error) {
      console.error("Failed to open billing portal:", error);
      setActionLoading(null);
    }
  };

  const formatPrice = (cents: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "EUR",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(cents / 100);
  };

  const formatNumber = (n: number | null, isLimit = false): string => {
    if (n === null) return "Unlimited";
    if (n === 0) return isLimit ? "Not included" : "0";
    const abs = Math.abs(n);
    const sign = n < 0 ? "-" : "";
    if (abs >= 1_000_000) {
      const m = abs / 1_000_000;
      return sign + (m % 1 === 0 ? `${m}M` : `${m.toFixed(1)}M`);
    }
    if (abs >= 1_000) {
      return sign + `${Math.round(abs / 1_000)}K`;
    }
    return n.toLocaleString();
  };

  const getUsagePercent = (used: number, limit: number | null): number => {
    if (limit === null || limit === 0) return 0;
    return Math.min(100, (used / limit) * 100);
  };

  const getDaysRemaining = (endDate: string): number => {
    const end = new Date(endDate);
    const now = new Date();
    return Math.max(0, Math.ceil((end.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)));
  };

  const currentTier = subscription?.subscribed_tier ?? "free";
  const isCanceled = subscription?.subscription?.status === "canceled";
  const isSubscribed = !!subscription?.subscription && !isCanceled;
  const isTrialing = subscription?.subscription?.status === "trialing";
  const isCanceling = subscription?.subscription?.is_canceling && !isCanceled;
  const cancelAt = subscription?.subscription?.cancel_at;
  const graceTier = subscription?.subscription?.grace_tier;
  const graceUntil = subscription?.subscription?.grace_until;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const sortedPlans = [...plans].sort(
    (a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier)
  );

  return (
    <div className="max-w-[1400px] mx-auto py-8 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back
      </Button>

      {/* Current Plan & Usage - only show for subscribed users */}
      {!isAnonymous && isSubscribed && subscription && (
        <Card className="mb-6">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  {subscription.subscribed_tier.charAt(0).toUpperCase() + subscription.subscribed_tier.slice(1)} Plan
                  {isTrialing && (
                    <span className="text-sm font-normal text-primary bg-primary/10 px-2 py-0.5 rounded-full flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      Trial
                    </span>
                  )}
                  {(isCanceling || isCanceled) && (
                    <span className="text-sm font-normal text-destructive bg-destructive/10 px-2 py-0.5 rounded-full">
                      {isCanceled ? "Canceled" : "Canceling"}
                    </span>
                  )}
                  {graceTier && !isCanceling && !isCanceled && (
                    <span className="text-sm font-normal text-amber-600 bg-amber-100 dark:bg-amber-900/30 dark:text-amber-400 px-2 py-0.5 rounded-full flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {graceTier.charAt(0).toUpperCase() + graceTier.slice(1)} access
                    </span>
                  )}
                </CardTitle>
                <CardDescription>
                  {isCanceling
                    ? `Access until ${new Date(cancelAt || subscription.subscription!.current_period_end).toLocaleDateString()}`
                    : isTrialing
                    ? `Trial ends in ${getDaysRemaining(subscription.subscription!.current_period_end)} days`
                    : graceTier && graceUntil
                    ? `${graceTier.charAt(0).toUpperCase() + graceTier.slice(1)} access until ${new Date(graceUntil).toLocaleDateString()}`
                    : `Renews ${new Date(subscription.subscription!.current_period_end).toLocaleDateString()}`}
                </CardDescription>
              </div>
              {isSubscribed && (
                <Button
                  variant="outline"
                  onClick={handleManageSubscription}
                  disabled={actionLoading !== null}
                >
                  {actionLoading === "portal" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "Manage"
                  )}
                </Button>
              )}
            </div>
          </CardHeader>

          {/* Usage bars - only show for subscribed users with limits */}
          {isSubscribed && subscription.period && (
            <CardContent className="space-y-4">
              {subscription.limits.premium_voice_characters !== null &&
                subscription.limits.premium_voice_characters > 0 && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className="cursor-help">
                        <div className="flex justify-between text-sm mb-1.5">
                          <span>Premium Voice</span>
                          <span className="text-muted-foreground">
                            {formatNumber(subscription.usage.premium_voice_characters)} /{" "}
                            {formatNumber(subscription.limits.premium_voice_characters, true)}
                          </span>
                        </div>
                        <Progress
                          value={getUsagePercent(
                            subscription.usage.premium_voice_characters,
                            subscription.limits.premium_voice_characters
                          )}
                        />
                        {(() => {
                          const extra = (subscription.extra_balances?.rollover_voice_chars ?? 0) + (subscription.extra_balances?.purchased_voice_chars ?? 0);
                          if (extra === 0) return null;
                          return (
                            <p className={`text-sm mt-0.5 text-right ${extra > 0 ? "text-accent-success" : "text-accent-warning"}`}>
                              {extra > 0 ? "+" : ""}{formatNumber(extra)}
                            </p>
                          );
                        })()}
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="bottom" className="text-xs">
                      <div className="space-y-0.5">
                        <p>Subscription: {formatNumber(subscription.usage.premium_voice_characters)} / {formatNumber(subscription.limits.premium_voice_characters)}</p>
                        {(subscription.extra_balances?.rollover_voice_chars ?? 0) !== 0 && (
                          <p>
                            Rollover: {(subscription.extra_balances?.rollover_voice_chars ?? 0) > 0 ? "+" : ""}{formatNumber(subscription.extra_balances?.rollover_voice_chars ?? 0)}
                          </p>
                        )}
                        {(subscription.extra_balances?.purchased_voice_chars ?? 0) > 0 && (
                          <p>Top-up: +{formatNumber(subscription.extra_balances?.purchased_voice_chars ?? 0)}</p>
                        )}
                      </div>
                    </TooltipContent>
                  </Tooltip>
                )}

              {subscription.limits.ocr_tokens !== null && subscription.limits.ocr_tokens > 0 && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="cursor-help">
                      <div className="flex justify-between text-sm mb-1.5">
                        <span>AI Transform</span>
                        <span className="text-muted-foreground">
                          {formatNumber(subscription.usage.ocr_tokens)} /{" "}
                          {formatNumber(subscription.limits.ocr_tokens, true)}
                        </span>
                      </div>
                      <Progress
                        value={getUsagePercent(subscription.usage.ocr_tokens, subscription.limits.ocr_tokens)}
                      />
                      {(() => {
                        const extra = (subscription.extra_balances?.rollover_tokens ?? 0) + (subscription.extra_balances?.purchased_tokens ?? 0);
                        if (extra === 0) return null;
                        return (
                          <p className={`text-sm mt-0.5 text-right ${extra > 0 ? "text-accent-success" : "text-accent-warning"}`}>
                            {extra > 0 ? "+" : ""}{formatNumber(extra)}
                          </p>
                        );
                      })()}
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="text-xs">
                    <div className="space-y-0.5">
                      <p>Subscription: {formatNumber(subscription.usage.ocr_tokens)} / {formatNumber(subscription.limits.ocr_tokens)}</p>
                      {(subscription.extra_balances?.rollover_tokens ?? 0) !== 0 && (
                        <p>
                          Rollover: {(subscription.extra_balances?.rollover_tokens ?? 0) > 0 ? "+" : ""}{formatNumber(subscription.extra_balances?.rollover_tokens ?? 0)}
                        </p>
                      )}
                      {(subscription.extra_balances?.purchased_tokens ?? 0) > 0 && (
                        <p>Top-up: +{formatNumber(subscription.extra_balances?.purchased_tokens ?? 0)}</p>
                      )}
                    </div>
                  </TooltipContent>
                </Tooltip>
              )}
            </CardContent>
          )}
        </Card>
      )}

      {/* Plan Selection */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 className="text-2xl font-semibold">Available Plans</h2>
        <Tabs value={interval} onValueChange={(v) => setInterval(v as BillingInterval)}>
          <TabsList>
            <TabsTrigger value="monthly">Monthly</TabsTrigger>
            <TabsTrigger value="yearly">
              Yearly
              <span className="ml-1.5 text-sm text-primary">Save 25%</span>
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {isAnonymous && (
        <p className="text-muted-foreground mb-4">
          <a href="/handler/signin" className="underline hover:text-foreground">Sign in</a> to subscribe to a plan
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-6">
        {sortedPlans.map((plan) => {
          const isCurrent = plan.tier === currentTier;
          const isUpgrade = TIER_ORDER.indexOf(plan.tier) > TIER_ORDER.indexOf(currentTier);

          return (
            <Card
              key={plan.tier}
              className={isCurrent ? "border-primary/50 bg-primary/5" : ""}
            >
              <CardHeader className="pb-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-xl">{plan.name}</CardTitle>
                  {isCurrent && (
                    <span className="text-sm bg-primary text-primary-foreground px-2.5 py-1 rounded-full">
                      Current
                    </span>
                  )}
                </div>
                <div className="mt-3">
                  {plan.price_cents_monthly === 0 ? (
                    <>
                      <span className="text-4xl font-bold">€0</span>
                      <span className="text-lg text-muted-foreground">/mo</span>
                      <div className="text-muted-foreground mt-1 h-5"></div>
                    </>
                  ) : (
                    <>
                      <span className="text-4xl font-bold">
                        {formatPrice(interval === "yearly" ? Math.round(plan.price_cents_yearly / 12) : plan.price_cents_monthly)}
                      </span>
                      <span className="text-lg text-muted-foreground">/mo</span>
                      <div className="text-muted-foreground mt-1 h-5">
                        {interval === "yearly" && `${formatPrice(plan.price_cents_yearly)}/year`}
                      </div>
                    </>
                  )}
                </div>
              </CardHeader>

              <CardContent className="flex-1">
                <ul className="space-y-3">
                  {PLAN_FEATURES[plan.tier].map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-2.5">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>

              <CardFooter>
                {plan.tier === "free" ? (
                  <Button variant="outline" className="w-full" disabled>
                    {isCurrent ? "Current Plan" : "Free"}
                  </Button>
                ) : isCurrent ? (
                  <Button variant="outline" className="w-full" disabled>
                    Current Plan
                  </Button>
                ) : (
                  <Button
                    className="w-full"
                    variant={isUpgrade ? "default" : "outline"}
                    onClick={() => {
                      if (!isSubscribed) {
                        handleSubscribe(plan.tier);
                      } else {
                        handleManageSubscription();
                      }
                    }}
                    disabled={actionLoading !== null}
                  >
                    {actionLoading === plan.tier || (isSubscribed && isUpgrade && actionLoading === "portal") ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : isUpgrade ? (
                      plan.trial_days > 0 && !isSubscribed ? (
                        `Start ${plan.trial_days}-day trial`
                      ) : (
                        "Upgrade"
                      )
                    ) : (
                      "Downgrade"
                    )}
                  </Button>
                )}
              </CardFooter>
            </Card>
          );
        })}
      </div>

      {/* Value Comparison Table */}
      <div className="mt-10 max-w-3xl mx-auto">
        <h3 className="text-lg font-medium text-center mb-4 text-muted-foreground">Value Comparison</h3>
        <div className="border rounded-lg overflow-hidden overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-2 py-2 text-left font-medium"></th>
                <th className="px-2 py-2 text-center font-medium">Basic Mo.</th>
                <th className="px-2 py-2 text-center font-medium">Basic Yr.</th>
                <th className="px-2 py-2 text-center font-medium">Plus Mo.</th>
                <th className="px-2 py-2 text-center font-medium">Plus Yr.</th>
                <th className="px-2 py-2 text-center font-medium">Max Mo.</th>
                <th className="px-2 py-2 text-center font-medium">Max Yr.</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              <tr>
                <td className="pl-2 pr-0 py-2 font-medium text-muted-foreground">Price</td>
                <td className="px-2 py-2 text-center">€10/mo</td>
                <td className="px-2 py-2 text-center">€7.5/mo eff.</td>
                <td className="px-2 py-2 text-center">€20/mo</td>
                <td className="px-2 py-2 text-center">€15/mo eff.</td>
                <td className="px-2 py-2 text-center">€40/mo</td>
                <td className="px-2 py-2 text-center">€30/mo eff.</td>
              </tr>
              <tr>
                <td className="pl-2 pr-0 py-2 font-medium text-muted-foreground">Premium Voice</td>
                <td className="px-2 py-2 text-center text-muted-foreground">—</td>
                <td className="px-2 py-2 text-center text-muted-foreground">—</td>
                <td className="px-2 py-2 text-center">1M</td>
                <td className="px-2 py-2 text-center">1M</td>
                <td className="px-2 py-2 text-center">3M</td>
                <td className="px-2 py-2 text-center">3M</td>
              </tr>
              <tr>
                <td className="pl-2 pr-0 py-2 font-medium text-muted-foreground">chars/€</td>
                <td className="px-2 py-2 text-center text-muted-foreground">—</td>
                <td className="px-2 py-2 text-center text-muted-foreground">—</td>
                <td className="px-2 py-2 text-center">50k</td>
                <td className="px-2 py-2 text-center">67k <span className="text-xs text-accent-success">+33%</span></td>
                <td className="px-2 py-2 text-center">75k <span className="text-xs text-accent-success">+50%</span></td>
                <td className="px-2 py-2 text-center">100k <span className="text-xs text-accent-success">+100%</span></td>
              </tr>
              <tr>
                <td className="pl-2 pr-0 py-2 font-medium text-muted-foreground">AI Tokens</td>
                <td className="px-2 py-2 text-center">5M</td>
                <td className="px-2 py-2 text-center">5M</td>
                <td className="px-2 py-2 text-center">10M</td>
                <td className="px-2 py-2 text-center">10M</td>
                <td className="px-2 py-2 text-center">15M</td>
                <td className="px-2 py-2 text-center">15M</td>
              </tr>
              <tr>
                <td className="pl-2 pr-0 py-2 font-medium text-muted-foreground">tokens/€</td>
                <td className="px-2 py-2 text-center">500k</td>
                <td className="px-2 py-2 text-center">667k <span className="text-xs text-accent-success">+33%</span></td>
                <td className="px-2 py-2 text-center">500k</td>
                <td className="px-2 py-2 text-center">667k <span className="text-xs text-accent-success">+33%</span></td>
                <td className="px-2 py-2 text-center">375k</td>
                <td className="px-2 py-2 text-center">500k</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <p className="mt-8 text-center text-sm text-muted-foreground">
        *Estimates vary by content and voice. TTS-1.5-Max uses 2× voice quota.
        <br />
        **Capped at 1M voice chars / 10M AI transformation tokens.
        <br />
        Fair use applies. Paid subscriptions are non-refundable. See <a href="/terms" className="underline hover:text-foreground">Terms</a>.
      </p>
    </div>
  );
};

export default SubscriptionPage;
