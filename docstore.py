"""
Functions to connect to a document store and fetch documents from it.
"""
import urllib.parse
import pymongo
import os


_CLIENT = None


def connect(user=None, password=None, uri=None):
    """Connects to the document store, here MongoDB."""
    global _CLIENT
    if _CLIENT is not None and not any([user, password, uri]):
        return _CLIENT
    mongodb_user = urllib.parse.quote_plus(user or os.environ["MONGODB_USER"])
    mongodb_password = urllib.parse.quote_plus(password or os.environ["MONGODB_PASSWORD"])
    mongodb_host = uri or os.environ["MONGODB_HOST"]
    connection_string = (
        f"mongodb+srv://{mongodb_user}:{mongodb_password}"
        f"@{mongodb_host}/?retryWrites=true&w=majority"
    )
    client = pymongo.MongoClient(
        connection_string,
        appname="ask-fsdl",
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=10000,
        socketTimeoutMS=30000,
    )
    if not any([user, password, uri]):
        _CLIENT = client
    return client


def get_database(db=None, client=None):
    """Accesses a specific database in the document store."""
    client = client or connect()
    db = db or os.environ.get("MONGODB_DATABASE")
    if db is None:
        raise ValueError(
            "No database specified and MONGODB_DATABASE is not set"
        )
    if isinstance(db, pymongo.database.Database):
        return db
    else:
        return client.get_database(db)


def get_collection(collection=None, db=None, client=None):
    """Accesses a specific collection in the document store."""
    db = get_database(db, client)
    collection = collection or os.environ.get("MONGODB_COLLECTION")
    if collection is None:
        raise ValueError(
            "No collection specified and MONGODB_COLLECTION is not set"
        )
    if isinstance(collection, pymongo.collection.Collection):
        return collection
    else:
        return db.get_collection(collection)


def get_documents(collection=None, db=None, client=None, query=None):
    """Fetches a collection of documents from a document database."""
    collection = get_collection(collection, db, client)
    query = query or {"metadata.ignore": False}
    return list(collection.find(query))


def drop(collection=None, db=None, client=None):
    """Drops a collection from the database."""
    collection = get_collection(collection, db, client)
    collection.drop()


def query(query, projection=None, collection=None, db=None):
    """Runs a query against the document db and returns a list of results."""
    collection = get_collection(collection, db)
    return list(collection.find(query, projection))


def query_one(query, projection=None, collection=None, db=None):
    """Runs a query against the document db and returns the first result."""
    collection = get_collection(collection, db)
    return collection.find_one(query, projection)
