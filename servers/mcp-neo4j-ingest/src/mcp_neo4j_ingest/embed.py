from neo4j import Driver
from neo4j_graphrag.embeddings import OpenAIEmbeddings

MAX_CHUNK_LENGTH = 12000

FETCH_QUERY = """
MATCH (n:Chunk)
WHERE n.text IS NOT NULL AND n.embedding IS NULL
RETURN n.id AS id, n.text AS text
"""

SET_EMBEDDING_QUERY = """
MATCH (n:Chunk {id: $id})
SET n.embedding = $embedding
"""


def embed_chunks(driver: Driver, openai_api_key: str, embedding_model: str = "text-embedding-ada-002") -> None:
    embedder = OpenAIEmbeddings(model=embedding_model, api_key=openai_api_key)

    with driver.session() as session:
        chunks = list(session.run(FETCH_QUERY))

    if not chunks:
        print("  No unembedded chunks found.")
        return

    print(f"  Embedding {len(chunks)} chunk(s)...")
    skipped = 0
    embedded = 0

    for i, record in enumerate(chunks):
        chunk_id = record["id"]
        text = record["text"]

        if len(text) > MAX_CHUNK_LENGTH:
            skipped += 1
            continue

        try:
            embedding = embedder.embed_query(text)
            with driver.session() as session:
                session.run(SET_EMBEDDING_QUERY, id=chunk_id, embedding=embedding)
            embedded += 1
            print(f"\r  Embedded {embedded}/{len(chunks)} chunks...", end="", flush=True)
        except Exception as e:
            print(f"\n  Failed to embed chunk {chunk_id}: {e}")

    print(f"\n  Done. {embedded} embedded, {skipped} skipped (too long).")
