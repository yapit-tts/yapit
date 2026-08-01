"""Voice preview sentences, per language.

The same five phrases in every language a Kokoro voice speaks (sentence two is the
language's canonical pangram where one exists). Keyed by the primary subtag of
Voice.lang ("pt-br" -> "pt"); English serves voices with unknown or absent lang.
"""

PREVIEW_SENTENCES: dict[str, list[str]] = {
    "en": [
        "Hello, this is a sample of my voice.",
        "The quick brown fox jumps over the lazy dog.",
        "I can read documents, articles, and research papers.",
        "Sometimes I wonder what it would be like to have a body.",
        "Breaking news: scientists discover that coffee is, in fact, essential.",
    ],
    "es": [
        "Hola, esta es una muestra de mi voz.",
        "El veloz murciélago hindú comía feliz cardillo y kiwi.",
        "Puedo leer documentos, artículos y trabajos de investigación.",
        "A veces me pregunto cómo sería tener un cuerpo.",
        "Última hora: científicos descubren que el café es, de hecho, imprescindible.",
    ],
    "fr": [
        "Bonjour, voici un échantillon de ma voix.",
        "Portez ce vieux whisky au juge blond qui fume.",
        "Je peux lire des documents, des articles et des publications scientifiques.",
        "Parfois, je me demande ce que ça ferait d'avoir un corps.",
        "Flash info : des scientifiques découvrent que le café est, en fait, indispensable.",
    ],
    "hi": [
        "नमस्ते, यह मेरी आवाज़ का एक नमूना है।",
        "तेज़ भूरी लोमड़ी आलसी कुत्ते के ऊपर से कूद जाती है।",
        "मैं दस्तावेज़, लेख और शोध पत्र पढ़ने में सक्षम हूँ।",
        "मुझे कभी-कभी आश्चर्य होता है कि शरीर होना कैसा लगता होगा।",
        "ताज़ा ख़बर: वैज्ञानिकों ने पाया कि कॉफ़ी वास्तव में अनिवार्य है।",
    ],
    "it": [
        "Ciao, questo è un esempio della mia voce.",
        "Ma la volpe col suo balzo ha raggiunto il quieto Fido.",
        "Posso leggere documenti, articoli e pubblicazioni scientifiche.",
        "A volte mi chiedo come sarebbe avere un corpo.",
        "Ultime notizie: gli scienziati scoprono che il caffè è, in effetti, essenziale.",
    ],
    "pt": [
        "Olá, esta é uma amostra da minha voz.",
        "Um pequeno jabuti xereta viu dez cegonhas felizes.",
        "Posso ler documentos, artigos e trabalhos de pesquisa.",
        "Às vezes me pergunto como seria ter um corpo.",
        "Notícia de última hora: cientistas descobrem que o café é, de fato, essencial.",
    ],
    "ja": [
        "こんにちは、これは私の声のサンプルです。",
        "素早い茶色の狐がのんびりした犬を飛び越えます。",
        "文書や記事、研究論文を読み上げることができます。",
        "時々、体があったらどんな感じだろうと考えます。",
        "速報：科学者たちは、コーヒーがやはり不可欠であることを発見しました。",
    ],
    "zh": [
        "你好，这是我的声音示例。",
        "敏捷的棕色狐狸跳过了懒惰的狗。",
        "我可以朗读文档、文章和研究论文。",
        "有时我会想，拥有身体会是什么感觉。",
        "突发新闻：科学家发现咖啡确实必不可少。",
    ],
}

N_PREVIEW_SENTENCES = len(PREVIEW_SENTENCES["en"])
assert all(len(sentences) == N_PREVIEW_SENTENCES for sentences in PREVIEW_SENTENCES.values())


def preview_sentences(lang: str | None) -> list[str]:
    """Sentences in the voice's language; English for absent/unknown langs."""
    if lang is None:
        return PREVIEW_SENTENCES["en"]
    return PREVIEW_SENTENCES.get(lang.split("-")[0], PREVIEW_SENTENCES["en"])
