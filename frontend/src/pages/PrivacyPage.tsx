import { useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

const PrivacyPage = () => {
  const navigate = useNavigate();

  return (
    <div className="container max-w-3xl mx-auto py-12 px-6">
      <Button variant="ghost" className="mb-8" onClick={() => navigate(-1)}>
        <ArrowLeft className="mr-2 h-5 w-5" />
        Back
      </Button>

      <h1 className="text-4xl font-bold mb-2">Privacy Policy</h1>
      <p className="text-muted-foreground mb-8">Last updated: February 18, 2026</p>

      <div className="prose prose-neutral dark:prose-invert max-w-none space-y-8">
        <section>
          <h2 className="text-2xl font-semibold mb-3">What We Collect</h2>

          <h3 className="text-lg font-medium mt-4 mb-2">Account information</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Email address</li>
            <li>Display name (if provided)</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Documents you upload</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Parsed text extracted from PDFs and files</li>
            <li>Stored as plain text in our database</li>
            <li>Original files are NOT stored — only the extracted text</li>
            <li>Document metadata (title, URL, page count)</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Audio</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Generated audio is cached temporarily</li>
            <li>Cache is evicted automatically based on usage patterns</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Usage data</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Text character counts and listening duration</li>
            <li>OCR page counts</li>
            <li>Feature usage (for billing limits)</li>
            <li>Performance metrics (latency, errors)</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Technical data</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>User ID (in server logs)</li>
            <li>Browser/device information</li>
            <li>Authentication tokens</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Browser storage (not cookies)</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li>Playback positions (localStorage)</li>
            <li>User preferences (speed, voice settings)</li>
            <li>These stay on your device</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">How We Use Your Data</h2>
          <ul className="list-disc pl-6 space-y-1">
            <li>To provide the service (TTS synthesis, OCR)</li>
            <li>To enforce usage limits</li>
            <li>To improve the service</li>
            <li>To communicate with you (support, important updates)</li>
          </ul>
          <p className="mt-3">An email address is required to create an account. Payment information is required for paid plans. Without these, we cannot provide the respective services. All other data collection (usage analytics, performance metrics) is necessary for service operation and is not optional.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Legal Basis (GDPR)</h2>
          <p className="mb-3">Under GDPR, we process your data based on:</p>
          <ul className="list-disc pl-6 space-y-1">
            <li><strong>Contract performance</strong>: Processing your documents and generating audio (Art. 6(1)(b))</li>
            <li><strong>Legitimate interest</strong>: Server logs for security, quality assurance, and debugging (Art. 6(1)(f))</li>
            <li><strong>Legal obligation</strong>: Retaining billing records as required by law (Art. 6(1)(c))</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Third Parties</h2>

          <h3 className="text-lg font-medium mt-4 mb-2">Your text content is sent to these APIs for processing:</h3>
          <ul className="list-disc pl-6 space-y-1 mb-3">
            <li><strong>InWorld</strong>: Premium voice synthesis (text blocks sent for audio generation)</li>
            <li><strong>Google (Gemini API)</strong>: AI document processing (PDF pages sent for text extraction when AI Transform is enabled). See <a href="https://ai.google.dev/gemini-api/terms" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Gemini API Terms</a>.</li>
            <li><strong>RunPod</strong>: Server-side TTS (text blocks sent for audio generation, if enabled)</li>
          </ul>
          <p className="mb-4">These APIs process your content to provide the service. They may process data in the United States. We don't control their data retention policies — refer to their respective privacy policies for details.</p>

          <h3 className="text-lg font-medium mt-4 mb-2">Payment processing:</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li><strong>Stripe</strong>: Payment processing as merchant of record (payment details, billing address)</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Email delivery:</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li><strong>Resend</strong>: Delivers verification and notification emails. Your email address is sent to Resend for delivery. Data stored in the US with GDPR-compliant safeguards (Standard Contractual Clauses, SOC 2 Type II, ISO 27001). See <a href="https://resend.com/legal/privacy-policy" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Resend Privacy Policy</a>.</li>
            <li><strong>Freestyle.sh</strong>: Renders email templates (no user data stored, just template processing).</li>
          </ul>

          <h3 className="text-lg font-medium mt-4 mb-2">Infrastructure:</h3>
          <ul className="list-disc pl-6 space-y-1">
            <li><strong>Hetzner</strong>: Hosting (data stored on their servers in Germany)</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Data Retention</h2>
          <ul className="list-disc pl-6 space-y-1">
            <li><strong>Account data</strong>: Until you delete your account</li>
            <li><strong>Documents</strong>: Until you delete them, or upon account deletion</li>
            <li><strong>Audio cache</strong>: Evicted based on usage, typically days to weeks</li>
            <li><strong>Logs</strong>: Retained as long as necessary for security, quality assurance, and debugging purposes, then deleted or anonymized</li>
            <li><strong>Usage records</strong>: Anonymized on account deletion, kept for analytics</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Your Rights (GDPR)</h2>
          <p className="mb-3">If you're in the EU/EEA, you have the right to:</p>
          <ul className="list-disc pl-6 space-y-1 mb-4">
            <li>Access your data</li>
            <li>Correct inaccurate data</li>
            <li>Delete your data ("right to be forgotten")</li>
            <li>Export your data (portability)</li>
            <li>Object to processing</li>
            <li>Restrict processing</li>
          </ul>
          <p className="mb-3">Your data (documents, audio, usage stats) is accessible directly in your account. For other requests, email <a href="mailto:yapit@mwolf.dev" className="text-primary hover:underline">yapit@mwolf.dev</a></p>
          <p>You also have the right to lodge a complaint with the Austrian data protection authority (<a href="https://www.dsb.gv.at" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">Datenschutzbehörde</a>).</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Account Deletion</h2>
          <p className="mb-3">You can delete your account in settings. This:</p>
          <ul className="list-disc pl-6 space-y-1">
            <li>Permanently deletes your documents and their audio</li>
            <li>Permanently deletes your preferences</li>
            <li>Anonymizes usage records (user ID replaced with hash, data patterns preserved for analytics)</li>
            <li>Cancels any active subscription</li>
            <li>Deletes your authentication data</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Cookies</h2>
          <p className="mb-3">We use <strong>only authentication cookies</strong> to keep you logged in. These are strictly necessary for the service to function.</p>
          <p className="mb-2"><strong>We do NOT use:</strong></p>
          <ul className="list-disc pl-6 space-y-1 mb-3">
            <li>Analytics cookies</li>
            <li>Tracking cookies</li>
            <li>Marketing cookies</li>
            <li>Third-party cookies</li>
          </ul>
          <p>No cookie consent banner is required because authentication cookies are exempt under EU ePrivacy Directive.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Data Security</h2>
          <p className="mb-3">We use reasonable measures to protect your data:</p>
          <ul className="list-disc pl-6 space-y-1 mb-4">
            <li>HTTPS everywhere</li>
            <li>Database access controls</li>
            <li>Regular backups</li>
          </ul>
          <p className="mb-4">Your documents are stored as plain text. While we have access controls, we (operators) can technically read your content. If this concerns you, don't upload sensitive documents.</p>
          <p><strong>Breach notification:</strong> In the event of a data breach affecting your personal data, we will notify the relevant authorities within 72 hours as required by GDPR, and notify affected users without undue delay.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Sensitive Content</h2>
          <p className="mb-3">You are responsible for the content you upload. Do not upload:</p>
          <ul className="list-disc pl-6 space-y-1 mb-3">
            <li>Confidential business information</li>
            <li>Personal data about others without consent</li>
            <li>Information subject to professional privilege</li>
            <li>Classified or restricted government documents</li>
          </ul>
          <p>We are not liable for any consequences of uploading sensitive content.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Children</h2>
          <p>Yapit is not intended for children under 16. We don't knowingly collect data from children.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Changes</h2>
          <p>We may update this policy. Material changes get 30 days notice.</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mb-3">Contact</h2>
          <p>Privacy questions? Email <a href="mailto:yapit@mwolf.dev" className="text-primary hover:underline">yapit@mwolf.dev</a></p>
        </section>
      </div>
    </div>
  );
};

export default PrivacyPage;
