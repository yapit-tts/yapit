import { Link } from "react-router";
import { FileQuestion } from "lucide-react";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center gap-6 text-muted-foreground bg-background">
      <FileQuestion className="h-20 w-20" />
      <h1 className="text-2xl font-semibold text-foreground">Page not found</h1>
      <p className="text-base text-center max-w-md">
        This is not the page you're looking for.
      </p>
      <Link
        to="/"
        className="text-lg text-primary hover:underline"
      >
        ← Back to home
      </Link>
    </div>
  );
}
