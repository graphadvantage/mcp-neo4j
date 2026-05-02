import base64
import json
from io import BytesIO

from neo4j import Driver
from PIL import Image

FETCH_QUERY = """
MATCH (n:Image|Table)
WHERE n.image_base64 IS NOT NULL AND n.bytes IS NULL
RETURN n.id AS id, n.image_base64 AS image_base64
"""

UPDATE_QUERY = """
WITH apoc.convert.fromJsonMap($props) AS map
MATCH (n:Image|Table {id: $id})
SET n += map
"""


def _image_properties(image_base64: str) -> dict | None:
    try:
        data = base64.b64decode(image_base64)
        with Image.open(BytesIO(data)) as img:
            width, height = img.size
            aspect_ratio = max(width / height, height / width) if width and height else None
            return {
                "bytes": len(image_base64),
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
            }
    except Exception as e:
        print(f"\n  Error reading image: {e}")
        return None


def compute_image_properties(driver: Driver) -> None:
    with driver.session() as session:
        records = list(session.run(FETCH_QUERY))

    if not records:
        print("  No images/tables without size metadata.")
        return

    print(f"  Computing properties for {len(records)} image/table node(s)...")
    updated = 0

    with driver.session() as session:
        for record in records:
            node_id = record["id"]
            props = _image_properties(record["image_base64"])
            if props:
                session.run(UPDATE_QUERY, id=node_id, props=json.dumps(props))
                updated += 1
                print(f"\r  Updated {updated}/{len(records)}", end="", flush=True)

    print(f"\n  Done. {updated} nodes updated.")
