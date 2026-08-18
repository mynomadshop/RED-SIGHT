"""
RedSight - High-Performance Local AI Intelligence Platform
Sparse Retrieval Engine

BM25-based lexical search that complements dense vector retrieval.
No heavy dependencies — pure Python implementation.

Implements:
- Inverted index with term frequencies and document frequencies
- BM25 scoring with Okapi formulation
- Field weighting (title, heading, content)
- Query tokenization with stop-word removal
- Fast candidate generation for reranking
"""

from __future__ import annotations

import math
import re
import string
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ─── Stop Words ────────────────────────────────────────────────────────

DEFAULT_STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "i", "me", "my", "we", "our", "you",
    "your", "he", "him", "his", "she", "her", "they", "them", "their",
    "what", "which", "who", "whom", "where", "when", "how", "why",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "just", "about", "above", "after", "again", "all", "also", "am",
    "any", "as", "because", "before", "between", "both", "each", "few",
    "more", "most", "other", "over", "own", "same", "some", "such",
    "only", "into", "through", "during", "out", "up", "down", "off",
    "once", "here", "there", "further", "while", "s", "t", "ll", "ve",
    "re", "d", "m", "don", "didn", "doesn", "won", "couldn", "wouldn",
    "shouldn", "isn", "aren", "wasn", "weren", "hasn", "haven",
}


def tokenize(text: str, stop_words: Optional[Set[str]] = None) -> List[str]:
    """
    Tokenize text into BM25-compatible tokens.

    - Lowercase
    - Remove punctuation
    - Remove short tokens (< 2 chars)
    - Remove stop words
    """
    if stop_words is None:
        stop_words = DEFAULT_STOP_WORDS

    # Lowercase and extract tokens (alphanumeric sequences of 2+ chars)
    text = text.lower()
    tokens = re.findall(r"[a-z][a-z0-9]{1,}", text)

    # Filter stop words and short tokens
    tokens = [t for t in tokens if t not in stop_words and len(t) >= 2]

    return tokens


class BM25Index:
    """
    BM25 sparse retrieval index.

    Lightweight pure-Python implementation of the BM25 scoring algorithm
    (Okapi Best Matching 25). Builds an inverted index from document content
    and scores queries by relevance.

    Parameters:
        k1: Term frequency saturation parameter (default: 1.5)
        b: Length normalization parameter (default: 0.75)
        epsilon: Smoothing factor for IDF (default: 0.25)
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        epsilon: float = 0.25,
        stop_words: Optional[Set[str]] = None,
    ):
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.stop_words = stop_words or DEFAULT_STOP_WORDS

        # Inverted index: term -> {doc_id -> tf}
        self._inverted_index: Dict[str, Dict[str, int]] = defaultdict(dict)

        # Document lengths
        self._doc_lengths: Dict[str, int] = {}

        # Document content for retrieval
        self._documents: Dict[str, Dict[str, Any]] = {}

        # Total number of documents
        self._num_docs = 0

        # Average document length
        self._avg_doc_length = 0.0

        # Total number of tokens across all documents
        self._total_tokens = 0

    def add_document(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a document to the index."""
        # Tokenize
        tokens = tokenize(content, self.stop_words)
        token_count = len(tokens)

        # Update document lengths
        self._doc_lengths[doc_id] = token_count
        self._total_tokens += token_count

        # Update inverted index
        term_freqs: Dict[str, int] = defaultdict(int)
        for token in tokens:
            term_freqs[token] += 1

        for term, tf in term_freqs.items():
            self._inverted_index[term][doc_id] = tf

        # Store document
        self._documents[doc_id] = {
            "content": content,
            "metadata": metadata or {},
        }

        self._num_docs += 1

        # Recalculate average document length
        self._avg_doc_length = (
            self._total_tokens / self._num_docs if self._num_docs > 0 else 0
        )

    def remove_document(self, doc_id: str) -> None:
        """Remove a document from the index."""
        if doc_id not in self._documents:
            return

        doc_length = self._doc_lengths.get(doc_id, 0)
        self._total_tokens -= doc_length
        self._num_docs -= 1

        # Remove from inverted index
        for term, doc_dict in self._inverted_index.items():
            doc_dict.pop(doc_id, None)

        # Remove document
        del self._documents[doc_id]
        del self._doc_lengths[doc_id]

        # Recalculate average
        self._avg_doc_length = (
            self._total_tokens / self._num_docs if self._num_docs > 0 else 0
        )

    def _idf(self, term: str, doc_freq: int) -> float:
        """
        Compute Inverse Document Frequency with smoothing.

        IDF = log((N - df + 0.5) / (df + 0.5) + 1)
        """
        numerator = self._num_docs - doc_freq + 0.5
        denominator = doc_freq + 0.5
        return math.log(numerator / denominator + 1) + self.epsilon

    def _score_term(
        self, term: str, doc_id: str, tf: int
    ) -> float:
        """
        Compute BM25 score for a single term in a document.

        BM25 = IDF * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / avgdl)))
        """
        idf = self._idf(term, len(self._inverted_index[term]))
        doc_length = self._doc_lengths.get(doc_id, 0)
        avg_length = self._avg_doc_length if self._avg_doc_length > 0 else 1.0

        numerator = tf * (self.k1 + 1)
        denominator = tf + self.k1 * (1 - self.b + self.b * (doc_length / avg_length))

        return idf * (numerator / denominator) if denominator > 0 else 0

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search the index using BM25 scoring.

        Returns list of {doc_id, score, content, metadata} sorted by score.
        """
        query_tokens = tokenize(query, self.stop_words)

        if not query_tokens:
            return []

        # Accumulate scores per document
        scores: Dict[str, float] = defaultdict(float)

        for token in query_tokens:
            if token not in self._inverted_index:
                continue

            for doc_id, tf in self._inverted_index[token].items():
                # Apply filters if specified
                if filters and not self._matches_filter(doc_id, filters):
                    continue

                scores[doc_id] += self._score_term(token, doc_id, tf)

        # Sort by score descending
        results = []
        for doc_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            if len(results) >= top_k:
                break

            doc = self._documents.get(doc_id, {})
            results.append({
                "doc_id": doc_id,
                "score": round(score, 6),
                "content": doc.get("content", ""),
                "metadata": doc.get("metadata", {}),
            })

        return results

    def _matches_filter(self, doc_id: str, filters: Dict[str, Any]) -> bool:
        """Check if a document matches the given filters."""
        doc = self._documents.get(doc_id, {})
        meta = doc.get("metadata", {})

        for key, value in filters.items():
            if isinstance(value, dict):
                if "match" in value:
                    if meta.get(key) != value["match"]["value"]:
                        return False
                elif "values" in value:
                    if meta.get(key) not in value["values"]:
                        return False
            else:
                if meta.get(key) != value:
                    return False

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        total_terms = sum(len(d) for d in self._inverted_index.values())
        return {
            "num_documents": self._num_docs,
            "num_terms": len(self._inverted_index),
            "total_entries": total_terms,
            "avg_doc_length": round(self._avg_doc_length, 1),
            "avg_doc_length_tokens": round(self._total_tokens / max(1, self._num_docs), 1),
        }

    def rebuild(self) -> None:
        """Rebuild the index (recalculate averages)."""
        self._total_tokens = sum(self._doc_lengths.values())
        self._num_docs = len(self._documents)
        self._avg_doc_length = (
            self._total_tokens / self._num_docs if self._num_docs > 0 else 0
        )


class BM25FieldIndex(BM25Index):
    """
    BM25 index with field weighting.

    Supports separate indexing for title, heading, and content fields.
    Heading matches are weighted 2x, title 3x.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Separate inverted indices per field
        self._field_indices: Dict[str, BM25Index] = {}

    def add_document(
        self,
        doc_id: str,
        content: str,
        title: str = "",
        heading: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a document with separate fields."""
        # Index each field separately
        self._documents[doc_id] = {
            "content": content,
            "title": title,
            "heading": heading,
            "metadata": metadata or {},
        }

        # Content field (base weight)
        content_tokens = tokenize(content, self.stop_words)
        self._doc_lengths[doc_id] = len(content_tokens)
        self._total_tokens += len(content_tokens)

        term_freqs = defaultdict(int)
        for token in content_tokens:
            term_freqs[token] += 1

        for term, tf in term_freqs.items():
            self._inverted_index[term][doc_id] = tf

        # Heading field (2x weight)
        if heading:
            heading_tokens = tokenize(heading, self.stop_words)
            for token in heading_tokens:
                if token not in self._inverted_index:
                    self._inverted_index[token] = {}
                self._inverted_index[token][doc_id] = (
                    self._inverted_index[token].get(doc_id, 0) + 2
                )

        # Title field (3x weight)
        if title:
            title_tokens = tokenize(title, self.stop_words)
            for token in title_tokens:
                if token not in self._inverted_index:
                    self._inverted_index[token] = {}
                self._inverted_index[token][doc_id] = (
                    self._inverted_index[token].get(doc_id, 0) + 3
                )

        self._num_docs += 1
        self._avg_doc_length = (
            self._total_tokens / self._num_docs if self._num_docs > 0 else 0
        )

    def _score_term(self, term: str, doc_id: str, tf: int) -> float:
        """Override to apply field weight boost."""
        base_score = super()._score_term(term, doc_id, tf)

        # Check if term appears in heading or title (field boost)
        doc = self._documents.get(doc_id, {})
        heading = doc.get("heading", "")
        title = doc.get("title", "")

        if term in tokenize(heading, self.stop_words):
            base_score *= 1.5  # Heading boost
        if term in tokenize(title, self.stop_words):
            base_score *= 1.3  # Title boost

        return base_score
