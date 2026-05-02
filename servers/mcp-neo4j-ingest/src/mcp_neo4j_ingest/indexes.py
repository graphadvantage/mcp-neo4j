from neo4j import Driver
from neo4j_graphrag.indexes import create_vector_index, create_fulltext_index


def create_indexes(driver: Driver, vector_index: str, fulltext_index: str) -> None:
    print(f"Creating vector index '{vector_index}' on Chunk.embedding...")
    create_vector_index(
        driver,
        vector_index,
        label="Chunk",
        embedding_property="embedding",
        dimensions=1536,
        similarity_fn="cosine",
        fail_if_exists=False,
    )

    print(f"Creating fulltext index '{fulltext_index}' on Entity.text/variants...")
    create_fulltext_index(
        driver,
        fulltext_index,
        label="Entity",
        node_properties=["text", "variants"],
        fail_if_exists=False,
    )

    print("Indexes ready.")
