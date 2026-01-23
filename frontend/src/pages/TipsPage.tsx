const TipsPage = () => {
  return (
    <div className="container max-w-4xl mx-auto py-8 px-6">
      <h1 className="text-4xl font-bold mb-2">Tips</h1>
      <p className="text-lg text-muted-foreground mb-8">
        Get the most out of Yapit
      </p>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold mb-4">Accidentally closed the tab while processing?</h2>
        <p className="text-muted-foreground">
          Don't worry — your progress isn't lost. Pages that finished extracting are cached.
          When you retry, those pages load instantly and won't count toward your usage limit again.
        </p>
      </section>

      {/* TODO: Getting Started section */}
      {/* TODO: How billing works (subscription quota, rollover, negative balance/debt) */}
      {/* TODO: Document Preprocessing prompts */}
      {/* TODO: FAQ */}
    </div>
  );
};

export default TipsPage;
