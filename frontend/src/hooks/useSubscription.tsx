import { createContext, useContext, useEffect, useState, type FC, type PropsWithChildren } from "react";
import { useApi } from "@/api";

type PlanTier = "free" | "voice" | "basic" | "plus" | "max";

interface SubscriptionState {
  tier: PlanTier;
  hasActivePlan: boolean;
  canUseCloudKokoro: boolean;
  billingEnabled: boolean;
  isLoading: boolean;
}

const SubscriptionContext = createContext<SubscriptionState>({
  tier: "free",
  hasActivePlan: false,
  canUseCloudKokoro: false,
  billingEnabled: true,
  isLoading: true,
});

interface SubscriptionResponse {
  billing_enabled?: boolean;
  plan: { tier: PlanTier };
  subscription: { status: string } | null;
}

export const SubscriptionProvider: FC<PropsWithChildren> = ({ children }) => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const [state, setState] = useState<SubscriptionState>({
    tier: "free",
    hasActivePlan: false,
    canUseCloudKokoro: false,
    billingEnabled: true,
    isLoading: true,
  });

  useEffect(() => {
    if (!isAuthReady) return;

    if (isAnonymous) {
      setState({ tier: "free", hasActivePlan: false, canUseCloudKokoro: false, billingEnabled: true, isLoading: false });
      return;
    }

    api.get<SubscriptionResponse>("/v1/users/me/subscription")
      .then(({ data }) => {
        if (data.billing_enabled === false) {
          setState({
            tier: "max",
            hasActivePlan: true,
            canUseCloudKokoro: true,
            billingEnabled: false,
            isLoading: false,
          });
          return;
        }

        const tier = data.plan.tier;
        const hasActive = data.subscription !== null &&
          ["active", "trialing"].includes(data.subscription.status);
        const canCloud = tier !== "free";
        setState({
          tier,
          hasActivePlan: hasActive,
          canUseCloudKokoro: canCloud,
          billingEnabled: true,
          isLoading: false,
        });
      })
      .catch((err) => {
        console.error("Failed to fetch subscription:", err);
        setState({ tier: "free", hasActivePlan: false, canUseCloudKokoro: false, billingEnabled: true, isLoading: false });
      });
  }, [api, isAuthReady, isAnonymous]);

  return (
    <SubscriptionContext.Provider value={state}>
      {children}
    </SubscriptionContext.Provider>
  );
};

export function useSubscription(): SubscriptionState {
  return useContext(SubscriptionContext);
}
