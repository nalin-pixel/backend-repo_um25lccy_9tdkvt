"""
Database Helper Functions with Mock Fallback

- Uses MongoDB when DATABASE_URL and DATABASE_NAME are set (default)
- Automatically falls back to an in-memory mock database when not configured
- You can force the mock by setting USE_MOCK_DB=true

Import and use create_document/get_documents just the same in your API code.
"""

from datetime import datetime, timezone
import os
from typing import Union, Dict, Any, List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from uuid import uuid4

# Load environment variables from .env file
load_dotenv()

# -------------------- Mock DB Implementation --------------------
class InsertOneResult:
    def __init__(self, inserted_id: str):
        self.inserted_id = inserted_id

class MockCollection:
    def __init__(self):
        self._docs: List[Dict[str, Any]] = []

    def insert_one(self, doc: Dict[str, Any]) -> InsertOneResult:
        # Assign an _id if not present
        if "_id" not in doc:
            doc["_id"] = str(uuid4())
        self._docs.append(doc)
        return InsertOneResult(doc["_id"])

    def find(self, filter_dict: Optional[Dict[str, Any]] = None):
        filter_dict = filter_dict or {}
        def match(d: Dict[str, Any]) -> bool:
            for k, v in filter_dict.items():
                if d.get(k) != v:
                    return False
            return True
        results = [d for d in self._docs if match(d)]
        return MockCursor(results)

class MockCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)

    def __next__(self):
        return next(iter(self._docs))

class MockDB:
    def __init__(self):
        self._collections: Dict[str, MockCollection] = {}

    def __getitem__(self, name: str) -> MockCollection:
        if name not in self._collections:
            self._collections[name] = MockCollection()
        return self._collections[name]

    def list_collection_names(self) -> List[str]:
        return list(self._collections.keys())

# -------------------- Real DB (Mongo) --------------------
_client = None
mongodb_available = False

try:
    from pymongo import MongoClient  # type: ignore
except Exception:
    MongoClient = None  # type: ignore

USE_MOCK_DB = (os.getenv("USE_MOCK_DB", "false").lower() == "true")
database_url = os.getenv("DATABASE_URL")
database_name = os.getenv("DATABASE_NAME")

# Initialize db handle (either real Mongo or mock)
db = None

if not USE_MOCK_DB and MongoClient and database_url and database_name:
    try:
        _client = MongoClient(database_url)
        db = _client[database_name]
        # Lightweight connectivity check (won't throw if server is unreachable until used)
        mongodb_available = True
    except Exception:
        # Fall back to mock on any error
        db = MockDB()
        mongodb_available = False
else:
    db = MockDB()
    mongodb_available = False

# -------------------- Helper functions --------------------

def create_document(collection_name: str, data: Union[BaseModel, dict]):
    """Insert a single document with timestamps. Returns inserted_id (str)."""
    # Convert Pydantic model to dict if needed
    if isinstance(data, BaseModel):
        data_dict = data.model_dump()
    else:
        data_dict = dict(data)

    now = datetime.now(timezone.utc)
    data_dict['created_at'] = now
    data_dict['updated_at'] = now

    result = db[collection_name].insert_one(data_dict)
    return str(result.inserted_id)


def get_documents(collection_name: str, filter_dict: dict = None, limit: int = None):
    """Get documents from collection as a list of dicts."""
    cursor = db[collection_name].find(filter_dict or {})
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)
