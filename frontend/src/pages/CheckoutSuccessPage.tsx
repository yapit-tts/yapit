import { useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router";
import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

const CheckoutSuccessPage = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { api, isAuthReady } = useApi();

  const [status, setStatus] = useState<"loading" | "completed" | "pending" | "failed">("loading");
  const [credits, setCredits] = useState<number | null>(null);

  const sessionId = searchParams.get("session_id");

  useEffect(() => {
    if (!isAuthReady || !sessionId) return;

    const checkStatus = async () => {
      try {
        const response = await api.get<{ status: string; credits: number | null }>(
          `/v1/billing/checkout/${sessionId}/status`
        );

        if (response.data.status === "completed") {
          setStatus("completed");
          setCredits(response.data.credits);
        } else if (response.data.status === "failed") {
          setStatus("failed");
        } else {
          setStatus("pending");
          setTimeout(checkStatus, 2000);
        }
      } catch (error) {
        console.error("Failed to check status:", error);
        setStatus("failed");
      }
    };

    checkStatus();
  }, [api, isAuthReady, sessionId]);

  const formatCredits = (credits: number) => {
    return new Intl.NumberFormat("en-US").format(credits);
  };

  return (
    <div className="container max-w-lg mx-auto py-16 px-4">
      <Card>
        <CardHeader className="text-center">
          {status === "loading" || status === "pending" ? (
            <>
              <Loader2 className="h-12 w-12 animate-spin text-primary mx-auto mb-4" />
              <CardTitle>Processing payment...</CardTitle>
            </>
          ) : status === "completed" ? (
            <>
              <CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-4" />
              <CardTitle>Payment successful!</CardTitle>
            </>
          ) : (
            <>
              <XCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
              <CardTitle>Payment failed</CardTitle>
            </>
          )}
        </CardHeader>
        <CardContent className="text-center">
          {status === "completed" && credits && (
            <p className="text-lg mb-6">
              <span className="font-bold text-primary">{formatCredits(credits)}</span> credits
              have been added to your account.
            </p>
          )}
          {status === "pending" && (
            <p className="text-muted-foreground mb-6">
              Please wait while we confirm your payment...
            </p>
          )}
          {status === "failed" && (
            <p className="text-muted-foreground mb-6">
              Something went wrong. Please try again or contact support.
            </p>
          )}
          <div className="flex gap-4 justify-center">
            <Button variant="outline" onClick={() => navigate("/settings")}>
              View Settings
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
