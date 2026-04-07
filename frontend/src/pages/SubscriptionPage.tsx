import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2, ArrowLeft, Check, Clock } from "lucide-react";
import { UsageBreakdown } from "@/components/UsageBreakdown";

type PlanTier = "free" | "voice" | "basic" | "plus" | "max";
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
  schedule_pending: boolean;
}

const TIER_ORDER: PlanTier[] = ["free", "voice", "basic", "plus", "max"];

const tipLink = (text: string, hash: string) => (
  <a href={`/tips#${hash}`} className="underline decoration-dotted underline-offset-2 decoration-muted-foreground/50 hover:decoration-foreground">{text}</a>
);

const PLAN_FEATURES: Record<string, React.ReactNode[]> = {
  free: [tipLink("Kokoro TTS (local, English)", "local-tts"), "100 documents"],
  voice: ["Unlimited Kokoro TTS (server)", "500 documents", tipLink("Unused quota accumulates**", "billing"), "Cancel anytime during trial"],
  basic: ["Unlimited Kokoro TTS (server)", "1,000 documents", tipLink("~500 AI-transformed pages*", "ai-transform"), tipLink("Unused quota accumulates**", "billing"), "Cancel anytime during trial"],
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
      localStorage.setItem("returnAfterSignIn", "/pricing");
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
  const schedulePending = subscription?.schedule_pending && !isCanceling && !isCanceled;

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
    <div className="max-w-[1000px] mx-auto py-8 px-6">
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
                  {subscription.plan.name} Plan
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
                  {schedulePending && (
                    <span className="text-sm font-normal text-amber-600 bg-amber-500/10 px-2 py-0.5 rounded-full flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      Plan change scheduled
                    </span>
                  )}
                </CardTitle>
                <CardDescription>
                  {isCanceling
                    ? `Access until ${new Date(cancelAt || subscription.subscription!.current_period_end).toLocaleDateString()}`
                    : schedulePending
                    ? `Plan change takes effect ${new Date(subscription.subscription!.current_period_end).toLocaleDateString()} · Manage in billing portal`
                    : isTrialing
                    ? `Trial ends in ${getDaysRemaining(subscription.subscription!.current_period_end)} days`
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

          {isSubscribed && subscription.period && (
            <CardContent>
              <UsageBreakdown
                usage={subscription.usage}
                limits={subscription.limits}
                extraBalances={subscription.extra_balances}
                formatNumber={formatNumber}
              />
            </CardContent>
          )}
        </Card>
      )}

      {/* Plan Selection */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 className="text-2xl font-semibold">Plans</h2>
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

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        {sortedPlans.map((plan) => {
          const isCurrent = plan.tier === currentTier;
          const isUpgrade = TIER_ORDER.indexOf(plan.tier) > TIER_ORDER.indexOf(currentTier);
          const features = PLAN_FEATURES[plan.tier];
          if (!features) return null;

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
                  {features.map((feature, idx) => (
                    <li key={idx} className="flex items-start gap-2.5">
                      <Check className="h-5 w-5 text-primary shrink-0 mt-0.5" />
                      <span>{feature}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>

              <CardFooter>
                {plan.tier === "free" ? (
                  <Button variant="outline" className="w-full dark:border-muted-foreground/25" disabled>
                    {isCurrent ? "Current Plan" : "Free"}
                  </Button>
                ) : isCurrent ? (
                  <Button variant="outline" className="w-full dark:border-muted-foreground/25" disabled>
                    Current Plan
                  </Button>
                ) : (
                  <Button
                    className={cn("w-full", !isUpgrade && "dark:border-muted-foreground/25 dark:hover:bg-muted-foreground/10")}
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

      <p className="mt-8 text-center text-sm text-muted-foreground">
        *Estimates vary by content complexity.
        <br />
        **Capped at 10M AI transformation tokens.
        <br />
        Fair use applies. Paid subscriptions are non-refundable. See <a href="/terms" className="underline hover:text-foreground">Terms</a>.
      </p>
    </div>
  );
};

export default SubscriptionPage;
