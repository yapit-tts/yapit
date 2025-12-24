"""Test corpus for TTS speed benchmarking.

Contains varied text samples to measure chars-per-second across different
content types, lengths, and edge cases.
"""

# Normal prose - various lengths
PROSE_SHORT = [
    "Hello, this is a quick test.",
    "The weather today is quite pleasant.",
    "She opened the door and stepped outside.",
]

PROSE_MEDIUM = [
    """The ancient library stood at the edge of the forest, its stone walls
covered in ivy that had been growing for centuries. Inside, countless
books lined the shelves, their leather bindings cracked with age.""",
    """Machine learning models have revolutionized the way we approach
complex problems in data analysis. Neural networks, in particular,
have shown remarkable success in pattern recognition tasks.""",
    """The chef carefully prepared each ingredient, slicing the vegetables
into thin strips and measuring the spices with precision. Cooking,
she believed, was as much about patience as it was about skill.""",
]

PROSE_LONG = [
    """In the early morning hours, before the sun had risen above the
eastern mountains, the village began to stir. Farmers emerged from
their cottages, their breath visible in the cold air, ready to tend
to their fields. The roosters crowed their daily announcements, and
the smell of fresh bread wafted from the bakery on the corner.
Children rubbed sleep from their eyes as their mothers called them
to breakfast. It was a scene that had repeated itself for generations,
a rhythm of life that seemed impervious to the changes happening in
the wider world. Yet change was coming, carried on the winds from
the distant cities, bringing with it both promise and uncertainty.""",
]

# Technical content
TECHNICAL = [
    "The API endpoint accepts GET, POST, and DELETE requests via HTTPS on port 443.",
    "Configure the DNS settings: A record pointing to 192.168.1.100, TTL 3600 seconds.",
    "The SHA-256 hash of the file is 3a7bd3e2c8d9f5b6a1e4c7d8f9a2b3c4d5e6f7a8b9c0.",
    "Run npm install --save-dev webpack@5.88.0 typescript@5.2.2 eslint@8.50.0.",
    "Memory usage peaked at 2.4GB with CPU utilization at 87% across 8 cores.",
]

# Numbers and quantities
NUMBERS = [
    "The total comes to one thousand two hundred and thirty-four dollars.",
    "1234 5678 9012 3456",  # Credit card style
    "Call us at 1-800-555-0199 or +1 (555) 123-4567.",
    "The coordinates are 40.7128 degrees north, 74.0060 degrees west.",
    "Version 2.0.1-beta.3 was released on 2024-03-15 at 14:30:00 UTC.",
    "Pi equals approximately 3.14159265358979323846264338327950288.",
    "The population grew from 1,234,567 to 2,345,678 between 2010 and 2020.",
]

# Abbreviations and acronyms
ABBREVIATIONS = [
    "The CEO of NASA met with representatives from the FBI, CIA, and NSA.",
    "Dr. Smith, Ph.D., presented at the IEEE conference on AI and ML.",
    "The USA, UK, EU, and ASEAN nations signed the MOU yesterday.",
    "FYI: The ETA for the VIP is ASAP, per the COO's memo re: Q4 KPIs.",
    "Prof. J.R.R. Tolkien Jr. wrote about Capt. Ahab vs. Dr. Frankenstein.",
]

# Dialogue and quotations
DIALOGUE = [
    '"Hello," she said. "How are you today?"',
    "'I don't think that's a good idea,' he muttered under his breath.",
    """She asked, "Have you seen the latest report?"
He replied, "No, what does it say?"
"It's not good news," she sighed.""",
    '"Stop!" he shouted. "Don\'t move!" The room fell silent.',
]

# Punctuation-heavy
PUNCTUATION = [
    "Wait... what? No! That can't be right -- or can it?!",
    "Items needed: eggs (12), milk (2L), bread (1 loaf); optional: butter, cheese.",
    "The result was: (a) incorrect, (b) misleading, and (c) potentially dangerous.",
    "He said—and I quote—'This is absolutely, positively, 100% certain.'",
    "Is this real? Really? REALLY?! I can't believe it... wow.",
]

# Lists and enumerations
LISTS = [
    "First, preheat the oven. Second, mix the ingredients. Third, bake for 30 minutes.",
    "The top five countries are: 1) China, 2) India, 3) USA, 4) Indonesia, 5) Pakistan.",
    "Requirements: a) valid ID, b) proof of address, c) completed application form.",
]

# Unicode and accented characters
UNICODE = [
    "The café serves excellent crème brûlée and café au lait.",
    "Müller's naïve résumé impressed the Zürich-based company.",
    "The piñata contained señor García's jalapeño-flavored candy.",
    "Tokyo (東京), Beijing (北京), and Seoul (서울) are major Asian capitals.",
    "Mathematical symbols: α + β = γ, ∑ from i=1 to n, ∞ approaches.",
]

# Repetition and stuttering (tests model stability)
REPETITION = [
    "The the quick brown fox jumps over the the lazy dog dog dog.",
    "I I I think we should should should reconsider this this decision.",
    "No no no, that's not what I meant at all, at all.",
    "Buffalo buffalo Buffalo buffalo buffalo buffalo Buffalo buffalo.",
]

# Very short fragments
FRAGMENTS = [
    "Yes.",
    "No way!",
    "Hmm...",
    "Okay, fine.",
    "What?!",
    "I see.",
    "Go on.",
]

# Scientific and medical
SCIENTIFIC = [
    "The patient presented with acute myocardial infarction and was administered aspirin.",
    "Photosynthesis converts carbon dioxide and water into glucose and oxygen.",
    "The double helix structure of DNA was discovered by Watson and Crick in 1953.",
    "Quantum entanglement allows particles to be correlated regardless of distance.",
]

# Code-like text (not actual code, but mentioned in speech)
CODE_SPEECH = [
    "The function takes two parameters: x and y, and returns their sum.",
    "Set the variable to null, then check if undefined before proceeding.",
    "The class inherits from base controller and overrides the render method.",
    "Import the module, instantiate the class, then call the execute function.",
]

# Edge cases - garbled/random
GARBLED = [
    "asdfghjkl qwertyuiop zxcvbnm",
    "aaa bbb ccc ddd eee fff ggg hhh iii jjj kkk",
    "!@#$%^&*()_+-=[]{}|;':\",./<>?",
    "xXxXxXxXxXxXxXxXxXxX",
    "a1b2c3d4e5f6g7h8i9j0",
]

# Random hex/base64-like strings
RANDOM_STRINGS = [
    "7f3a9c2b8d4e1f6a0b5c9d8e7f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0",
    "SGVsbG8gV29ybGQhIFRoaXMgaXMgYmFzZTY0IGVuY29kZWQgdGV4dC4=",
    "0x7f3a9c2b 0x8d4e1f6a 0x0b5c9d8e 0x7f2a3b4c",
]

# Numbers with various spacing/formatting
NUMBERS_FORMATTED = [
    "1 2 3 4 5 6 7 8 9 0",
    "1  2  3  4  5  6  7  8  9  0",
    "1   2   3   4   5   6   7   8   9   0",
    "123 456 789 012 345 678 901 234 567 890",
    "1-2-3-4-5-6-7-8-9-0",
    "1.2.3.4.5.6.7.8.9.0",
    "1,2,3,4,5,6,7,8,9,0",
]

# Mixed language (might confuse models)
MIXED_LANGUAGE = [
    "She said bonjour and he replied with konnichiwa.",
    "The restaurant serves both pizza and sushi, truly fusion cuisine.",
    "Auf wiedersehen, my friend, until we meet again, sayonara.",
]

# Empty-ish content
WHITESPACE_HEAVY = [
    "   Lots   of   spaces   between   words   here   ",
    "New\nlines\neverywhere\nin\nthis\ntext",
    "Tabs\there\tand\tthere\tand\teverywhere",
]

# Extreme punctuation
EXTREME_PUNCTUATION = [
    "......",
    "!!!!!!",
    "??????",
    ".,.,.,.,.,.,",
    "-----------",
    "***********",
]


def get_all_samples() -> list[tuple[str, str, str]]:
    """Return all samples as (category, id, text) tuples."""
    samples = []

    categories = [
        ("prose_short", PROSE_SHORT),
        ("prose_medium", PROSE_MEDIUM),
        ("prose_long", PROSE_LONG),
        ("technical", TECHNICAL),
        ("numbers", NUMBERS),
        ("abbreviations", ABBREVIATIONS),
        ("dialogue", DIALOGUE),
        ("punctuation", PUNCTUATION),
        ("lists", LISTS),
        ("unicode", UNICODE),
        ("repetition", REPETITION),
        ("fragments", FRAGMENTS),
        ("scientific", SCIENTIFIC),
        ("code_speech", CODE_SPEECH),
        ("garbled", GARBLED),
        ("random_strings", RANDOM_STRINGS),
        ("numbers_formatted", NUMBERS_FORMATTED),
        ("mixed_language", MIXED_LANGUAGE),
        ("whitespace_heavy", WHITESPACE_HEAVY),
        ("extreme_punctuation", EXTREME_PUNCTUATION),
    ]

    for category_name, texts in categories:
        for i, text in enumerate(texts):
            samples.append((category_name, f"{category_name}_{i}", text))

    return samples


def get_mega_document() -> str:
    """Return a single large document containing all test cases as sections.
    Useful for batch processing benchmarks.
    """
    sections = []

    sections.append("# TTS Benchmark Document\n")
    sections.append("This document contains various text types for benchmarking TTS synthesis speed.\n\n")

    categories = [
        ("Normal Prose - Short", PROSE_SHORT),
        ("Normal Prose - Medium", PROSE_MEDIUM),
        ("Normal Prose - Long", PROSE_LONG),
        ("Technical Content", TECHNICAL),
        ("Numbers and Quantities", NUMBERS),
        ("Abbreviations and Acronyms", ABBREVIATIONS),
        ("Dialogue and Quotations", DIALOGUE),
        ("Punctuation Heavy", PUNCTUATION),
        ("Lists and Enumerations", LISTS),
        ("Unicode and Accented Characters", UNICODE),
        ("Repetition and Stuttering", REPETITION),
        ("Very Short Fragments", FRAGMENTS),
        ("Scientific and Medical", SCIENTIFIC),
        ("Code-like Speech", CODE_SPEECH),
        ("Garbled and Random", GARBLED),
        ("Random Hex/Base64 Strings", RANDOM_STRINGS),
        ("Numbers with Various Formatting", NUMBERS_FORMATTED),
        ("Mixed Language", MIXED_LANGUAGE),
        ("Whitespace Heavy", WHITESPACE_HEAVY),
        ("Extreme Punctuation", EXTREME_PUNCTUATION),
    ]

    for section_name, texts in categories:
        sections.append(f"## {section_name}\n\n")
        for text in texts:
            # Clean up newlines for display
            clean_text = text.replace("\n", " ").strip()
            sections.append(f"- {clean_text}\n\n")

    return "".join(sections)


if __name__ == "__main__":
    samples = get_all_samples()
    print(f"Total samples: {len(samples)}")
    print(f"Total characters: {sum(len(s[2]) for s in samples)}")
    print("\nCategories:")
    from collections import Counter

    cats = Counter(s[0] for s in samples)
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")
