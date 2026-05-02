from neo4j import Driver
from openai import OpenAI

FETCH_CHUNKS_QUERY = """
MATCH (n:Chunk:ProcessMe)
WHERE NOT (n)-[:HAS_ENTITY]->() AND n.entities IS NULL
RETURN n.id AS id, replace(n.text, "\n", "") AS text
LIMIT $limit
"""

MARK_PROCESS_QUERY = """
MATCH (n:Chunk {type:"NarrativeText"})
WHERE NOT (n)-[:HAS_ENTITY]->() AND n.entities IS NULL
SET n:ProcessMe
"""

ENTITY_INSERT_QUERY = """
WITH $entities AS entities
MATCH (n:Chunk:ProcessMe {id: $id})
WITH n, entities
CALL apoc.do.when(
    entities[0] = "[]" OR entities[0] STARTS WITH "The text provided does not contain",
    "WITH n SET n.entities = 'failed' REMOVE n:ProcessMe RETURN 0 AS rels",
    "WITH n, apoc.convert.fromJsonList(entities[0]) AS names
     UNWIND names AS name
     MERGE (e:Entity {text: toLower(name)})
     ON CREATE SET e.variants = [name]
     ON MATCH SET e.variants = apoc.convert.toSet(e.variants + [name])
     MERGE (n)-[:HAS_ENTITY]->(e)
     WITH DISTINCT n, COUNT(e) AS rels
     REMOVE n:ProcessMe
     RETURN rels",
    {n: n, entities: entities}
) YIELD value
RETURN value
"""

FAIL_MARK_QUERY = """
MATCH (n:Chunk:ProcessMe {id: $id})
SET n.entities = "failed"
REMOVE n:ProcessMe
"""


def _build_prompt(text: str, domain: str, entity_types: list[str] | None) -> str:
    type_hint = ""
    if entity_types:
        type_hint = f"\n\nFocus specifically on these entity types: {', '.join(entity_types)}."

    return f"""Extract all the entities from the following text.

Identify only entities, abbreviations and technical terms commonly used in {domain}.

Return entities in this format: ["entity1", "entity2"]

Do not include any extra text or explanation.{type_hint}

Text: {text}"""


def _extract_entities(client: OpenAI, text: str, domain: str, entity_types: list[str] | None, model: str) -> list[str]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": f"You help extract entities from {domain}-related text."},
            {"role": "user", "content": _build_prompt(text, domain, entity_types)},
        ],
        max_tokens=500,
        temperature=0,
    )
    return [response.choices[0].message.content.strip()]


def extract_entities(
    driver: Driver,
    openai_api_key: str,
    domain: str,
    entity_types: list[str] | None = None,
    model: str = "gpt-4o",
    max_chunks: int = 10000,
) -> None:
    client = OpenAI(api_key=openai_api_key)

    # Mark unprocessed chunks
    with driver.session() as session:
        session.run(MARK_PROCESS_QUERY)

    with driver.session() as session:
        chunks = list(session.run(FETCH_CHUNKS_QUERY, limit=max_chunks))

    if not chunks:
        print("  No chunks to process for entity extraction.")
        return

    print(f"  Extracting entities from {len(chunks)} chunk(s)...")
    processed = 0

    with driver.session() as session:
        for chunk in chunks:
            chunk_id = chunk["id"]
            text = chunk["text"]

            try:
                entities = _extract_entities(client, text, domain, entity_types, model)
                result = session.run(ENTITY_INSERT_QUERY, id=chunk_id, entities=entities)
                for record in result:
                    rels = record["value"]["rels"]
                    processed += 1
                    print(f"\r  Processed {processed}/{len(chunks)} | Last: {rels} entities", end="", flush=True)
                result.consume()
            except Exception as e:
                print(f"\n  Failed chunk {chunk_id}: {e}")
                session.run(FAIL_MARK_QUERY, id=chunk_id)

    print(f"\n  Done. {processed} chunks processed.")
