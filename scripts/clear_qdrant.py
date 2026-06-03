import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value

def main():
    _load_dotenv()
    url = (os.getenv("QDRANT_API_URL") or "").rstrip("/")
    api_key = os.getenv("QDRANT_API_KEY") or ""
    
    if not url or not api_key:
        print("Missing QDRANT_API_URL or QDRANT_API_KEY in .env")
        return

    print(f"Connecting to Qdrant at {url}")
    
    # 1. Get all collections
    request = urllib.request.Request(
        f"{url}/collections",
        headers={
            "api-key": api_key,
            "Authorization": f"Bearer {api_key}",
        }
    )
    
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            body = response.read().decode("utf-8")
            res_json = json.loads(body)
            collections = res_json.get("result", {}).get("collections", [])
    except Exception as e:
        print(f"Failed to fetch collections: {e}")
        return
        
    if not collections:
        print("No collections found in Qdrant.")
        return
        
    print(f"Found {len(collections)} collection(s).")
    
    for coll in collections:
        name = coll.get("name")
        if not name:
            continue
            
        print(f"Deleting collection: {name}...")
        del_req = urllib.request.Request(
            f"{url}/collections/{name}",
            method="DELETE",
            headers={
                "api-key": api_key,
                "Authorization": f"Bearer {api_key}",
            }
        )
        try:
            with urllib.request.urlopen(del_req, timeout=30.0) as response:
                print(f"Collection {name} deleted successfully.")
        except urllib.error.HTTPError as e:
            print(f"Failed to delete {name}. Status code: {e.code}")
        except Exception as e:
            print(f"Failed to delete {name}. Error: {e}")

if __name__ == "__main__":
    main()
