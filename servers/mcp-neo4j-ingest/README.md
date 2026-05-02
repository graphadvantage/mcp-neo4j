# mcp-neo4j-ingest

CLI pipeline for ingesting unstructured documents (PDFs, etc.) into a Neo4j knowledge graph for use with `mcp-neo4j-unstructured`.

## Pipeline Steps

1. **indexes** — Create vector (`chunk_embedding`) and fulltext (`entity_text`) indexes (idempotent)
2. **parse** — Parse documents with unstructured.io, write Chunk/Image/Table nodes to Neo4j
3. **embed** — Generate OpenAI vector embeddings for all unembedded Chunks
4. **entities** — Extract domain entities from Chunks using GPT-4o, write Entity nodes
5. **images** — Compute width/height/aspect_ratio/bytes for Image and Table nodes

## Usage

```bash
# Set connection details via env or flags
export NEO4J_URI=bolt://localhost:7687
export NEO4J_PASSWORD=password
export OPENAI_API_KEY=sk-...
export UNSTRUCTURED_API_KEY=...

mcp-neo4j-ingest /path/to/documents \
  --domain "petroleum exploration, reservoir analysis, oil & gas production" \
  --entity-types "Formation,Wellbore,Fault,Measurement,Fluid"
```

## Options

| Flag | Env | Default | Description |
|------|-----|---------|-------------|
| `--neo4j-uri` | `NEO4J_URI` | — | Neo4j connection URI |
| `--neo4j-username` | `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `--neo4j-password` | `NEO4J_PASSWORD` | — | Neo4j password |
| `--neo4j-database` | `NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `--openai-api-key` | `OPENAI_API_KEY` | — | OpenAI API key |
| `--unstructured-api-key` | `UNSTRUCTURED_API_KEY` | — | Unstructured.io API key |
| `--domain` | — | `general technical` | Domain description for entity extraction prompt |
| `--entity-types` | — | — | Comma-separated entity types to focus on |
| `--model` | — | `gpt-4o` | OpenAI model for entity extraction |
| `--embedding-model` | — | `text-embedding-ada-002` | OpenAI embedding model |
| `--steps` | — | `all` | Steps to run: `indexes,parse,embed,entities,images` or `all` |
| `--max-characters` | — | `1500` | Max characters per chunk |
| `--max-chunks` | — | `10000` | Max chunks per entity extraction run |
| `--vector-index` | — | `chunk_embedding` | Vector index name |
| `--fulltext-index` | — | `entity_text` | Fulltext index name |

## Running Individual Steps

```bash
# Only re-run entity extraction (e.g. after tuning the domain prompt)
mcp-neo4j-ingest /path/to/docs --steps entities --domain "new domain"

# Only create indexes on a fresh database
mcp-neo4j-ingest /path/to/docs --steps indexes
```
