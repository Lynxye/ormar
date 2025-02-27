from typing import List, Optional

import databases
import pytest
import sqlalchemy
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import AsyncClient

import ormar
from tests.settings import DATABASE_URL

app = FastAPI()
metadata = sqlalchemy.MetaData()
database = databases.Database(DATABASE_URL, force_rollback=True)
app.state.database = database


@app.on_event("startup")
async def startup() -> None:
    database_ = app.state.database
    if not database_.is_connected:
        await database_.connect()


@app.on_event("shutdown")
async def shutdown() -> None:
    database_ = app.state.database
    if database_.is_connected:
        await database_.disconnect()


class Category(ormar.Model):
    class Meta:
        tablename = "categories"
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)


class Item(ormar.Model):
    class Meta:
        tablename = "items"
        metadata = metadata
        database = database

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=100)
    category: Optional[Category] = ormar.ForeignKey(Category, nullable=True)


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    engine = sqlalchemy.create_engine(DATABASE_URL)
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


@app.get("/items", response_model=List[Item])
async def get_items():
    items = await Item.objects.select_related("category").all()
    return items


@app.get("/items/raw", response_model=List[Item])
async def get_raw_items():
    items = await Item.objects.all()
    return items


@app.post("/items", response_model=Item)
async def create_item(item: Item):
    await item.save()
    return item


@app.post("/categories", response_model=Category)
async def create_category(category: Category):
    await category.save()
    return category


@app.get("/items/{item_id}")
async def get_item(item_id: int):
    item = await Item.objects.get(pk=item_id)
    return item


@app.put("/items/{item_id}")
async def update_item(item_id: int, item: Item):
    item_db = await Item.objects.get(pk=item_id)
    return await item_db.update(**item.dict())


@app.delete("/items/{item_id}")
async def delete_item(item_id: int):
    item_db = await Item.objects.get(pk=item_id)
    return {"deleted_rows": await item_db.delete()}


@pytest.mark.asyncio
async def test_all_endpoints():
    client = AsyncClient(app=app, base_url="http://testserver")
    async with client as client, LifespanManager(app):
        response = await client.post("/categories", json={"name": "test cat"})
        category = response.json()
        response = await client.post(
            "/items", json={"name": "test", "id": 1, "category": category}
        )
        item = Item(**response.json())
        assert item.pk is not None

        response = await client.get("/items")
        items = [Item(**item) for item in response.json()]
        assert items[0] == item

        item.name = "New name"
        response = await client.put(f"/items/{item.pk}", json=item.dict())
        assert response.json() == item.dict()

        response = await client.get("/items")
        items = [Item(**item) for item in response.json()]
        assert items[0].name == "New name"

        response = await client.get("/items/raw")
        items = [Item(**item) for item in response.json()]
        assert items[0].name == "New name"
        assert items[0].category.name is None

        response = await client.get(f"/items/{item.pk}")
        new_item = Item(**response.json())
        assert new_item == item

        response = await client.delete(f"/items/{item.pk}")
        assert response.json().get("deleted_rows", "__UNDEFINED__") != "__UNDEFINED__"
        response = await client.get("/items")
        items = response.json()
        assert len(items) == 0

        await client.post(
            "/items", json={"name": "test_2", "id": 2, "category": category}
        )
        response = await client.get("/items")
        items = response.json()
        assert len(items) == 1

        item = Item(**items[0])
        response = await client.delete(f"/items/{item.pk}")
        assert response.json().get("deleted_rows", "__UNDEFINED__") != "__UNDEFINED__"

        response = await client.get("/docs")
        assert response.status_code == 200
