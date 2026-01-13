import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

const TermsPage = () => {
  const navigate = useNavigate();

  return (
    <div className="container max-w-3xl mx-auto py-12 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back
      </Button>

      <h1 className="text-4xl font-bold mb-2">Terms of Service</h1>
      <p className="text-muted-foreground mb-8">Last updated: January 8, 2026</p>

      <div className="prose prose-neutral dark:prose-invert max-w-none space-y-8">
        <section>
          <h2 className="text-2xl font-semibold mb-3">1. Agreement to Terms</h2>
          <p>By using Yapit (yapit.md), you agree to these terms. If you don't agree, don't use the service.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">2. Description of Service</h2>
          <p className="mb-3">Yapit is a text-to-speech service. You upload or paste text, we convert it to audio. We offer:</p>
          <ul className="list-disc pl-6 space-y-1">
            <li>Free tier: Browser-based TTS (no account required)</li>
            <li>Paid tiers: Premium voices, OCR for PDFs, additional features</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">3. Accounts</h2>
          <ul className="list-disc pl-6 space-y-1">
            <li>One account per person</li>
            <li>You must provide accurate information</li>
            <li>You're responsible for your account security</li>
            <li>We may terminate accounts for violations</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">4. Subscriptions & Billing</h2>

          <h3 className="text-lg font-medium mt-4 mb-2">Billing</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Payments processed by Stripe (merchant of record)</li>
            <li>Prices shown include applicable taxes</li>
            <li>Billing occurs at start of each period</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Cancellation</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Cancel anytime via account settings or Stripe portal</li>
            <li>Cancellation takes effect at end of current billing period</li>
            <li>No prorated refunds for partial periods</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">EU 14-Day Withdrawal Right</h3>
          <p className="mb-3">If you're in the EU/EEA, you normally have a legal right to cancel distance contracts within 14 days without giving a reason.</p>

          <p className="mb-2"><strong>Waiver for immediate digital services:</strong> By subscribing to Yapit, you:</p>
          <ol className="list-decimal pl-6 space-y-1 mb-3">
            <li>Expressly consent to immediate access to the service</li>
            <li>Acknowledge that this immediate access waives your 14-day withdrawal right</li>
          </ol>

          <p className="mb-3">Once you begin using the service (generating or streaming audio), you are no longer entitled to a refund under the EU withdrawal right.</p>

          <p className="mb-3"><strong>Free trials:</strong> You can cancel a free trial at any time without charge. The waiver above applies only when you begin a paid subscription.</p>

          <p>This waiver does not affect any statutory rights that cannot be waived under applicable law.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">5. Usage Limits</h2>
          <p>Each plan has usage limits (listening hours, OCR pages). Limits reset monthly. We enforce limits — if you hit them, you'll need to wait or upgrade.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">6. User Content</h2>
          <ul className="list-disc pl-6 space-y-1 mb-4">
            <li>You retain ownership of content you upload</li>
            <li>You own the audio output generated from your content</li>
            <li>You grant us a license to process your content for the service</li>
            <li>You must have rights to content you upload</li>
          </ul>

          <p className="mb-2"><strong>Prohibited uses:</strong></p>
          <ul className="list-disc pl-6 space-y-1 mb-3">
            <li>Content you don't have rights to reproduce</li>
            <li>Impersonating real people without consent</li>
            <li>Generating fraudulent or deceptive content</li>
            <li>Any illegal purpose</li>
          </ul>

          <p>We may remove content and terminate accounts that violate these terms.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">7. Service Changes</h2>
          <ul className="list-disc pl-6 space-y-1">
            <li>Features and available voices may change</li>
            <li>Premium tiers provide access to premium-quality voices as available, not specific voice models</li>
            <li>We'll give 30 days notice for material changes when possible</li>
            <li>Pricing changes: 30 days notice</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">8. Disclaimers</h2>
          <p className="mb-3">The service is provided "as is." We don't guarantee:</p>
          <ul className="list-disc pl-6 space-y-1">
            <li>100% uptime or availability</li>
            <li>Perfect audio quality, accuracy, or pronunciation</li>
            <li>Consistent speed or output quality</li>
            <li>That specific voices will always be available</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Document Processing</h3>
          <p className="mb-3">We use AI models to extract and transform text from uploaded documents (PDFs, images). These models may:</p>
          <ul className="list-disc pl-6 space-y-1 mb-3">
            <li>Introduce minor errors or inaccuracies</li>
            <li>Imperfectly render mathematical notation, tables, or complex layouts</li>
            <li>Occasionally misinterpret or omit content</li>
            <li>Adapt visual layouts to improve readability</li>
          </ul>
          <p>While we strive for accuracy, the extracted text may not be identical to the original document. For critical content, verify against your source material.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">9. Limitation of Liability</h2>
          <p className="mb-3">Our total liability is limited to the amount you paid us in the 3 months before the claim. We're not liable for indirect damages, lost profits, or data loss.</p>
          <p>We implement reasonable security measures but cannot guarantee absolute security. We are not liable for unauthorized access to your data resulting from circumstances beyond our reasonable control, including security breaches. You acknowledge uploading content at your own risk.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">10. Indemnification</h2>
          <p>You agree to indemnify and hold us harmless from any claims, damages, or expenses (including legal fees) arising from your use of the service, your content, or your violation of these terms. This includes claims from third parties related to content you upload.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">11. Termination</h2>
          <p className="mb-3">We may terminate your account for:</p>
          <ul className="list-disc pl-6 space-y-1">
            <li>Violation of these terms</li>
            <li>Non-payment</li>
            <li>Extended inactivity</li>
            <li>At our discretion with 30 days notice</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">12. Governing Law</h2>
          <p>These terms are governed by Austrian law. Disputes will be resolved in Austrian courts, except where EU consumer protection law gives you rights in your home jurisdiction.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">13. Changes to Terms</h2>
          <p>We may update these terms. Continued use after changes = acceptance. Material changes get 30 days notice.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">14. Contact</h2>
          <p>Questions? Email <a href="mailto:yapit@mwolf.dev" className="text-primary hover:underline">yapit@mwolf.dev</a></p>
        </section>
      </div>
    </div>
  );
};

export default TermsPage;
