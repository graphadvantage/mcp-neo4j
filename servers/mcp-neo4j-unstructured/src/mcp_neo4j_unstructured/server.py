import asyncio
import json
import logging
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Literal, Optional

import neo4j
from neo4j import AsyncGraphDatabase, GraphDatabase, Query, RoutingControl
from neo4j.exceptions import ClientError, Neo4jError
from pydantic import Field
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fastmcp.exceptions import ToolError
from fastmcp.server import FastMCP
from fastmcp.tools.tool import ToolResult
from mcp.types import ImageContent, TextContent, ToolAnnotations

from .html_graph import generate_interactive_graph_html, SUBGRAPH_QUERIES
from .retrieval import create_retriever, sanitize_for_lucene
from .utils import format_namespace, _value_sanitize

logger = logging.getLogger("mcp_neo4j_unstructured")


async def _is_write_query(query: str, driver, database: str) -> bool:
    _, summary, _ = await driver.execute_query("EXPLAIN " + query, database_=database)
    return "w" in (summary.query_type or "")


def create_mcp_server(
    retriever: neo4j.Driver,
    async_driver,
    neo4j_database: str,
    fulltext_index_name: str,
    namespace: str = "",
    read_only: bool = False,
    read_timeout: int = 30,
    schema_sample_size: int = 1000,
) -> FastMCP:
    ns = format_namespace(namespace)
    allow_writes = not read_only
    mcp: FastMCP = FastMCP("mcp-neo4j-unstructured", stateless_http=True)

    @mcp.tool(
        name=ns + "query_knowledge_graph",
        annotations=ToolAnnotations(
            title="Query Knowledge Graph",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def query_knowledge_graph(
        question: str = Field(
            ...,
            description="Natural language question to search the knowledge graph",
        ),
    ) -> ToolResult:
        """Retrieve relevant context from the knowledge graph using hybrid vector+fulltext search.

        Searches indexed document chunks using both vector similarity and fulltext matching.
        Returns retrieved text chunks and a flat list of node elementIds that were found.

        After calling this tool you can:
        - Call get_retrieval_subgraph(element_ids) to get nodes+edges for a Mermaid diagram
        - Call get_node_content(element_id) on any elementId to get full text, images, or tables
        - Call get_chunk_neighbors(element_id) to navigate adjacent document sections
        """
        logger.info(f"query_knowledge_graph: {question!r}")
        sanitized = sanitize_for_lucene(question)
        try:
            result = await asyncio.to_thread(
                retriever.search,
                query_text=sanitized,
                top_k=5,
            )
        except Exception as e:
            raise ToolError(f"Retrieval error: {e}")

        all_ids: list[str] = []
        chunks: list[dict] = []
        for item in result.items:
            meta = item.metadata or {}
            list_ids: list[str] = meta.get("listIds") or []
            for eid in list_ids:
                if eid not in all_ids:
                    all_ids.append(eid)
            if meta.get("nodeText"):
                chunks.append({"text": meta["nodeText"], "element_ids": list_ids})

        output = {
            "retrieved_chunks": chunks,
            "element_ids": all_ids,
            "hint": (
                "Call get_retrieval_subgraph(element_ids) for graph structure, "
                "get_node_content(element_id) to inspect images/tables/text."
            ),
        }
        return ToolResult(
            content=[TextContent(type="text", text=json.dumps(output))],
            structured_content=output,
        )

    @mcp.tool(
        name=ns + "get_retrieval_subgraph",
        annotations=ToolAnnotations(
            title="Get Retrieval Subgraph",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_retrieval_subgraph(
        element_ids: list[str] = Field(
            ...,
            description="List of node elementIds returned by query_knowledge_graph",
        ),
    ) -> ToolResult:
        """Get the graph structure for a set of nodes as nodes + edges.

        Returns each node with its labels and a display name (truncated text or entity id),
        plus all relationships between those nodes. Use this data to generate a Mermaid
        flowchart showing how retrieved chunks, documents, and entities are connected.

        Example Mermaid usage:
            graph LR
              id1["Chunk: reservoir pressure..."] --> id2["Document: Field Report 2023"]
              id1 --> id3["Entity: Fault Line Alpha"]
        """
        logger.info(f"get_retrieval_subgraph: {len(element_ids)} ids")
        try:
            async with async_driver.session() as session:
                result = await session.run(
                    """
                    MATCH (n) WHERE elementId(n) IN $ids
                    OPTIONAL MATCH (n)-[r]-(m) WHERE elementId(m) IN $ids
                    WITH
                        collect(DISTINCT {
                            id: elementId(n),
                            labels: labels(n),
                            short_name: left(coalesce(n.text, n.id, n.name, elementId(n)), 60)
                        }) AS nodes,
                        collect(DISTINCT CASE WHEN r IS NOT NULL THEN {
                            source: elementId(startNode(r)),
                            target: elementId(endNode(r)),
                            type: type(r)
                        } END) AS raw_edges
                    RETURN nodes, [e IN raw_edges WHERE e IS NOT NULL] AS edges
                    """,
                    ids=element_ids,
                )
                record = await result.single()
        except Neo4jError as e:
            raise ToolError(f"Neo4j error: {e}")

        if not record:
            return ToolResult(content=[TextContent(type="text", text="No nodes found")])

        data = {"nodes": record["nodes"], "edges": record["edges"]}
        return ToolResult(
            content=[TextContent(type="text", text=json.dumps(data))],
            structured_content=data,
        )

    @mcp.tool(
        name=ns + "get_node_content",
        annotations=ToolAnnotations(
            title="Get Node Content",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_node_content(
        element_id: str = Field(
            ..., description="Neo4j elementId of the node to fetch"
        ),
    ) -> ToolResult:
        """Fetch the full content of a graph node by its elementId.

        Node types and what they return:
        - Chunk / NarrativeText  → TextContent with the chunk text
        - Image                  → ImageContent (base64 PNG rendered inline by Claude Desktop)
        - Table                  → TextContent with HTML + ImageContent if image available
        - Document               → TextContent with document name and text
        - Entity (any other)     → TextContent with entity id, name, and properties

        Image and table nodes produce inline images that Claude can read and reason about,
        not just display — use this to extract data from diagrams, charts, and tables.
        """
        logger.info(f"get_node_content: {element_id}")
        try:
            async with async_driver.session() as session:
                result = await session.run(
                    "MATCH (n) WHERE elementId(n) = $id RETURN labels(n) AS labels, properties(n) AS props",
                    id=element_id,
                )
                record = await result.single()
        except Neo4jError as e:
            raise ToolError(f"Neo4j error: {e}")

        if not record:
            raise ToolError(f"Node not found: {element_id}")

        labels: list[str] = record["labels"]
        props: dict = record["props"]
        content: list = []

        if "Image" in labels:
            img_data = props.get("image") or props.get("image_base64")
            if img_data:
                content.append(
                    TextContent(
                        type="text",
                        text=f"[Image: {props.get('id', element_id)}]",
                    )
                )
                content.append(
                    ImageContent(type="image", data=img_data, mimeType="image/png")
                )
            else:
                content.append(
                    TextContent(type="text", text=f"Image node has no image data. Properties: {list(props.keys())}")
                )
        elif "Table" in labels:
            html = props.get("text_as_html") or props.get("text", "")
            if html:
                content.append(TextContent(type="text", text=f"[Table]\n{html}"))
            img_data = props.get("image") or props.get("image_base64")
            if img_data:
                content.append(
                    ImageContent(type="image", data=img_data, mimeType="image/png")
                )
        elif "Chunk" in labels or "NarrativeText" in labels:
            content.append(TextContent(type="text", text=props.get("text", "")))
        elif "Document" in labels:
            parts = []
            if props.get("name"):
                parts.append(f"Document: {props['name']}")
            if props.get("text"):
                parts.append(props["text"])
            content.append(TextContent(type="text", text="\n".join(parts)))
        else:
            # Entity or unknown
            parts = [f"Labels: {', '.join(labels)}"]
            for key in ("id", "name", "text", "description"):
                if props.get(key):
                    parts.append(f"{key}: {props[key]}")
            content.append(TextContent(type="text", text="\n".join(parts)))

        return ToolResult(
            content=content,
            structured_content={"labels": labels, "element_id": element_id},
        )

    @mcp.tool(
        name=ns + "get_chunk_neighbors",
        annotations=ToolAnnotations(
            title="Get Chunk Neighbors",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_chunk_neighbors(
        element_id: str = Field(
            ...,
            description="elementId of a Chunk node to navigate from",
        ),
    ) -> ToolResult:
        """Get the immediately adjacent chunks connected by NEXT_CHUNK relationships.

        Returns the previous and next chunks with text previews and their elementIds.
        Use to navigate surrounding document context when a retrieved chunk references
        something that needs more surrounding text.
        """
        logger.info(f"get_chunk_neighbors: {element_id}")
        try:
            async with async_driver.session() as session:
                result = await session.run(
                    """
                    MATCH (n) WHERE elementId(n) = $id
                    OPTIONAL MATCH (n)-[:NEXT_CHUNK]->(nxt)
                    OPTIONAL MATCH (prv)-[:NEXT_CHUNK]->(n)
                    RETURN
                        left(n.text, 200) AS current_preview,
                        elementId(nxt) AS next_id,
                        left(nxt.text, 200) AS next_preview,
                        elementId(prv) AS prev_id,
                        left(prv.text, 200) AS prev_preview
                    """,
                    id=element_id,
                )
                record = await result.single()
        except Neo4jError as e:
            raise ToolError(f"Neo4j error: {e}")

        if not record:
            raise ToolError(f"Node not found: {element_id}")

        data = {
            "current_preview": record["current_preview"],
            "prev": (
                {"element_id": record["prev_id"], "preview": record["prev_preview"]}
                if record["prev_id"]
                else None
            ),
            "next": (
                {"element_id": record["next_id"], "preview": record["next_preview"]}
                if record["next_id"]
                else None
            ),
        }
        return ToolResult(
            content=[TextContent(type="text", text=json.dumps(data))],
            structured_content=data,
        )

    @mcp.tool(
        name=ns + "search_entities",
        annotations=ToolAnnotations(
            title="Search Entities",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def search_entities(
        query: str = Field(
            ...,
            description="Search string to match against entity names and ids (case-insensitive substring)",
        ),
    ) -> ToolResult:
        """Search for entity nodes by name or id using case-insensitive substring matching.

        Returns matching entity nodes with their elementIds, labels, and names.
        Excludes Chunk and Document nodes — returns only entity-type nodes extracted
        from documents (e.g. Person, Organization, Location, etc.).
        Use get_node_content to fetch full details of any returned entity.
        """
        logger.info(f"search_entities: {query!r}")
        lower_query = query.lower()
        try:
            async with async_driver.session() as session:
                result = await session.run(
                    """
                    MATCH (n)
                    WHERE NOT 'Chunk' IN labels(n)
                      AND NOT 'Document' IN labels(n)
                      AND (
                        toLower(coalesce(n.id, '')) CONTAINS $q
                        OR toLower(coalesce(n.name, '')) CONTAINS $q
                        OR toLower(coalesce(n.text, '')) CONTAINS $q
                      )
                    RETURN elementId(n) AS id, labels(n) AS labels,
                           coalesce(n.id, n.name, '') AS name
                    LIMIT 10
                    """,
                    q=lower_query,
                )
                entities = []
                async for record in result:
                    entities.append(
                        {
                            "element_id": record["id"],
                            "labels": record["labels"],
                            "name": record["name"],
                        }
                    )
        except Neo4jError as e:
            raise ToolError(f"Neo4j error: {e}")

        return ToolResult(
            content=[TextContent(type="text", text=json.dumps({"entities": entities}))],
            structured_content={"entities": entities},
        )

    # ── Interactive graph visualization ────────────────────────────────────────

    @mcp.tool(
        name=ns + "open_interactive_subgraph",
        annotations=ToolAnnotations(
            title="Open Interactive Subgraph",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def open_interactive_subgraph(
        element_ids: list[str] = Field(
            ...,
            description="Node elementIds from query_knowledge_graph to visualize interactively",
        ),
    ) -> ToolResult:
        """Generate an interactive force-directed graph and open it in the browser.

        Follows the same traversal as the aura-chatbot modal:
        - Chunk → PART_OF_DOCUMENT → Document
        - Chunk ↔ NEXT_CHUNK ↔ Chunk
        - Chunk ↔ HAS_ENTITY ↔ Entity
        - Chunk → RELATED_CONTENT → Image/Table (filtered: aspect_ratio<10, bytes>9KB)

        Clicking any node opens a side panel showing:
        - Chunk: full narrative text
        - Image: inline rendered image + OCR text
        - Table: table image + HTML table
        - Document/Entity: name and properties

        Colors match the React modal: Chunk=blue, Document=green, Image=yellow,
        Table=coral, Entity=purple.
        """
        logger.info(f"open_interactive_subgraph: {len(element_ids)} ids")
        try:
            nodes_map: dict[str, dict] = {}
            edges: list[dict] = []

            async with async_driver.session() as session:
                result = await session.run(SUBGRAPH_QUERIES, ids=element_ids)
                async for record in result:
                    src_id = record["src_id"]
                    tgt_id = record["tgt_id"]
                    if src_id not in nodes_map:
                        nodes_map[src_id] = {
                            "id": src_id,
                            "labels": record["src_labels"],
                            "props": dict(record["src_props"]),
                        }
                    if tgt_id not in nodes_map:
                        nodes_map[tgt_id] = {
                            "id": tgt_id,
                            "labels": record["tgt_labels"],
                            "props": dict(record["tgt_props"]),
                        }
                    edges.append({
                        "source": src_id,
                        "target": tgt_id,
                        "type": record["rel_type"],
                    })
        except Neo4jError as e:
            raise ToolError(f"Neo4j error: {e}")

        nodes_data = list(nodes_map.values())
        html = generate_interactive_graph_html(nodes_data, edges)

        tmp_path = f"/tmp/neo4j_graph_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(html)

        subprocess.Popen(["open", tmp_path])

        return ToolResult(
            content=[TextContent(
                type="text",
                text=f"Interactive graph opened in browser ({len(nodes_data)} nodes, {len(edges)} edges).\nFile: {tmp_path}",
            )]
        )

    # ── Cypher tools (mirroring mcp-neo4j-cypher) ──────────────────────────────

    @mcp.tool(
        name=ns + "get_neo4j_schema",
        annotations=ToolAnnotations(
            title="Get Neo4j Schema",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def get_neo4j_schema(
        sample_size: int = Field(
            default=schema_sample_size,
            description="Sample size for schema inference. Lower is faster; -1 scans the full graph.",
        ),
    ) -> ToolResult:
        """Return node labels, property types, and relationships via APOC schema inspection."""
        effective = sample_size or schema_sample_size
        logger.info(f"get_neo4j_schema: sample_size={effective}")
        query = f"CALL apoc.meta.schema({{sample: {effective}}}) YIELD value RETURN value"

        def _clean(schema: dict) -> dict:
            out = {}
            for key, entry in schema.items():
                e: dict = {"type": entry["type"]}
                if "count" in entry:
                    e["count"] = entry["count"]
                if entry.get("labels"):
                    e["labels"] = entry["labels"]
                props = {
                    pn: {k: v for k, v in pi.items() if k in ("indexed", "type")}
                    for pn, pi in entry.get("properties", {}).items()
                    if any(k in pi for k in ("indexed", "type"))
                }
                if props:
                    e["properties"] = props
                rels = {}
                for rn, r in entry.get("relationships", {}).items():
                    cr = {k: v for k, v in r.items() if k in ("direction", "labels")}
                    rprops = {
                        rpn: {k: v for k, v in rpi.items() if k in ("indexed", "type")}
                        for rpn, rpi in r.get("properties", {}).items()
                        if any(k in rpi for k in ("indexed", "type"))
                    }
                    if rprops:
                        cr["properties"] = rprops
                    if cr:
                        rels[rn] = cr
                if rels:
                    e["relationships"] = rels
                out[key] = e
            return out

        try:
            results = await async_driver.execute_query(
                query,
                routing_control=RoutingControl.READ,
                database_=neo4j_database,
                result_transformer_=lambda r: r.data(),
            )
            schema_str = json.dumps(_clean(results[0].get("value")), default=str)
            return ToolResult(content=[TextContent(type="text", text=schema_str)])
        except ClientError as e:
            if "ProcedureNotFound" in str(e):
                raise ToolError("APOC plugin not found. Install APOC to use get_neo4j_schema.")
            raise ToolError(f"Neo4j Client Error: {e}")
        except Neo4jError as e:
            raise ToolError(f"Neo4j Error: {e}")
        except Exception as e:
            raise ToolError(f"Unexpected error: {e}")

    @mcp.tool(
        name=ns + "read_neo4j_cypher",
        annotations=ToolAnnotations(
            title="Read Neo4j Cypher",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def read_neo4j_cypher(
        query: str = Field(..., description="The read Cypher query to execute."),
        params: dict[str, Any] = Field(
            default_factory=dict, description="Optional query parameters."
        ),
    ) -> ToolResult:
        """Execute a read-only Cypher query. Raises if the query contains writes."""
        if await _is_write_query(query, async_driver, neo4j_database):
            raise ToolError("Only read queries are allowed. Use write_neo4j_cypher for writes.")
        try:
            results = await async_driver.execute_query(
                Query(query, timeout=float(read_timeout)),
                parameters_=params,
                routing_control=RoutingControl.READ,
                database_=neo4j_database,
                result_transformer_=lambda r: r.data(),
            )
            sanitized = [_value_sanitize(el) for el in results]
            return ToolResult(
                content=[TextContent(type="text", text=json.dumps(sanitized, default=str))]
            )
        except Neo4jError as e:
            raise ToolError(f"Neo4j Error: {e}\n{query}\n{params}")
        except Exception as e:
            raise ToolError(f"Error: {e}\n{query}\n{params}")

    @mcp.tool(
        name=ns + "write_neo4j_cypher",
        annotations=ToolAnnotations(
            title="Write Neo4j Cypher",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        enabled=allow_writes,
    )
    async def write_neo4j_cypher(
        query: str = Field(..., description="The write Cypher query to execute."),
        params: dict[str, Any] = Field(
            default_factory=dict, description="Optional query parameters."
        ),
    ) -> ToolResult:
        """Execute a write Cypher query (CREATE, MERGE, SET, DELETE). Disabled when read_only=True."""
        if not await _is_write_query(query, async_driver, neo4j_database):
            raise ToolError("Only write queries are allowed here. Use read_neo4j_cypher for reads.")
        try:
            _, summary, _ = await async_driver.execute_query(
                query,
                parameters_=params,
                routing_control=RoutingControl.WRITE,
                database_=neo4j_database,
            )
            return ToolResult(
                content=[TextContent(type="text", text=json.dumps(summary.counters.__dict__, default=str))]
            )
        except Neo4jError as e:
            raise ToolError(f"Neo4j Error: {e}\n{query}\n{params}")
        except Exception as e:
            raise ToolError(f"Error: {e}\n{query}\n{params}")

    return mcp


async def main(
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str,
    openai_api_key: str,
    vector_index_name: str,
    fulltext_index_name: str,
    transport: Literal["stdio", "sse", "http"] = "stdio",
    namespace: str = "",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp/",
    allow_origins: list[str] = [],
    allowed_hosts: list[str] = [],
    read_only: bool = False,
    read_timeout: int = 30,
    schema_sample_size: int = 1000,
    context_limit: int = 100,
) -> None:
    logger.info("Starting Neo4j Unstructured MCP Server")
    logger.info(f"Connecting to Neo4j: {neo4j_uri}")

    # Async driver for direct Cypher queries in tools
    async_driver = AsyncGraphDatabase.driver(
        neo4j_uri, auth=(neo4j_user, neo4j_password), database=neo4j_database
    )
    try:
        await async_driver.verify_connectivity()
        logger.info("Async Neo4j connection verified")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        exit(1)

    # Sync driver for HybridCypherRetriever (neo4j-graphrag uses sync driver)
    sync_driver = GraphDatabase.driver(
        neo4j_uri, auth=(neo4j_user, neo4j_password)
    )

    retriever = create_retriever(
        driver=sync_driver,
        openai_api_key=openai_api_key,
        vector_index_name=vector_index_name,
        fulltext_index_name=fulltext_index_name,
        database=neo4j_database,
        context_limit=context_limit,
    )
    logger.info(f"HybridCypherRetriever initialized (vector={vector_index_name}, fulltext={fulltext_index_name})")

    custom_middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        ),
        Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts),
    ]

    mcp = create_mcp_server(
        retriever, async_driver, neo4j_database, fulltext_index_name,
        namespace, read_only, read_timeout, schema_sample_size,
    )
    logger.info("MCP server created")

    logger.info(f"Starting with transport: {transport}")
    match transport:
        case "http":
            await mcp.run_http_async(host=host, port=port, path=path, middleware=custom_middleware)
        case "stdio":
            await mcp.run_stdio_async()
        case "sse":
            await mcp.run_http_async(host=host, port=port, path=path, middleware=custom_middleware, transport="sse")
        case _:
            raise ValueError(f"Unsupported transport: {transport}")
