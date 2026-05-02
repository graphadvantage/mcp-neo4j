import base64
import json
import logging
import os
import zlib

import nltk
from neo4j import Driver
from unstructured_client import UnstructuredClient
from unstructured_client.models import operations, shared

logging.disable(logging.CRITICAL)

CHUNK_QUERY = """
WITH apoc.convert.fromJsonList($json) AS maps
UNWIND maps AS map
WITH apoc.map.clean(map,[],["  ",""]) AS m
MERGE (d:Document {name: m.metadata.filename})
WITH m, d
CALL(m, d) {
  CREATE (n:Chunk {id: m.element_id})
  SET
    n.type = "NarrativeText",
    n.text = m.text,
    n.filename = m.metadata.filename,
    n.filetype = m.metadata.filetype,
    n.languages = m.metadata.languages,
    n.page_number = m.metadata.page_number,
    n.tokens = m.tokens
  CREATE (n)-[:PART_OF_DOCUMENT]->(d)
  RETURN n
}
WITH m, d, n
CALL(m, d, n) {
  WITH m, d, n
  WHERE m.metadata.type IN ['Image', 'Table']
  CREATE (i:$(m.metadata.type) {id: m.element_id})
  SET i.type = m.metadata.type,
      i.figure_caption = m.metadata.figure_caption,
      i.text = m.metadata.text,
      i.filename = m.metadata.filename,
      i.filetype = m.metadata.filetype,
      i.languages = m.metadata.languages,
      i.page_number = m.metadata.page_number,
      i.image_base64 = m.metadata.image_base64,
      i.image_mime_type = m.metadata.image_mime_type,
      i.text_as_html = m.metadata.text_as_html
  MERGE (n)-[:RELATED_CONTENT]->(i)
  MERGE (i)-[:PART_OF_DOCUMENT]->(d)
}
WITH DISTINCT d, n
WITH d, COLLECT(n) AS nodes
CALL apoc.nodes.link(nodes, "NEXT_CHUNK")
"""

# Guard against document already being partially ingested
SKIP_CHECK_QUERY = """
MATCH (d:Document {name: $filename})
RETURN count(d) > 0 AS exists
"""


def _extract_orig_elements(encoded: str) -> list:
    decoded = base64.b64decode(encoded)
    decompressed = zlib.decompress(decoded)
    return json.loads(decompressed.decode("utf-8"))


def _enrich_element(element: dict) -> dict:
    if element.get("text"):
        try:
            element["tokens"] = len(nltk.word_tokenize(element["text"]))
        except Exception:
            element["tokens"] = 0

    metadata = element.get("metadata", {})
    if metadata.get("orig_elements"):
        try:
            orig = _extract_orig_elements(metadata["orig_elements"])
            for obj in orig:
                if obj.get("type") == "FigureCaption" and obj.get("text", "").lower().startswith("figure"):
                    metadata["figure_caption"] = obj["text"]
                if obj.get("type") == "Image":
                    metadata.update({
                        "element_id": obj["element_id"],
                        "type": obj["type"],
                        "image_base64": obj["metadata"]["image_base64"],
                        "image_mime_type": obj["metadata"]["image_mime_type"],
                        "text": obj["text"],
                    })
                if obj.get("type") == "Table":
                    metadata.update({
                        "element_id": obj["element_id"],
                        "type": obj["type"],
                        "text_as_html": obj["metadata"]["text_as_html"],
                        "image_base64": obj["metadata"]["image_base64"],
                        "image_mime_type": obj["metadata"]["image_mime_type"],
                        "text": obj["text"],
                    })
        except Exception:
            pass
        metadata.pop("orig_elements", None)

    return element


def parse_directory(
    driver: Driver,
    docs_path: str,
    unstructured_api_key: str,
    max_characters: int = 1500,
    skip_existing: bool = True,
) -> None:
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)

    client = UnstructuredClient(
        api_key_auth=unstructured_api_key,
        server_url="https://api.unstructuredapp.io",
    )

    files = [
        f for f in os.listdir(docs_path)
        if not f.startswith(".") and os.path.isfile(os.path.join(docs_path, f))
    ]

    if not files:
        print("No files found in directory.")
        return

    print(f"Found {len(files)} file(s) to process.")

    for filename in files:
        filepath = os.path.join(docs_path, filename)

        if skip_existing:
            with driver.session() as session:
                result = session.run(SKIP_CHECK_QUERY, filename=filename)
                if result.single()["exists"]:
                    print(f"  Skipping (already ingested): {filename}")
                    continue

        print(f"  Parsing: {filename}")
        try:
            _parse_file(client, driver, filepath, filename, max_characters)
        except Exception as e:
            print(f"  ERROR processing {filename}: {e}")


def _parse_file(
    client: UnstructuredClient,
    driver: Driver,
    filepath: str,
    filename: str,
    max_characters: int,
) -> None:
    with open(filepath, "rb") as f:
        content = f.read()

    request = operations.PartitionRequest(
        partition_parameters=shared.PartitionParameters(
            files=shared.Files(content=content, file_name=filename),
            strategy="hi_res",
            hi_res_model_name="yolox",
            element_exclude=["Header", "Footer", "ListItem", "Formula", "UncategorizedText"],
            extract_image_block_types=["Image", "Table"],
            chunking_strategy="by_title",
            max_characters=max_characters,
            split_pdf_page=True,
            split_pdf_allow_failed=True,
            split_pdf_concurrency_level=15,
        )
    )

    response = client.general.partition(request=request)
    elements = [_enrich_element(e) for e in response.elements]

    json_data = json.dumps(elements, indent=2)

    with driver.session() as session:
        summary = session.execute_write(
            lambda tx, q, j: tx.run(q, {"json": j}).consume(),
            CHUNK_QUERY,
            json_data,
        )
        nodes = summary.counters.nodes_created
        rels = summary.counters.relationships_created
        print(f"  Done: {filename} — {nodes} nodes, {rels} relationships")
