from . import server
import asyncio
import argparse
import logging

from .utils import process_config

logger = logging.getLogger("mcp_neo4j_unstructured")
logger.setLevel(logging.INFO)


def main():
    """Entry point for the mcp-neo4j-unstructured server."""
    parser = argparse.ArgumentParser(description="Neo4j Unstructured RAG MCP Server")
    parser.add_argument("--db-url", default=None, help="Neo4j connection URL")
    parser.add_argument("--username", default=None, help="Neo4j username")
    parser.add_argument("--password", default=None, help="Neo4j password")
    parser.add_argument("--database", default=None, help="Neo4j database name")
    parser.add_argument("--openai-api-key", default=None, help="OpenAI API key for embeddings")
    parser.add_argument("--vector-index", default=None, help="Neo4j vector index name")
    parser.add_argument("--fulltext-index", default=None, help="Neo4j fulltext index name")
    parser.add_argument("--namespace", default=None, help="Tool namespace prefix")
    parser.add_argument("--transport", default=None, help="Transport type: stdio, sse, http")
    parser.add_argument("--server-host", default=None, help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--server-port", type=int, default=None, help="HTTP port (default: 8000)")
    parser.add_argument("--server-path", default=None, help="HTTP path (default: /mcp/)")
    parser.add_argument("--allow-origins", default=None, help="Comma-separated CORS origins")
    parser.add_argument("--allowed-hosts", default=None, help="Comma-separated allowed hosts")
    parser.add_argument("--read-only", action="store_true", default=False, help="Disable write Cypher tool")
    parser.add_argument("--read-timeout", type=int, default=None, help="Cypher read timeout in seconds (default: 30)")
    parser.add_argument("--schema-sample-size", type=int, default=None, help="APOC schema sample size (default: 1000)")
    parser.add_argument("--context-limit", type=int, default=None, help="LIMIT for hybrid retrieval expansion query (default: 100)")

    args = parser.parse_args()
    config = process_config(args)
    asyncio.run(server.main(**config))


__all__ = ["main", "server"]
