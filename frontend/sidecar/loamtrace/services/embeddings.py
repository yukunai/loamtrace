from __future__ import annotations

import hashlib
import json
import math
import re

DIMENSIONS = 64

TOKEN_ALIASES = {
    "arr": ("annual", "recurring", "revenue", "subscription"),
    "cashflow": ("cash", "flow"),
    "capex": ("capital", "expenditure", "spending"),
    "churn": ("retention", "attrition"),
    "ebitda": ("earnings", "profit", "profitability"),
    "gmv": ("gross", "merchandise", "value"),
    "margin": ("profit", "profitability"),
    "mrr": ("monthly", "recurring", "revenue", "subscription"),
    "profit": ("margin", "profitability", "earnings"),
    "profitability": ("profit", "margin", "earnings"),
    "retention": ("churn", "renewal"),
    "revenue": ("sales", "income"),
    "sales": ("revenue", "income"),
    "subscription": ("recurring", "revenue", "arr", "mrr"),
}


def embed_text(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for token in text_tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
        index = int.from_bytes(digest[:2], "big") % DIMENSIONS
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 6) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def dumps_embedding(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def loads_embedding(value: str) -> list[float]:
    return [float(item) for item in json.loads(value)]


def text_tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[\w.%$-]+", text, flags=re.UNICODE)]
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(TOKEN_ALIASES.get(token, ()))
    return expanded
