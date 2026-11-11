import json
from loamtrace.services.chunker import chunk_words

def test_chunk_words():
    document_id = "doc123"
    page_number = 1
    words = [
        {"id": f"w{i}", "text": "word", "bbox_json": '{"page": 1, "x0": 0, "y0": 0, "x1": 0.1, "y1": 0.1}'}
        for i in range(10)
    ]
    # Small target_words to trigger chunking
    chunks = chunk_words(document_id, page_number, words, target_words=5)
    
    # words are not sentence boundaries, so it should chunk after target_words?
    # Wait, the logic is: if reached_target and sentence_boundary
    # So if no sentence boundary, it will only chunk at the end of the list.
    assert len(chunks) == 1
    assert chunks[0]["document_id"] == document_id
    assert chunks[0]["token_count"] == 10

def test_chunk_words_with_boundaries():
    document_id = "doc123"
    page_number = 1
    words = [
        {"id": "w1", "text": "Hello.", "bbox_json": '{"page": 1, "x0": 0, "y0": 0, "x1": 0.1, "y1": 0.1}'},
        {"id": "w2", "text": "World.", "bbox_json": '{"page": 1, "x0": 0, "y0": 0, "x1": 0.1, "y1": 0.1}'},
    ]
    chunks = chunk_words(document_id, page_number, words, target_words=1)
    assert len(chunks) == 2
    assert chunks[0]["text"] == "Hello."
    assert chunks[1]["text"] == "World."
