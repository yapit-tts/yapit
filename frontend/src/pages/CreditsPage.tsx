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
import { Loader2, Coins, ArrowLeft } from "lucide-react";

interface CreditPack {
  id: string;
  name: string;
  credits: number;
  price_cents: number;
  currency: string;
}

interface UserCredits {
  user_id: string;
  balance: string;
  total_purchased: string;
  total_used: string;
}

interface CreditTransaction {
  id: string;
  type: string;
  status: string;
  amount: string;
  description: string | null;
  created: string;
}

const CreditsPage = () => {
  const { api, isAuthReady, isAnonymous } = useApi();
  const navigate = useNavigate();

  const [packages, setPackages] = useState<CreditPack[]>([]);
  const [credits, setCredits] = useState<UserCredits | null>(null);
  const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [purchaseLoading, setPurchaseLoading] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthReady) return;

    const fetchData = async () => {
      try {
        const packagesRes = await api.get<CreditPack[]>("/v1/billing/packages");
        setPackages(packagesRes.data);

        if (!isAnonymous) {
          const [creditsRes, transactionsRes] = await Promise.all([
            api.get<UserCredits>("/v1/users/me/credits"),
            api.get<CreditTransaction[]>("/v1/users/me/transactions"),
          ]);
          setCredits(creditsRes.data);
          setTransactions(transactionsRes.data);
        }
      } catch (error) {
        console.error("Failed to fetch settings data:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [api, isAuthReady, isAnonymous]);

  const handlePurchase = async (packageId: string) => {
    if (isAnonymous) {
      navigate("/handler/signin");
      return;
    }

    setPurchaseLoading(packageId);
    try {
      const response = await api.post<{ checkout_url: string }>("/v1/billing/checkout", {
        package_id: packageId,
      });
      window.location.href = response.data.checkout_url;
    } catch (error) {
      console.error("Failed to create checkout session:", error);
      setPurchaseLoading(null);
    }
  };

  const formatPrice = (cents: number, currency: string) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency.toUpperCase(),
    }).format(cents / 100);
  };

  const formatCredits = (credits: number) => {
    return new Intl.NumberFormat("en-US").format(credits);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="container max-w-4xl mx-auto py-8 px-4">
      <Button
        variant="ghost"
        className="mb-6"
        onClick={() => navigate(-1)}
      >
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back
      </Button>

      <h1 className="text-3xl font-bold mb-8">Credits</h1>

      {/* Credit Balance */}
      {!isAnonymous && credits && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Coins className="h-5 w-5" />
              Credit Balance
            </CardTitle>
            <CardDescription>
              Your available credits for TTS synthesis
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-4xl font-bold text-primary">
              {formatCredits(parseFloat(credits.balance))}
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              1 credit = 1 second of audio
            </p>
          </CardContent>
        </Card>
      )}

      {/* Credit Packages */}
      <div className="mb-8">
        <h2 className="text-xl font-semibold mb-4">Buy Credits</h2>
        {isAnonymous && (
          <p className="text-sm text-muted-foreground mb-4">
            Sign in to purchase credits
          </p>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {packages.map((pack) => (
            <Card key={pack.id} className="flex flex-col">
              <CardHeader>
                <CardTitle>{pack.name}</CardTitle>
                <CardDescription>
                  {formatCredits(pack.credits)} credits
                </CardDescription>
              </CardHeader>
              <CardContent className="flex-1">
                <div className="text-3xl font-bold">
                  {formatPrice(pack.price_cents, pack.currency)}
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {(pack.price_cents / pack.credits * 10).toFixed(2)}¢ per 10 credits
                </p>
              </CardContent>
              <CardFooter>
                <Button
                  className="w-full"
                  onClick={() => handlePurchase(pack.id)}
                  disabled={purchaseLoading !== null}
                >
                  {purchaseLoading === pack.id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : isAnonymous ? (
                    "Sign in to buy"
                  ) : (
                    "Buy"
                  )}
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </div>

      {/* Transaction History */}
      {!isAnonymous && transactions.length > 0 && (
        <div>
          <h2 className="text-xl font-semibold mb-4">Transaction History</h2>
          <Card>
            <CardContent className="p-0">
              <div className="divide-y">
                {transactions.slice(0, 10).map((tx) => (
                  <div key={tx.id} className="flex justify-between items-center p-4">
                    <div>
                      <div className="font-medium flex items-center gap-2">
                        {tx.description || tx.type.replace(/_/g, " ")}
                        {tx.status !== "completed" && (
                          <span className="text-xs text-muted-foreground">
                            ({tx.status})
                          </span>
                        )}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {new Date(tx.created).toLocaleDateString()}
                      </div>
                    </div>
                    <div className={`font-mono ${
                      tx.status !== "completed" ? "text-muted-foreground" :
                      parseFloat(tx.amount) >= 0 ? "text-green-600" : "text-red-600"
                    }`}>
                      {parseFloat(tx.amount) >= 0 ? "+" : ""}{formatCredits(parseFloat(tx.amount))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};

export default CreditsPage;
