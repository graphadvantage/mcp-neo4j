# mcp-neo4j-unstructured

A Model Context Protocol (MCP) server that gives Claude Desktop native access to a **Neo4j knowledge graph built from unstructured documents** — PDFs, technical reports, and other document types parsed into text, images, and tables with their structural relationships preserved.

Claude replaces the UI layer entirely. Rather than a separate LLM doing retrieval summarization, Claude receives raw chunks, inline images, and table HTML from the graph and synthesizes answers directly — with full access to the visual content extracted from source documents.

---

## Motivation

Technical documents contain information that resists keyword search: figures with annotated diagrams, tables of measurements, and narrative text that references both. Standard RAG pipelines return text chunks and lose the images and tables entirely.

This server builds on the [aura-chatbot](https://github.com/neo4j-labs/aura-chatbot) GraphRAG approach and ports it to Claude Desktop as an MCP server. The key differences from a typical RAG setup:

- **Images and tables are first-class nodes** in the graph, linked to the chunks that reference them
- **Hybrid retrieval** combines vector similarity on chunk embeddings with fulltext search on extracted entities, then graph-traverses to collect surrounding context
- **Claude reasons over retrieved images inline** — `get_node_content` returns base64 PNG via `ImageContent`, which Claude Desktop renders and reads without any additional tooling
- **Interactive force-directed graph** opens in the browser after every query, showing the chunk/document/entity/image subgraph with a clickable side panel matching the aura-chatbot modal
- **No LLM in the retrieval path** — all synthesis is done by Claude using raw evidence from the graph

---

## Graph Structure

The graph is built by the companion [`mcp-neo4j-ingest`](../mcp-neo4j-ingest) CLI pipeline.

| Node label | Key properties | Description |
|---|---|---|
| `Chunk` | `text`, `embedding`, `type`, `page_number` | Layout-aware text chunk from a document (`type="NarrativeText"`) |
| `Document` | `name` | Source document (one per file) |
| `Image` | `image_base64`, `image_mime_type`, `figure_caption`, `bytes`, `aspect_ratio` | Extracted figure or photo as base64 PNG |
| `Table` | `text_as_html`, `image_base64`, `bytes`, `aspect_ratio` | Extracted table as HTML and/or image |
| `Entity` | `text`, `variants` | Domain entity extracted from chunk text (formation, wellbore, fault, etc.) |

| Relationship | Meaning |
|---|---|
| `(Chunk)-[:NEXT_CHUNK]->(Chunk)` | Sequential document order |
| `(Chunk)-[:HAS_ENTITY]->(Entity)` | Entity extracted from chunk |
| `(Chunk)-[:RELATED_CONTENT]->(Image\|Table)` | Image or table associated with a chunk |
| `(Chunk)-[:PART_OF_DOCUMENT]->(Document)` | Chunk belongs to document |
| `(Image\|Table)-[:PART_OF_DOCUMENT]->(Document)` | Image or table belongs to document |

---

## Tools

| Tool | Description |
|---|---|
| `query_knowledge_graph` | Hybrid vector+fulltext retrieval. Returns text chunks and a flat `element_ids` list. Start here. |
| `open_interactive_subgraph` | Generates a force-directed vis.js graph and opens it in the browser. Call after every query. |
| `get_node_content` | Returns full content of any node: text for Chunks, inline `ImageContent` for Images, HTML+image for Tables. |
| `get_chunk_neighbors` | Navigate `NEXT_CHUNK` to read surrounding document context when a chunk seems truncated. |
| `search_entities` | Find entity nodes by name substring — useful for targeted lookups by formation, wellbore, fault name. |
| `get_neo4j_schema` | Inspect node labels, property types, and relationships via APOC. |
| `read_neo4j_cypher` | Execute a custom read-only Cypher query. |
| `write_neo4j_cypher` | Execute a write Cypher query (disabled when `NEO4J_READ_ONLY=true`). |

---

## Dependencies

**Runtime:**
- Python 3.10+
- [fastmcp](https://github.com/jlowin/fastmcp) ≥ 2.0, < 3
- [neo4j](https://pypi.org/project/neo4j/) ≥ 5.26 (provides both sync and async drivers)
- [neo4j-graphrag](https://pypi.org/project/neo4j-graphrag/) ≥ 1.0 (provides `HybridCypherRetriever` and `OpenAIEmbeddings`)
- [openai](https://pypi.org/project/openai/) ≥ 1.0 (for query embedding at retrieval time)
- [pydantic](https://pypi.org/project/pydantic/) ≥ 2.10

**Neo4j requirements:**
- Neo4j 5.x (AuraDB or self-hosted)
- [APOC plugin](https://neo4j.com/labs/apoc/) — required for `get_neo4j_schema` and the ingestion pipeline
- A vector index named `chunk_embedding` on `Chunk.embedding` (1536 dimensions, cosine)
- A fulltext index named `entity_text` on `Entity.text` and `Entity.variants`

---

## Installation

### As a global tool with uv (recommended for Claude Desktop)

```bash
cd servers/mcp-neo4j-unstructured
uv tool install .
```

This installs the `mcp-neo4j-unstructured` binary to `~/.local/bin/`. After code changes, reinstall with:

```bash
uv tool install . --reinstall
```

### From source (development)

```bash
cd servers/mcp-neo4j-unstructured
pip install -e .
```

---

## Configuration

All configuration is via environment variables (or CLI flags when running directly).

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | — | Neo4j password |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `OPENAI_API_KEY` | — | OpenAI API key (used to embed queries at retrieval time) |
| `VECTOR_INDEX_NAME` | `chunk_embedding` | Name of the vector index on `Chunk.embedding` |
| `FULLTEXT_INDEX_NAME` | `entity_text` | Name of the fulltext index on `Entity` |
| `NEO4J_CONTEXT_LIMIT` | `100` | Maximum nodes returned by the hybrid retriever |
| `NEO4J_READ_ONLY` | `false` | Set `true` to disable `write_neo4j_cypher` |
| `NEO4J_READ_TIMEOUT` | `30` | Query timeout in seconds |
| `NEO4J_SCHEMA_SAMPLE_SIZE` | `1000` | Sample size for APOC schema inference |

---

## Claude Desktop Setup

Add the server to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "neo4j-unstructured": {
      "command": "/Users/<you>/.local/bin/mcp-neo4j-unstructured",
      "args": [],
      "env": {
        "NEO4J_URI": "neo4j+s://<instance>.databases.neo4j.io",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "<password>",
        "NEO4J_DATABASE": "neo4j",
        "OPENAI_API_KEY": "<key>",
        "VECTOR_INDEX_NAME": "chunk_embedding",
        "FULLTEXT_INDEX_NAME": "entity_text",
        "NEO4J_CONTEXT_LIMIT": "100"
      }
    }
  }
}
```

Restart Claude Desktop after editing the config.

### System prompt

Copy [`claude-prompt.md`](./claude-prompt.md) into your Claude Desktop project as the system prompt. It instructs Claude to:
- Start every question with `query_knowledge_graph`
- Always call `open_interactive_subgraph` after retrieval
- Call `get_node_content` on every `Image` and `Table` node in the result set
- Render images inline in the response narrative rather than appending them at the end

---

## Usage

Once Claude Desktop is configured with the server and the system prompt, ask questions directly in natural language. Claude retrieves relevant graph context, opens an interactive browser visualization, and synthesizes an answer with inline images and tables.

**Example questions for a petroleum / oil & gas knowledge graph:**

```
What is the petrology of the Hugin Formation sandstones, including micrograph and porosity analyses?

Describe Fault 3514m and Fault 3619m from the EcoScope analyses of well 15-9-F14.

What is the dip vector interpretation from the EcoScope analyses of wellbore 15-9-F-14?

What are the interpretations from the StethoScope wellbore analyses?

What is the facies interpretation from the biostratigraphic analyses?

Are there any significant unconformities in the reservoir?

Describe the Theta West discovery and the size and recoverability of the reservoir.
```

### Interactive graph

After every `query_knowledge_graph` call, `open_interactive_subgraph` opens a self-contained HTML file in your browser. The force-directed graph shows all retrieved nodes connected by their relationships. Clicking any node opens a side panel:

- **Chunk** — full narrative text
- **Image** — rendered inline image + OCR text
- **Table** — rendered table image + HTML
- **Entity** — name and property list
- **Document** — document name

Node colours: Chunk (blue `#0A6190`) · Document (green `#BCF194`) · Image (yellow `#FFC300`) · Table (coral `#FF8E6A`) · Entity (purple `#B38EFF`)

---

## Building a Knowledge Graph

Use the companion [`mcp-neo4j-ingest`](../mcp-neo4j-ingest) CLI to parse documents and populate the graph:

```bash
pip install ../mcp-neo4j-ingest

mcp-neo4j-ingest /path/to/documents \
  --neo4j-uri neo4j+s://<instance>.databases.neo4j.io \
  --neo4j-password <password> \
  --openai-api-key <key> \
  --unstructured-api-key <key> \
  --domain "petroleum exploration, petroleum geology, reservoir analysis, and oil & gas production" \
  --entity-types "Formation,Wellbore,Fault,Measurement,Fluid"
```

The pipeline runs five idempotent steps: create indexes → parse with unstructured.io → embed chunks → extract entities → compute image dimensions. Individual steps can be re-run independently with `--steps entities` etc.

---

## Architecture Notes

- **Dual Neo4j drivers** — a sync driver (`GraphDatabase.driver`) is required by `HybridCypherRetriever` (neo4j-graphrag uses the sync API); an async driver (`AsyncGraphDatabase.driver`) handles all direct tool queries. The sync retriever runs in a thread pool via `asyncio.to_thread()` to avoid blocking the event loop.
- **Hybrid retrieval** — `HybridCypherRetriever` searches `Chunk.embedding` (cosine vector similarity) and the `Entity` fulltext index simultaneously, then expands via `NEXT_CHUNK` and `HAS_ENTITY` traversal up to `NEO4J_CONTEXT_LIMIT` nodes.
- **Interactive graph** — `open_interactive_subgraph` runs a UNION Cypher query matching the same traversal as the aura-chatbot React modal (`PART_OF_DOCUMENT`, `NEXT_CHUNK`, `HAS_ENTITY`, `RELATED_CONTENT` with `aspect_ratio < 10 AND bytes > 9216` filter). The resulting HTML uses vis.js 9.1.9 from CDN and is opened via `subprocess.Popen(["open", path])`.
