"""Shared test helpers for markdown parser/transformer tests."""

from yapit.gateway.markdown.models import InlineContent, ListContent


def ast_contains(nodes: list[InlineContent], node_type: str) -> bool:
    """Check if AST contains a node of the given type (recursive)."""
    for node in nodes:
        if node.type == node_type:
            return True
        if hasattr(node, "content") and isinstance(node.content, list):
            if ast_contains(node.content, node_type):
                return True
        if isinstance(node, ListContent):
            for item in node.items:
                if ast_contains(item, node_type):
                    return True
    return False


def ast_text(nodes: list[InlineContent]) -> str:
    """Extract display text content from AST (recursive).

    Excludes SpeakContent (TTS-only) — this mirrors what the frontend renders.
    Joins with spaces — use for content-presence checks, not exact matching.
    """
    parts: list[str] = []
    for node in nodes:
        if node.type in ("text", "code_span", "math_inline"):
            parts.append(node.content)
        elif node.type == "inline_image":
            parts.append(node.alt)
        elif node.type == "footnote_ref":
            parts.append(f"[^{node.label}]")
        elif hasattr(node, "content") and isinstance(node.content, list):
            parts.append(ast_text(node.content))
        elif isinstance(node, ListContent):
            parts.extend(ast_text(item) for item in node.items)
    return " ".join(p for p in parts if p)
