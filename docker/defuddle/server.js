import Fastify from "fastify";
import { JSDOM, VirtualConsole } from "jsdom";
import { Defuddle } from "defuddle/node";

const app = Fastify({ bodyLimit: 50 * 1024 * 1024 });

app.get("/health", async () => ({ status: "ok" }));

app.post("/extract", async (request, reply) => {
  const { html, url } = request.body;
  if (!html) {
    return reply.code(400).send({ error: "html field required" });
  }

  // Build our own JSDOM instance without resources: 'usable' to avoid
  // fetching external stylesheets (causes timeouts on pages with slow CDNs).
  const dom = new JSDOM(html, {
    url: url || undefined,
    pretendToBeVisual: true,
    includeNodeLocations: true,
    virtualConsole: new VirtualConsole().sendTo(console, { omitJSDOMErrors: true }),
  });

  const result = await Defuddle(dom, url || undefined, { markdown: true });

  return {
    markdown: result.content,
    title: result.title || null,
    description: result.description || null,
    author: result.author || null,
    published: result.published || null,
    domain: result.domain || null,
    wordCount: result.wordCount || 0,
  };
});

const port = parseInt(process.env.PORT || "8080");
app.listen({ port, host: "0.0.0.0" }).then(() => {
  console.log(`defuddle sidecar listening on :${port}`);
});
