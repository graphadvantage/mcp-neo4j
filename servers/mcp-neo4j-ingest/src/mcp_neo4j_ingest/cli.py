import sys

import click
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

ALL_STEPS = ["indexes", "parse", "embed", "entities", "images"]


def _parse_steps(steps_str: str) -> list[str]:
    if steps_str == "all":
        return ALL_STEPS
    steps = [s.strip() for s in steps_str.split(",")]
    invalid = [s for s in steps if s not in ALL_STEPS]
    if invalid:
        raise click.BadParameter(f"Unknown steps: {invalid}. Valid: {ALL_STEPS}")
    return steps


@click.command()
@click.argument("docs_path", type=click.Path(exists=True, file_okay=False))
@click.option("--neo4j-uri", envvar="NEO4J_URI", required=True, help="Neo4j connection URI")
@click.option("--neo4j-username", envvar="NEO4J_USERNAME", default="neo4j", show_default=True)
@click.option("--neo4j-password", envvar="NEO4J_PASSWORD", required=True)
@click.option("--neo4j-database", envvar="NEO4J_DATABASE", default="neo4j", show_default=True)
@click.option("--openai-api-key", envvar="OPENAI_API_KEY", default=None)
@click.option("--unstructured-api-key", envvar="UNSTRUCTURED_API_KEY", default=None)
@click.option(
    "--domain",
    default="general technical",
    show_default=True,
    help="Domain description for entity extraction prompt (e.g. 'petroleum exploration, reservoir analysis')",
)
@click.option(
    "--entity-types",
    default=None,
    help="Comma-separated entity types to focus on (e.g. 'Formation,Wellbore,Fault')",
)
@click.option("--model", default="gpt-4o", show_default=True, help="OpenAI model for entity extraction")
@click.option("--embedding-model", default="text-embedding-ada-002", show_default=True)
@click.option(
    "--steps",
    default="all",
    show_default=True,
    help=f"Steps to run (comma-separated or 'all'): {', '.join(ALL_STEPS)}",
)
@click.option("--max-characters", default=1500, show_default=True, help="Max characters per chunk")
@click.option("--max-chunks", default=10000, show_default=True, help="Max chunks per entity extraction run")
@click.option("--vector-index", default="chunk_embedding", show_default=True)
@click.option("--fulltext-index", default="entity_text", show_default=True)
@click.option("--no-skip-existing", is_flag=True, default=False, help="Re-parse already-ingested documents")
def main(
    docs_path: str,
    neo4j_uri: str,
    neo4j_username: str,
    neo4j_password: str,
    neo4j_database: str,
    openai_api_key: str | None,
    unstructured_api_key: str | None,
    domain: str,
    entity_types: str | None,
    model: str,
    embedding_model: str,
    steps: str,
    max_characters: int,
    max_chunks: int,
    vector_index: str,
    fulltext_index: str,
    no_skip_existing: bool,
) -> None:
    """Ingest documents from DOCS_PATH into a Neo4j knowledge graph for GraphRAG."""

    try:
        selected_steps = _parse_steps(steps)
    except click.BadParameter as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    entity_type_list = [t.strip() for t in entity_types.split(",")] if entity_types else None

    needs_openai = any(s in selected_steps for s in ("embed", "entities"))
    needs_unstructured = "parse" in selected_steps

    if needs_openai and not openai_api_key:
        click.echo("Error: --openai-api-key (or OPENAI_API_KEY) is required for embed/entities steps.", err=True)
        sys.exit(1)
    if needs_unstructured and not unstructured_api_key:
        click.echo("Error: --unstructured-api-key (or UNSTRUCTURED_API_KEY) is required for parse step.", err=True)
        sys.exit(1)

    click.echo(f"Connecting to Neo4j at {neo4j_uri}...")
    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_username, neo4j_password), database=neo4j_database)

    try:
        driver.verify_connectivity()
    except Exception as e:
        click.echo(f"Failed to connect to Neo4j: {e}", err=True)
        sys.exit(1)

    click.echo(f"Running steps: {', '.join(selected_steps)}\n")

    if "indexes" in selected_steps:
        from mcp_neo4j_ingest.indexes import create_indexes
        click.echo("[1/5] Creating indexes...")
        create_indexes(driver, vector_index, fulltext_index)
        click.echo()

    if "parse" in selected_steps:
        from mcp_neo4j_ingest.parse import parse_directory
        click.echo("[2/5] Parsing documents...")
        parse_directory(
            driver,
            docs_path,
            unstructured_api_key,
            max_characters=max_characters,
            skip_existing=not no_skip_existing,
        )
        click.echo()

    if "embed" in selected_steps:
        from mcp_neo4j_ingest.embed import embed_chunks
        click.echo("[3/5] Generating embeddings...")
        embed_chunks(driver, openai_api_key, embedding_model)
        click.echo()

    if "entities" in selected_steps:
        from mcp_neo4j_ingest.entities import extract_entities
        click.echo(f"[4/5] Extracting entities (domain: {domain})...")
        extract_entities(driver, openai_api_key, domain, entity_type_list, model, max_chunks)
        click.echo()

    if "images" in selected_steps:
        from mcp_neo4j_ingest.images import compute_image_properties
        click.echo("[5/5] Computing image properties...")
        compute_image_properties(driver)
        click.echo()

    driver.close()
    click.echo("Ingestion complete.")
