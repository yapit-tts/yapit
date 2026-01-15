import { createContext, useContext, useEffect, useState, type FC, type PropsWithChildren } from "react";
import { useApi } from "@/api";

type PlanTier = "free" | "basic" | "plus" | "max";

interface SubscriptionState {
  tier: PlanTier;
  hasActivePlan: boolean;
  canUseCloudKokoro: boolean;  // Basic, Plus, Max
  canUseInworld: boolean;      // Plus, Max only
  isLoading: boolean;
}

const SubscriptionContext = createContext<SubscriptionState>({
  tier: "free",
  hasActivePlan: false,
  canUseCloudKokoro: false,
  canUseInworld: false,
  isLoading: true,
});

interface SubscriptionResponse {
  plan: { tier: PlanTier };
  subscription: { status: string } | null;
}

export const SubscriptionProvider: FC<PropsWithChildren> = ({ children }) => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const [state, setState] = useState<SubscriptionState>({
    tier: "free",
    hasActivePlan: false,
    canUseCloudKokoro: false,
    canUseInworld: false,
    isLoading: true,
  });

  useEffect(() => {
    if (!isAuthReady) return;

    if (isAnonymous) {
      setState({ tier: "free", hasActivePlan: false, canUseCloudKokoro: false, canUseInworld: false, isLoading: false });
      return;
    }

    api.get<SubscriptionResponse>("/v1/users/me/subscription")
      .then(({ data }) => {
        const tier = data.plan.tier;
        const hasActive = data.subscription !== null &&
          ["active", "trialing"].includes(data.subscription.status);
        const canCloud = tier !== "free";
        const canInworld = tier === "plus" || tier === "max";
        setState({
          tier,
          hasActivePlan: hasActive,
          canUseCloudKokoro: canCloud,
          canUseInworld: canInworld,
          isLoading: false,
        });
      })
      .catch((err) => {
        console.error("Failed to fetch subscription:", err);
        setState({ tier: "free", hasActivePlan: false, canUseCloudKokoro: false, canUseInworld: false, isLoading: false });
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
