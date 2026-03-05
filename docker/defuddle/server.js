import Fastify from "fastify";
import { Defuddle } from "defuddle/node";

const app = Fastify({ bodyLimit: 50 * 1024 * 1024 });

app.get("/health", async () => ({ status: "ok" }));

app.post("/extract", async (request, reply) => {
  const { html, url } = request.body;
  if (!html) {
    return reply.code(400).send({ error: "html field required" });
  }

  const result = await Defuddle(html, url || undefined, { markdown: true });

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
