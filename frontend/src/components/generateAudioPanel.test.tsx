import { beforeAll, describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { GenerateAudioPanel } from "./generateAudioPanel";
import { KOKORO_SLUG } from "@/lib/voiceSelection";

const api = { get: vi.fn(() => Promise.resolve({ data: { uncached_characters: [0], plan_includes_voice: true, available_characters: null, running_job_document_id: null } })) };
vi.mock("@/api", () => ({ useApi: () => ({ api, isAnonymous: false }) }));

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    value: (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }),
  });
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("[]")));
});

describe("GenerateAudioPanel", () => {
  it("opens on the voice picker rather than the title's (i), whose note opens on keyboard focus", async () => {
    renderPanel();

    await screen.findByText("Generate in background");
    expect(document.activeElement).toHaveTextContent("Heart");
  });

  it("reaches Tick all before the voice picker on Tab", async () => {
    renderPanel();

    const tickAll = await screen.findByRole("button", { name: /tick all sections/i });
    const voicePicker = screen.getByRole("button", { name: /Heart/ });
    expect(tickAll.compareDocumentPosition(voicePicker) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

function renderPanel() {
  render(
    <MemoryRouter>
      <GenerateAudioPanel
        open
        onOpenChange={() => {}}
        documentId="doc"
        sections={[]}
        documentBlocks={[{ est_duration_ms: 1000 }]}
        expandedSections={new Set()}
        voiceSelection={{ model: KOKORO_SLUG, voiceSlug: "af_heart" }}
        onVoiceChange={() => {}}
        job={null}
        onStart={async () => null}
        onCancel={async () => {}}
        exportProgress={{}}
        onDownload={async () => {}}
      />
    </MemoryRouter>,
  );
}
