"""
RAG (Retrieval-Augmented Generation) for URDF generation.

Indexes a database of valid URDF snippets and retrieves the most relevant
ones based on the user's natural language prompt. Retrieved snippets are
injected into the LLM context to improve generation accuracy.

Uses simple TF-IDF cosine similarity (no external vector DB needed).
"""

import logging
import math
import re
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

SNIPPETS_DIR = Path(__file__).parent.parent / "data" / "urdf_snippets"


# ---------------------------------------------------------------------------
# Snippet data model
# ---------------------------------------------------------------------------

class URDFSnippet:
    """A URDF snippet with metadata extracted from XML comments."""

    def __init__(self, path: Path):
        self.path = path
        self.content = path.read_text()
        self.name = path.stem
        self.description = ""
        self.tags: list[str] = []
        self._parse_metadata()

    def _parse_metadata(self):
        """Extract SNIPPET description and TAGS from XML comments."""
        desc_match = re.search(r"<!--\s*SNIPPET:\s*(.+?)-->", self.content)
        if desc_match:
            self.description = desc_match.group(1).strip()

        tags_match = re.search(r"<!--\s*TAGS:\s*(.+?)-->", self.content)
        if tags_match:
            self.tags = [t.strip().lower() for t in tags_match.group(1).split(",")]

    @property
    def searchable_text(self) -> str:
        """Combined text for TF-IDF indexing."""
        return f"{self.description} {' '.join(self.tags)} {self.name}"


# ---------------------------------------------------------------------------
# TF-IDF engine (lightweight, no external deps)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric."""
    return re.findall(r'[a-z0-9]+', text.lower())


def _term_frequency(tokens: list[str]) -> dict[str, float]:
    """Compute normalized term frequency."""
    counts = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: count / total for term, count in counts.items()}


def _idf(documents: list[list[str]]) -> dict[str, float]:
    """Compute inverse document frequency."""
    num_docs = len(documents)
    df = Counter()
    for doc_tokens in documents:
        unique_terms = set(doc_tokens)
        for term in unique_terms:
            df[term] += 1

    idf_scores = {}
    for term, count in df.items():
        idf_scores[term] = math.log((num_docs + 1) / (count + 1)) + 1
    return idf_scores


def _tfidf_vector(tokens: list[str], idf_scores: dict[str, float]) -> dict[str, float]:
    """Compute TF-IDF vector for a document."""
    tf = _term_frequency(tokens)
    return {term: tf_val * idf_scores.get(term, 1.0) for term, tf_val in tf.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors."""
    common_terms = set(vec_a.keys()) & set(vec_b.keys())
    if not common_terms:
        return 0.0

    dot = sum(vec_a[t] * vec_b[t] for t in common_terms)
    mag_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# RAG Index
# ---------------------------------------------------------------------------

class RAGIndex:
    """
    In-memory TF-IDF index over URDF snippets.
    Loads all .urdf files from the snippets directory and indexes them.
    """

    def __init__(self, snippets_dir: Path | None = None):
        self.snippets_dir = snippets_dir or SNIPPETS_DIR
        self.snippets: list[URDFSnippet] = []
        self._doc_tokens: list[list[str]] = []
        self._idf: dict[str, float] = {}
        self._doc_vectors: list[dict[str, float]] = []
        self._loaded = False

    def load(self):
        """Load and index all URDF snippets."""
        if not self.snippets_dir.exists():
            logger.warning("Snippets directory not found: %s", self.snippets_dir)
            self._loaded = True
            return

        urdf_files = sorted(self.snippets_dir.glob("*.urdf"))
        logger.info("RAG: Loading %d URDF snippets from %s", len(urdf_files), self.snippets_dir)

        self.snippets = [URDFSnippet(f) for f in urdf_files]
        self._doc_tokens = [_tokenize(s.searchable_text) for s in self.snippets]
        self._idf = _idf(self._doc_tokens)
        self._doc_vectors = [_tfidf_vector(tokens, self._idf) for tokens in self._doc_tokens]
        self._loaded = True

        logger.info("RAG: Indexed %d snippets with %d unique terms",
                     len(self.snippets), len(self._idf))

    def retrieve(self, query: str, top_k: int = 3) -> list[tuple[URDFSnippet, float]]:
        """
        Retrieve the top-k most relevant URDF snippets for a query.

        Returns list of (snippet, similarity_score) tuples, sorted by relevance.
        """
        if not self._loaded:
            self.load()

        if not self.snippets:
            return []

        query_tokens = _tokenize(query)
        query_vec = _tfidf_vector(query_tokens, self._idf)

        scored = []
        for i, doc_vec in enumerate(self._doc_vectors):
            sim = _cosine_similarity(query_vec, doc_vec)
            scored.append((self.snippets[i], sim))

        # Sort by similarity descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Filter out zero-similarity results
        results = [(s, score) for s, score in scored[:top_k] if score > 0.0]

        logger.info("RAG: Retrieved %d snippets for query '%s' (top score: %.3f)",
                     len(results), query[:50],
                     results[0][1] if results else 0.0)
        return results

    def build_context(self, query: str, top_k: int = 2) -> str:
        """
        Build a context string from retrieved snippets for injection into LLM prompt.

        Returns a formatted string with relevant URDF examples.
        """
        results = self.retrieve(query, top_k=top_k)

        if not results:
            return ""

        context_parts = ["Here are reference URDF examples for similar robots:\n"]

        for snippet, score in results:
            context_parts.append(f"--- Example: {snippet.description} (relevance: {score:.2f}) ---")
            # Include a trimmed version (first ~2000 chars) to avoid token bloat
            trimmed = snippet.content[:2000]
            if len(snippet.content) > 2000:
                trimmed += "\n<!-- ... truncated ... -->"
            context_parts.append(trimmed)
            context_parts.append("")

        context_parts.append(
            "Use these examples as reference for correct URDF syntax, "
            "joint structure, and physical properties. "
            "Adapt them to match the user's specific request.\n"
        )

        return "\n".join(context_parts)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_rag_index: RAGIndex | None = None


def get_rag_index() -> RAGIndex:
    """Get or create the singleton RAG index."""
    global _rag_index
    if _rag_index is None:
        _rag_index = RAGIndex()
        _rag_index.load()
    return _rag_index


def retrieve_snippets(query: str, top_k: int = 3) -> list[tuple[URDFSnippet, float]]:
    """Convenience function: retrieve relevant snippets for a query."""
    return get_rag_index().retrieve(query, top_k=top_k)


def build_rag_context(query: str, top_k: int = 2) -> str:
    """Convenience function: build RAG context string for a query."""
    return get_rag_index().build_context(query, top_k=top_k)
