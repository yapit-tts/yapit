"""Markdown parsing using markdown-it-py.

Configures markdown-it with the plugins we need:
- CommonMark base
- GFM tables and strikethrough
- Dollar math ($inline$ and $$display$$)
"""

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from mdit_py_plugins.dollarmath import dollarmath_plugin


def create_parser() -> MarkdownIt:
    """Create configured markdown-it parser."""
    md = MarkdownIt("commonmark")
    md.enable("table")
    md.enable("strikethrough")
    dollarmath_plugin(md)
    return md


# Singleton parser instance
_parser: MarkdownIt | None = None


def get_parser() -> MarkdownIt:
    """Get or create the singleton parser instance."""
    global _parser
    if _parser is None:
        _parser = create_parser()
    return _parser


def parse_markdown(text: str) -> SyntaxTreeNode:
    """Parse markdown text into AST.

    Args:
        text: Markdown text to parse

    Returns:
        Root SyntaxTreeNode of the AST
    """
    parser = get_parser()
    tokens = parser.parse(text)
    return SyntaxTreeNode(tokens)
