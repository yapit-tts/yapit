"""Thin wrapper around markdown-it-py for parsing markdown to AST."""

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.dollarmath import dollarmath_plugin


def create_parser() -> MarkdownIt:
    """Create a configured markdown parser.

    Includes:
    - CommonMark base
    - GFM tables
    - Dollar math ($...$ and $$...$$)
    - Strikethrough (~~text~~)
    """
    md = MarkdownIt("commonmark")
    md.enable("table")
    md.enable("strikethrough")
    dollarmath_plugin(md)
    return md


def parse_markdown(text: str) -> SyntaxTreeNode:
    """Parse markdown text to AST.

    Returns a SyntaxTreeNode which provides hierarchical access to the parsed
    document structure with .children, .type, .content, etc.
    """
    md = create_parser()
    tokens = md.parse(text)
    return SyntaxTreeNode(tokens)


def render_html(text: str) -> str:
    """Render markdown to HTML.

    Used for generating the `html` field of prose blocks.
    """
    md = create_parser()
    return md.render(text)
