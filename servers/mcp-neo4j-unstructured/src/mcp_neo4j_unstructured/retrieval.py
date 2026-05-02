import re

import neo4j
from neo4j_graphrag.embeddings import OpenAIEmbeddings
from neo4j_graphrag.retrievers import HybridCypherRetriever
from neo4j_graphrag.types import RetrieverResultItem

def _build_retrieval_query(context_limit: int = 100) -> str:
    return f"""
WITH node, score
OPTIONAL MATCH (node)-[:NEXT_CHUNK]-(c)
OPTIONAL MATCH (node)<-[:HAS_ENTITY]-(e)
ORDER BY score DESC LIMIT {context_limit}
RETURN apoc.convert.toSet(
    COLLECT(elementId(node)) + COLLECT(elementId(e)) + COLLECT(elementId(c))
) AS listIds,
COLLECT(e.id) as contextNodes, node.text as nodeText, score
ORDER BY score DESC
"""


def sanitize_for_lucene(query: str) -> str:
    query = query.replace("\n", " ").replace("\r", " ")
    query = re.sub(r"([\+\-\!\(\)\{\}\[\]\^\"\~\*\?\:\\\/])", r"\\\1", query)
    query = re.sub(r"\b\w+:(?=\S)", "", query)
    return re.sub(r"\s+", " ", query).strip()


def _formatter(record: neo4j.Record) -> RetrieverResultItem:
    node_text = record.get("nodeText")
    score = record.get("score")
    list_ids = record.get("listIds")
    context_nodes = record.get("contextNodes")
    return RetrieverResultItem(
        content=f"{node_text}: score {score}, Related context: {context_nodes}",
        metadata={"listIds": list_ids, "nodeText": node_text},
    )


def create_retriever(
    driver: neo4j.Driver,
    openai_api_key: str,
    vector_index_name: str,
    fulltext_index_name: str,
    database: str = "neo4j",
    context_limit: int = 100,
) -> HybridCypherRetriever:
    embedder = OpenAIEmbeddings(model="text-embedding-ada-002", api_key=openai_api_key)
    return HybridCypherRetriever(
        driver,
        vector_index_name=vector_index_name,
        fulltext_index_name=fulltext_index_name,
        retrieval_query=_build_retrieval_query(context_limit),
        result_formatter=_formatter,
        embedder=embedder,
        neo4j_database=database,
    )
