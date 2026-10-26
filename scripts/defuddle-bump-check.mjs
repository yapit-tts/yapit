#!/usr/bin/env node
/**
 * Checks a defuddle bump before it lands: that the new release is what kepano/defuddle's
 * release workflow built, and how its extraction differs from the old version's on the
 * pages in defuddle-ab-corpus.txt.
 *
 * Usage: node scripts/defuddle-bump-check.mjs <old-version> <new-version> [workdir]
 *
 * docker/defuddle/package-lock.json must already pin <new-version>. Writes the report to
 * <workdir>/report.md, and each page's HTML, both extractions and their diff to
 * <workdir>/ab/. Exits 1 when any check fails; a warning leaves the exit code alone.
 */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { cpSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");
const SERVICE = join(REPO, "docker/defuddle");
const CORPUS = join(REPO, "scripts/defuddle-ab-corpus.txt");
const UPSTREAM = "kepano/defuddle";
const RELEASE_WORKFLOW = ".github/workflows/release.yml";
const BROWSER_UA =
	"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";
// A GitHub comment holds 65536 characters.
const REPORT_LIMIT = 60000;
const DIFF_LINES_PER_PAGE = 40;
const CONTEXT = 80;

// Every install here runs with --ignore-scripts, and vetting a fresh release is the point
// of fetching it, so a min-release-age cooldown in the user's npm config is lifted.
const NPM_FLAGS = ["--min-release-age=0"];

const [oldVersion, newVersion, workdir = `/var/tmp/defuddle-check-${oldVersion}-${newVersion}`] =
	process.argv.slice(2);
if (!oldVersion || !newVersion) {
	console.error("Usage: node scripts/defuddle-bump-check.mjs <old-version> <new-version> [workdir]");
	process.exit(2);
}

rmSync(workdir, { recursive: true, force: true });
mkdirSync(join(workdir, "ab"), { recursive: true });

const checks = [];
const pass = (name, detail = "") => checks.push({ name, status: "pass", detail });
const fail = (name, detail = "") => checks.push({ name, status: "fail", detail });
const warn = (name, detail = "") => checks.push({ name, status: "warn", detail });
const check = (name, ok, detail) => (ok ? pass : fail)(name, detail);
const MARK = { pass: "✅", fail: "❌", warn: "⚠️" };

const meta = JSON.parse(npm(["view", `defuddle@${newVersion}`, "--json"]));
const published = await unpackTarball(meta);
const tree = installServiceTree();
const commit = await checkProvenance(meta);
if (commit) checkRebuild(commit, published);
checkAudit(tree);
const pages = await abCorpus();

const report = renderReport(pages);
writeFileSync(join(workdir, "report.md"), report);
console.log(join(workdir, "report.md"));
process.exit(checks.some((c) => c.status === "fail") ? 1 : 0);

async function unpackTarball(meta) {
	const lock = JSON.parse(readFileSync(join(SERVICE, "package-lock.json"), "utf8")).packages[
		"node_modules/defuddle"
	];
	check(
		`The lockfile pins the registry's ${newVersion} tarball`,
		lock.version === newVersion && lock.integrity === meta.dist.integrity,
		`lockfile: ${lock.version}, \`${lock.integrity.slice(0, 20)}…\``,
	);

	const tarball = Buffer.from(await (await fetch(meta.dist.tarball)).arrayBuffer());
	const integrity = `sha512-${createHash("sha512").update(tarball).digest("base64")}`;
	check("The downloaded tarball has that integrity", integrity === meta.dist.integrity);

	const dir = join(workdir, "published");
	mkdirSync(dir);
	writeFileSync(join(workdir, "defuddle.tgz"), tarball);
	run("tar", ["-xzf", join(workdir, "defuddle.tgz"), "-C", dir]);
	const scripts = JSON.parse(readFileSync(join(dir, "package/package.json"), "utf8")).scripts ?? {};
	const hooks = ["preinstall", "install", "postinstall"].filter((hook) => scripts[hook]);
	check("It declares no install scripts", hooks.length === 0, hooks.join(", "));
	return join(dir, "package");
}

function installServiceTree() {
	const dir = join(workdir, "service");
	mkdirSync(dir);
	for (const file of ["package.json", "package-lock.json"]) cpSync(join(SERVICE, file), join(dir, file));
	npm(["ci", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"], { cwd: dir });
	const signatures = attempt("npm", ["audit", "signatures", ...NPM_FLAGS], { cwd: dir });
	check(
		"Registry signatures and provenance attestations verify across the service's tree (`npm audit signatures`)",
		signatures.ok,
		tail(signatures.stdout + signatures.stderr),
	);
	return dir;
}

/** The commit the provenance says the release was built from, or null when it doesn't hold up. */
async function checkProvenance(meta) {
	const name = `Its provenance says ${UPSTREAM}'s ${RELEASE_WORKFLOW} built it from tag ${newVersion}`;
	if (!meta.dist.attestations) {
		fail(name, "the registry has no attestation for this version");
		return null;
	}
	const { attestations } = await (await fetch(meta.dist.attestations.url)).json();
	const provenance = attestations.find((a) => a.predicateType === "https://slsa.dev/provenance/v1");
	const statement = JSON.parse(Buffer.from(provenance.bundle.dsseEnvelope.payload, "base64").toString());
	const { workflow } = statement.predicate.buildDefinition.externalParameters;
	const commit = statement.predicate.buildDefinition.resolvedDependencies[0].digest.gitCommit;
	const sha512 = Buffer.from(meta.dist.integrity.replace(/^sha512-/, ""), "base64").toString("hex");
	const ok =
		workflow.repository === `https://github.com/${UPSTREAM}` &&
		workflow.path === RELEASE_WORKFLOW &&
		workflow.ref === `refs/tags/${newVersion}` &&
		statement.subject[0].digest.sha512 === sha512;
	check(name, ok, `${workflow.repository} ${workflow.ref} @ ${commit.slice(0, 7)}`);
	return ok ? commit : null;
}

function checkRebuild(commit, published) {
	const name = `Its dist/ rebuilds byte for byte from ${commit.slice(0, 7)}`;
	const source = join(workdir, "source");
	try {
		run("git", ["clone", "--quiet", "--filter=blob:none", `https://github.com/${UPSTREAM}.git`, source]);
		run("git", ["-C", source, "checkout", "--quiet", commit]);
		npm(["ci", "--ignore-scripts", "--no-audit", "--no-fund"], { cwd: source });
		npm(["run", "build"], { cwd: source });
	} catch (error) {
		fail(name, `the build failed: ${tail(error.stderr ?? error.message)}`);
		return;
	}
	const built = hashTree(join(source, "dist"));
	const shipped = hashTree(join(published, "dist"));
	const differing = [...new Set([...built.keys(), ...shipped.keys()])].filter(
		(file) => built.get(file) !== shipped.get(file),
	);
	check(
		name,
		differing.length === 0,
		differing.length
			? `differs: ${differing.slice(0, 8).join(", ")}${differing.length > 8 ? ", …" : ""}`
			: `${shipped.size} files, Node ${process.versions.node}`,
	);
}

/** A warning rather than a failure: the advisories belong to the whole tree, which the bump may not have touched. */
function checkAudit(tree) {
	const { vulnerabilities } = JSON.parse(
		attempt("npm", ["audit", "--omit=dev", "--json", ...NPM_FLAGS], { cwd: tree }).stdout,
	);
	const found = Object.values(vulnerabilities).map((v) => `${v.name} (${v.severity})`);
	(found.length ? warn : pass)("`npm audit` finds no advisories in the service's production tree", found.join(", "));
}

async function abCorpus() {
	const extractors = {};
	for (const version of [oldVersion, newVersion]) {
		const dir = join(workdir, "ab", `defuddle-${version}`);
		mkdirSync(dir);
		writeFileSync(join(dir, "package.json"), "{}");
		npm(["install", "--ignore-scripts", "--no-audit", "--no-fund", `defuddle@${version}`], { cwd: dir });
		extractors[version] = (await import(pathToFileURL(join(dir, "node_modules/defuddle/dist/node.js")))).Defuddle;
	}

	const pages = [];
	for (const [name, url] of corpusEntries()) {
		const page = { name, url };
		pages.push(page);
		try {
			const response = await fetch(url, {
				headers: { "user-agent": BROWSER_UA },
				signal: AbortSignal.timeout(30_000),
			});
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			page.html = await response.text();
		} catch (error) {
			page.fetchError = error.message;
			continue;
		}
		writeFileSync(join(workdir, "ab", `${name}.html`), page.html);
		for (const [side, version] of [["old", oldVersion], ["new", newVersion]]) {
			try {
				page[side] = await extractors[version](page.html, url, { markdown: true });
				writeFileSync(join(workdir, "ab", `${name}.${version}.md`), page[side].content);
			} catch (error) {
				page[`${side}Error`] = error.message;
			}
		}
		if (page.old && page.new && page.old.content !== page.new.content) {
			page.diff = wordDiff(join(workdir, "ab", `${name}.${oldVersion}.md`), join(workdir, "ab", `${name}.${newVersion}.md`));
			writeFileSync(join(workdir, "ab", `${name}.diff`), page.diff.lines.join("\n"));
		}
	}

	const extracted = pages.filter((p) => p.html);
	const broken = extracted.filter(
		(p) =>
			p.newError ||
			typeof p.new.content !== "string" ||
			typeof p.new.title !== "string" ||
			typeof p.new.wordCount !== "number",
	);
	check(
		"`Defuddle(html, url, { markdown: true })` from `defuddle/node` still returns content, title and wordCount",
		extracted.length > 0 && broken.length === 0,
		extracted.length ? broken.map((p) => `${p.name}: ${p.newError ?? "missing fields"}`).join("; ") : "no page could be fetched",
	);
	return pages;
}

function corpusEntries() {
	return readFileSync(CORPUS, "utf8")
		.split("\n")
		.map((line) => line.trim())
		.filter((line) => line && !line.startsWith("#"))
		.map((line) => line.split(/\s+/));
}

/** The changed lines in git's word-diff notation, long lines cut down to the changes and their context. */
function wordDiff(a, b) {
	const { stdout } = attempt("git", ["diff", "--no-index", "--no-color", "--word-diff=plain", "--unified=0", a, b]);
	const body = stdout.slice(stdout.indexOf("\n@@") + 1);
	const hunks = body.split(/^@@.*@@\n?/m).slice(1);
	return { hunks: hunks.length, lines: hunks.flatMap((hunk, i) => [...(i ? [""] : []), ...hunk.trimEnd().split("\n").map(clip)]) };
}

function clip(line) {
	if (line.length <= 2 * CONTEXT + 200) return line;
	const windows = [];
	for (const match of line.matchAll(/\[-.*?-\]|\{\+.*?\+\}/g)) {
		const start = Math.max(0, match.index - CONTEXT);
		const end = Math.min(line.length, match.index + Math.min(match[0].length, 400) + CONTEXT);
		const last = windows.at(-1);
		if (last && start <= last[1]) last[1] = Math.max(last[1], end);
		else windows.push([start, end]);
	}
	return windows
		.map(([start, end]) => `${start > 0 ? "…" : ""}${line.slice(start, end)}${end < line.length ? "…" : ""}`)
		.join(" ");
}

function renderReport(pages) {
	const fetched = pages.filter((p) => p.html);
	const identical = fetched.filter((p) => p.old && p.new && !p.diff);
	const unfetched = pages.length - fetched.length;
	const head = [
		`## defuddle ${oldVersion} → ${newVersion}`,
		"",
		`[Upstream changes](https://github.com/${UPSTREAM}/compare/${oldVersion}...${newVersion}) · ` +
			`[release notes](https://github.com/${UPSTREAM}/releases/tag/${newVersion})`,
		"",
		"### Checks",
		"",
		"| | Check | Detail |",
		"|---|---|---|",
		...checks.map((c) => `| ${MARK[c.status]} | ${c.name} | ${cell(c.detail)} |`),
		"",
		"### Extraction A/B",
		"",
		`Both versions read the same HTML through \`defuddle/node\`, the call yapit's static path makes. ` +
			`${identical.length} of ${fetched.length} pages come out byte-identical` +
			(unfetched ? `; ${unfetched} could not be fetched.` : "."),
		"",
		"| Page | Result | Words |",
		"|---|---|---|",
		...pages.map((p) => `| [${p.name}](${p.url}) | ${cell(outcome(p))} | ${p.old && p.new ? `${p.old.wordCount} → ${p.new.wordCount}` : ""} |`),
		"",
	].join("\n");

	let body = "";
	const changed = pages.filter((p) => p.diff);
	for (const [i, page] of changed.entries()) {
		const shown = page.diff.lines.slice(0, DIFF_LINES_PER_PAGE);
		const more = page.diff.lines.length - shown.length;
		const text = shown.join("\n") + (more > 0 ? `\n… ${more} more lines` : "");
		const details = [
			`<details><summary>${page.name}: ${changes(page)}</summary>`,
			"",
			fence(text),
			"",
			"</details>",
			"",
		].join("\n");
		if (head.length + body.length + details.length > REPORT_LIMIT) {
			body += `The diffs of ${changed.slice(i).map((p) => p.name).join(", ")} don't fit here; the run's artifact has every diff.\n`;
			break;
		}
		body += details;
	}
	return head + "\n" + body;
}

function outcome(page) {
	if (page.fetchError) return `not fetched: ${page.fetchError}`;
	if (page.oldError || page.newError)
		return [page.oldError && `${oldVersion} threw: ${page.oldError}`, page.newError && `${newVersion} threw: ${page.newError}`]
			.filter(Boolean)
			.join("; ");
	return page.diff ? changes(page) : "identical";
}

function changes(page) {
	return `${page.diff.hunks} ${page.diff.hunks === 1 ? "change" : "changes"}`;
}

function fence(text) {
	const longest = Math.max(2, ...[...text.matchAll(/`+/g)].map((m) => m[0].length));
	const ticks = "`".repeat(longest + 1);
	return `${ticks}text\n${text}\n${ticks}`;
}

function cell(text) {
	return String(text ?? "").replaceAll("|", "\\|").replaceAll("\n", " ");
}

function hashTree(root) {
	const hashes = new Map();
	for (const entry of readdirSync(root, { recursive: true, withFileTypes: true })) {
		if (!entry.isFile()) continue;
		const path = join(entry.parentPath, entry.name);
		hashes.set(relative(root, path), createHash("sha256").update(readFileSync(path)).digest("hex"));
	}
	return hashes;
}

function run(cmd, args, options = {}) {
	return execFileSync(cmd, args, { encoding: "utf8", maxBuffer: 1 << 28, stdio: ["ignore", "pipe", "pipe"], ...options });
}

function npm(args, options) {
	return run("npm", [...args, ...NPM_FLAGS], options);
}

function attempt(cmd, args, options) {
	try {
		return { ok: true, stdout: run(cmd, args, options), stderr: "" };
	} catch (error) {
		return { ok: false, stdout: error.stdout ?? "", stderr: error.stderr ?? error.message };
	}
}

function tail(text, lines = 3) {
	return text.trim().split("\n").slice(-lines).join(" ");
}
