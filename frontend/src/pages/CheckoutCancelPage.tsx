import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { XCircle } from "lucide-react";

const CheckoutCancelPage = () => {
  const navigate = useNavigate();

  return (
    <div className="container max-w-lg mx-auto py-16 px-4">
      <Card>
        <CardHeader className="text-center">
          <XCircle className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
          <CardTitle>Checkout cancelled</CardTitle>
        </CardHeader>
        <CardContent className="text-center">
          <p className="text-muted-foreground mb-6">
            Your purchase was cancelled. No charges were made.
          </p>
          <div className="flex gap-4 justify-center">
            <Button variant="outline" onClick={() => navigate("/settings")}>
              Back to Settings
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

export default CheckoutCancelPage;
