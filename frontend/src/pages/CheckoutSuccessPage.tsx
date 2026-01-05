import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

interface SubscriptionSummary {
  plan: { tier: string; name: string };
  subscription: { status: string } | null;
}

const CheckoutSuccessPage = () => {
  const navigate = useNavigate();
  const { api, isAuthReady } = useApi();

  const [status, setStatus] = useState<"loading" | "success" | "failed">("loading");
  const [planName, setPlanName] = useState<string | null>(null);
  const [isTrialing, setIsTrialing] = useState(false);

  useEffect(() => {
    if (!isAuthReady) return;

    let attempts = 0;
    const maxAttempts = 15;

    const checkSubscription = async () => {
      try {
        const response = await api.get<SubscriptionSummary>("/v1/users/me/subscription");
        const sub = response.data;

        if (sub.subscription && (sub.subscription.status === "active" || sub.subscription.status === "trialing")) {
          setStatus("success");
          setPlanName(sub.plan.name);
          setIsTrialing(sub.subscription.status === "trialing");
          return;
        }

        attempts++;
        if (attempts < maxAttempts) {
          setTimeout(checkSubscription, 2000);
        } else {
          setStatus("failed");
        }
      } catch {
        attempts++;
        if (attempts < maxAttempts) {
          setTimeout(checkSubscription, 2000);
        } else {
          setStatus("failed");
        }
      }
    };

    checkSubscription();
  }, [api, isAuthReady]);

  return (
    <div className="container max-w-lg mx-auto py-16 px-4">
      <Card>
        <CardHeader className="text-center">
          {status === "loading" ? (
            <>
              <Loader2 className="h-12 w-12 animate-spin text-primary mx-auto mb-4" />
              <CardTitle>Activating your subscription...</CardTitle>
            </>
          ) : status === "success" ? (
            <>
              <CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-4" />
              <CardTitle>
                {isTrialing ? "Trial started!" : "Subscription activated!"}
              </CardTitle>
            </>
          ) : (
            <>
              <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
              <CardTitle>Something went wrong</CardTitle>
            </>
          )}
        </CardHeader>
        <CardContent className="text-center">
          {status === "success" && planName && (
            <p className="text-lg mb-6">
              You're now on the <span className="font-bold text-primary">{planName}</span> plan.
              {isTrialing && " Your trial has begun."}
            </p>
          )}
          {status === "loading" && (
            <p className="text-muted-foreground mb-6">
              Please wait while we confirm your subscription...
            </p>
          )}
          {status === "failed" && (
            <p className="text-muted-foreground mb-6">
              We couldn't confirm your subscription. It may still be processing.
              Check your subscription page or try again later.
            </p>
          )}
          <div className="flex gap-4 justify-center">
            <Button variant="outline" onClick={() => navigate("/subscription")}>
              View Subscription
            </Button>
            <Button onClick={() => navigate("/")}>
              Continue
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default CheckoutSuccessPage;
