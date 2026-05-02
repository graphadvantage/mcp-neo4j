import argparse
import os
import logging
from typing import Any, Union

logger = logging.getLogger("mcp_neo4j_unstructured")


def _value_sanitize(d: Any, list_limit: int = 128) -> Any:
    """Strip embedding-like oversized lists from query results before returning to Claude."""
    if isinstance(d, dict):
        new_dict = {}
        for key, value in d.items():
            if isinstance(value, dict):
                sanitized = _value_sanitize(value)
                if sanitized is not None:
                    new_dict[key] = sanitized
            elif isinstance(value, list):
                if len(value) < list_limit:
                    sanitized = _value_sanitize(value)
                    if sanitized is not None:
                        new_dict[key] = sanitized
            else:
                new_dict[key] = value
        return new_dict
    elif isinstance(d, list):
        if len(d) < list_limit:
            return [_value_sanitize(item) for item in d if _value_sanitize(item) is not None]
        return None
    else:
        return d


def format_namespace(namespace: str) -> str:
    if namespace:
        return namespace if namespace.endswith("-") else namespace + "-"
    return ""


def process_config(args: argparse.Namespace) -> dict[str, Union[str, int, None]]:
    config: dict = {}

    # Neo4j URI
    if args.db_url is not None:
        config["neo4j_uri"] = args.db_url
    elif os.getenv("NEO4J_URL"):
        config["neo4j_uri"] = os.getenv("NEO4J_URL")
    elif os.getenv("NEO4J_URI"):
        config["neo4j_uri"] = os.getenv("NEO4J_URI")
    else:
        logger.warning("No Neo4j URI provided. Using default: bolt://localhost:7687")
        config["neo4j_uri"] = "bolt://localhost:7687"

    # Neo4j username
    if args.username is not None:
        config["neo4j_user"] = args.username
    elif os.getenv("NEO4J_USERNAME"):
        config["neo4j_user"] = os.getenv("NEO4J_USERNAME")
    else:
        logger.warning("No Neo4j username provided. Using default: neo4j")
        config["neo4j_user"] = "neo4j"

    # Neo4j password
    if args.password is not None:
        config["neo4j_password"] = args.password
    elif os.getenv("NEO4J_PASSWORD"):
        config["neo4j_password"] = os.getenv("NEO4J_PASSWORD")
    else:
        logger.warning("No Neo4j password provided. Using default: password")
        config["neo4j_password"] = "password"

    # Neo4j database
    if args.database is not None:
        config["neo4j_database"] = args.database
    elif os.getenv("NEO4J_DATABASE"):
        config["neo4j_database"] = os.getenv("NEO4J_DATABASE")
    else:
        config["neo4j_database"] = "neo4j"

    # OpenAI API key (required for embeddings)
    if args.openai_api_key is not None:
        config["openai_api_key"] = args.openai_api_key
    elif os.getenv("OPENAI_API_KEY"):
        config["openai_api_key"] = os.getenv("OPENAI_API_KEY")
    else:
        logger.warning("No OpenAI API key provided — vector search will fail")
        config["openai_api_key"] = ""

    # Vector index name
    if args.vector_index is not None:
        config["vector_index_name"] = args.vector_index
    elif os.getenv("NEO4J_VECTOR_INDEX"):
        config["vector_index_name"] = os.getenv("NEO4J_VECTOR_INDEX")
    elif os.getenv("VECTOR_INDEX_NAME"):
        config["vector_index_name"] = os.getenv("VECTOR_INDEX_NAME")
    else:
        logger.warning("No vector index name provided. Using default: vector")
        config["vector_index_name"] = "vector"

    # Fulltext index name
    if args.fulltext_index is not None:
        config["fulltext_index_name"] = args.fulltext_index
    elif os.getenv("NEO4J_FULLTEXT_INDEX"):
        config["fulltext_index_name"] = os.getenv("NEO4J_FULLTEXT_INDEX")
    elif os.getenv("FULLTEXT_INDEX_NAME"):
        config["fulltext_index_name"] = os.getenv("FULLTEXT_INDEX_NAME")
    else:
        logger.warning("No fulltext index name provided. Using default: fulltext")
        config["fulltext_index_name"] = "fulltext"

    # Transport
    if args.transport is not None:
        config["transport"] = args.transport
    elif os.getenv("NEO4J_TRANSPORT"):
        config["transport"] = os.getenv("NEO4J_TRANSPORT")
    else:
        config["transport"] = "stdio"

    # Server host
    if args.server_host is not None:
        config["host"] = args.server_host
    elif os.getenv("NEO4J_MCP_SERVER_HOST"):
        config["host"] = os.getenv("NEO4J_MCP_SERVER_HOST")
    elif config["transport"] != "stdio":
        config["host"] = "127.0.0.1"
    else:
        config["host"] = None

    # Server port
    if args.server_port is not None:
        config["port"] = args.server_port
    elif os.getenv("NEO4J_MCP_SERVER_PORT"):
        config["port"] = int(os.getenv("NEO4J_MCP_SERVER_PORT"))
    elif config["transport"] != "stdio":
        config["port"] = 8000
    else:
        config["port"] = None

    # Server path
    if args.server_path is not None:
        config["path"] = args.server_path
    elif os.getenv("NEO4J_MCP_SERVER_PATH"):
        config["path"] = os.getenv("NEO4J_MCP_SERVER_PATH")
    elif config["transport"] != "stdio":
        config["path"] = "/mcp/"
    else:
        config["path"] = None

    # CORS allow origins
    if args.allow_origins is not None:
        config["allow_origins"] = [o.strip() for o in args.allow_origins.split(",") if o.strip()]
    elif os.getenv("NEO4J_MCP_SERVER_ALLOW_ORIGINS"):
        config["allow_origins"] = [
            o.strip() for o in os.getenv("NEO4J_MCP_SERVER_ALLOW_ORIGINS", "").split(",") if o.strip()
        ]
    else:
        config["allow_origins"] = []

    # Allowed hosts (DNS rebinding protection)
    if args.allowed_hosts is not None:
        config["allowed_hosts"] = [h.strip() for h in args.allowed_hosts.split(",") if h.strip()]
    elif os.getenv("NEO4J_MCP_SERVER_ALLOWED_HOSTS"):
        config["allowed_hosts"] = [
            h.strip() for h in os.getenv("NEO4J_MCP_SERVER_ALLOWED_HOSTS", "").split(",") if h.strip()
        ]
    else:
        config["allowed_hosts"] = ["localhost", "127.0.0.1"]

    # Namespace
    if args.namespace is not None:
        config["namespace"] = args.namespace
    elif os.getenv("NEO4J_NAMESPACE"):
        config["namespace"] = os.getenv("NEO4J_NAMESPACE")
    else:
        config["namespace"] = ""

    # Read-only mode
    if getattr(args, "read_only", None):
        config["read_only"] = True
    elif os.getenv("NEO4J_READ_ONLY"):
        config["read_only"] = os.getenv("NEO4J_READ_ONLY", "").strip().lower() == "true"
    else:
        config["read_only"] = False

    # Read timeout
    if getattr(args, "read_timeout", None) is not None:
        config["read_timeout"] = args.read_timeout
    elif os.getenv("NEO4J_READ_TIMEOUT"):
        config["read_timeout"] = int(os.getenv("NEO4J_READ_TIMEOUT"))
    else:
        config["read_timeout"] = 30

    # Schema sample size
    if getattr(args, "schema_sample_size", None) is not None:
        config["schema_sample_size"] = args.schema_sample_size
    elif os.getenv("NEO4J_SCHEMA_SAMPLE_SIZE"):
        config["schema_sample_size"] = int(os.getenv("NEO4J_SCHEMA_SAMPLE_SIZE"))
    else:
        config["schema_sample_size"] = 1000

    # Context limit (LIMIT clause in hybrid retrieval query)
    if getattr(args, "context_limit", None) is not None:
        config["context_limit"] = args.context_limit
    elif os.getenv("NEO4J_CONTEXT_LIMIT"):
        config["context_limit"] = int(os.getenv("NEO4J_CONTEXT_LIMIT"))
    else:
        config["context_limit"] = 100

    return config
