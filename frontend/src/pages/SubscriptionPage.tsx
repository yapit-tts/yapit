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

const CHARS_PER_HOUR = 61200; // ~17 chars/sec * 3600 sec/hr

type PlanTier = "free" | "basic" | "plus" | "max";
type BillingInterval = "monthly" | "yearly";

interface Plan {
  tier: PlanTier;
  name: string;
  server_kokoro_characters: number | null;
  premium_voice_characters: number | null;
  ocr_pages: number | null;
  price_cents_monthly: number;
  price_cents_yearly: number;
  trial_days: number;
}

interface SubscriptionInfo {
  status: "active" | "trialing" | "past_due" | "canceled" | "incomplete";
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
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
    ocr_pages: number | null;
  };
  usage: {
    server_kokoro_characters: number;
    premium_voice_characters: number;
    ocr_pages: number;
  };
  period: { start: string; end: string } | null;
}

const TIER_ORDER: PlanTier[] = ["free", "basic", "plus", "max"];

const PLAN_FEATURES: Record<PlanTier, string[]> = {
  free: ["Local TTS (English only)", "Unlimited documents"],
  basic: ["Everything in Free", "Unlimited Kokoro (all languages)", "500 OCR pages/month", "Cancel anytime during trial"],
  plus: ["Everything in Basic", "~20 hrs premium voices/month*", "1,500 OCR pages/month", "Cancel anytime during trial"],
  max: ["Everything in Plus", "~50 hrs premium voices/month*", "3,000 OCR pages/month"],
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

  const formatCharactersAsHours = (chars: number | null, isLimit = false): string => {
    if (chars === null) return "Unlimited";
    if (chars === 0) return isLimit ? "Not included" : "0 hrs";
    const hours = chars / CHARS_PER_HOUR;
    if (hours < 1) {
      const minutes = Math.round(hours * 60);
      return `~${minutes} min`;
    }
    return `~${Math.round(hours)} hrs`;
  };

  const formatCharactersExact = (chars: number): string => {
    if (chars >= 1_000_000) {
      return `${(chars / 1_000_000).toFixed(2)}M chars`;
    }
    return `${chars.toLocaleString()} chars`;
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
  const isCanceling = subscription?.subscription?.cancel_at_period_end && !isCanceled;
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
    <div className="container max-w-7xl mx-auto py-8 px-6">
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
                  {isTrialing
                    ? `Trial ends in ${getDaysRemaining(subscription.subscription!.current_period_end)} days`
                    : isCanceling
                    ? `Access until ${new Date(subscription.subscription!.current_period_end).toLocaleDateString()}`
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
                            {formatCharactersAsHours(subscription.usage.premium_voice_characters)} /{" "}
                            {formatCharactersAsHours(subscription.limits.premium_voice_characters, true)}
                          </span>
                        </div>
                        <Progress
                          value={getUsagePercent(
                            subscription.usage.premium_voice_characters,
                            subscription.limits.premium_voice_characters
                          )}
                        />
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">
                      <p>{formatCharactersExact(subscription.usage.premium_voice_characters)} / {formatCharactersExact(subscription.limits.premium_voice_characters)}</p>
                      <p className="text-xs opacity-75">Hours are approximate (~17 chars/sec)</p>
                    </TooltipContent>
                  </Tooltip>
                )}

              {subscription.limits.ocr_pages !== null && subscription.limits.ocr_pages > 0 && (
                <div>
                  <div className="flex justify-between text-sm mb-1.5">
                    <span>OCR Pages</span>
                    <span className="text-muted-foreground">
                      {subscription.usage.ocr_pages.toLocaleString()} /{" "}
                      {subscription.limits.ocr_pages.toLocaleString()}
                    </span>
                  </div>
                  <Progress
                    value={getUsagePercent(subscription.usage.ocr_pages, subscription.limits.ocr_pages)}
                  />
                </div>
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
              <span className="ml-1.5 text-sm text-primary">Save up to 50%</span>
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {isAnonymous && (
        <p className="text-muted-foreground mb-4">
          Sign in to subscribe to a plan
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
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
                <th className="px-3 py-3 text-left font-medium"></th>
                <th className="px-3 py-3 text-center font-medium">Plus Monthly</th>
                <th className="px-3 py-3 text-center font-medium">Plus Yearly</th>
                <th className="px-3 py-3 text-center font-medium">Max Monthly</th>
                <th className="px-3 py-3 text-center font-medium">Max Yearly</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              <tr>
                <td className="px-3 py-2.5 font-medium text-muted-foreground">Price</td>
                <td className="px-3 py-2.5 text-center">€20/mo</td>
                <td className="px-3 py-2.5 text-center">€16/mo eff.</td>
                <td className="px-3 py-2.5 text-center">€40/mo</td>
                <td className="px-3 py-2.5 text-center">€20/mo eff.</td>
              </tr>
              <tr>
                <td className="px-3 py-2.5 font-medium text-muted-foreground">Chars</td>
                <td className="px-3 py-2.5 text-center">1.2M</td>
                <td className="px-3 py-2.5 text-center">1.2M</td>
                <td className="px-3 py-2.5 text-center">3M</td>
                <td className="px-3 py-2.5 text-center">3M</td>
              </tr>
              <tr>
                <td className="px-3 py-2.5 font-medium text-muted-foreground">chars/€</td>
                <td className="px-3 py-2.5 text-center">60k</td>
                <td className="px-3 py-2.5 text-center">
                  <span className="relative">
                    75k
                    <span className="absolute left-full ml-1 text-xs text-emerald-600 dark:text-emerald-400 whitespace-nowrap">+25%</span>
                  </span>
                </td>
                <td className="px-3 py-2.5 text-center">75k</td>
                <td className="px-3 py-2.5 text-center">
                  <span className="relative">
                    150k
                    <span className="absolute left-full ml-1 text-xs text-emerald-600 dark:text-emerald-400 whitespace-nowrap">+100%</span>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <p className="mt-8 text-center text-sm text-muted-foreground">
        *~20 hrs at 1× listening speed. TTS-1-Max uses 2× quota. Prices <em>include</em> VAT.
        <br />
        Paid subscriptions are non-refundable after service begins. See <a href="/terms" className="underline hover:text-foreground">Terms</a>.
      </p>
    </div>
  );
};

export default SubscriptionPage;
