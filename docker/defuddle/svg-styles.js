/**
 * Runs in the page: writes each inline SVG's computed look into its style attributes.
 * Defuddle drops class attributes and never sees the stylesheet, so a chart styled by CSS
 * would otherwise come out in default black lines and fonts.
 * Animations are finished first, so the SVG is kept as it ends.
 */
export function inlineSvgStyles() {
	const INHERITED = [
		"color", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-dasharray",
		"stroke-dashoffset", "stroke-linecap", "stroke-linejoin", "stroke-opacity", "font-family",
		"font-size", "font-style", "font-weight", "text-anchor", "dominant-baseline", "visibility",
	];

	for (const animation of document.getAnimations()) {
		try {
			animation.finish();
		} catch {
			// An infinite animation has no end to finish at.
		}
	}

	for (const svg of document.querySelectorAll("svg")) {
		const elements = [svg, ...svg.querySelectorAll("*")];
		const declarations = elements.map((el) => {
			const own = getComputedStyle(el);
			const parent = el === svg ? null : getComputedStyle(el.parentElement);
			const decls = INHERITED.filter((p) => !parent || own.getPropertyValue(p) !== parent.getPropertyValue(p)).map(
				(p) => `${p}:${own.getPropertyValue(p)}`,
			);
			if (own.opacity !== "1") decls.push(`opacity:${own.opacity}`);
			return decls.join(";");
		});
		elements.forEach((el, i) => {
			if (i > 0 && declarations[i]) el.setAttribute("style", declarations[i]);
		});
		// The root's own look goes on a group around its content: defuddle reads a style's
		// "stroke-width:1px" on the root as a width and removes the SVG as an icon.
		const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
		group.setAttribute("style", declarations[0]);
		group.append(...svg.childNodes);
		svg.append(group);
	}
}

/**
 * Runs in the page: replaces each canvas with an image of what it shows, which defuddle keeps.
 * A page often draws a canvas only once it scrolls into view, so each is scrolled to first.
 * The image is painted over the page's background behind the canvas, since a canvas is
 * usually transparent and drawn in colours meant for that background.
 * Self-contained, as is inlineSvgStyles: page.evaluate sends the function's source alone.
 */
export async function snapshotCanvases() {
	const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));
	const backgroundBehind = (el) => {
		for (let node = el; node instanceof Element; node = node.parentElement) {
			const color = getComputedStyle(node).backgroundColor;
			if (color && color !== "transparent" && !/rgba\(.*,\s*0\)$/.test(color)) return color;
		}
		return "white";
	};
	for (const canvas of document.querySelectorAll("canvas")) {
		canvas.scrollIntoView({ block: "center" });
		await frame();
		await frame();
		if (canvas.width < 33 || canvas.height < 33) continue;

		const plate = document.createElement("canvas");
		plate.width = canvas.width;
		plate.height = canvas.height;
		const ctx = plate.getContext("2d");
		ctx.fillStyle = backgroundBehind(canvas);
		ctx.fillRect(0, 0, plate.width, plate.height);
		let src;
		try {
			ctx.drawImage(canvas, 0, 0);
			src = plate.toDataURL("image/png");
		} catch {
			continue; // A canvas that drew a cross-origin image refuses to be read.
		}
		const img = document.createElement("img");
		img.src = src;
		img.alt = canvas.getAttribute("aria-label") || "";
		img.width = canvas.clientWidth;
		img.height = canvas.clientHeight;
		canvas.replaceWith(img);
	}
	window.scrollTo(0, 0);
}
