from typing import Optional, List
from uuid import uuid4, UUID

from fastapi import FastAPI, HTTPException, Path, Query, Body, Header, status
from pydantic import BaseModel, Field, constr, conint, confloat


app = FastAPI(title="Books API (Practice)")


# ---------- Pydantic-модели ----------
ISBN = constr(strip_whitespace=True, min_length=10, max_length=17)  # ISBN-10/13
Year = conint(ge=1400, le=2100)
Price = confloat(gt=0)
Rating = confloat(ge=0, le=5)


class BookCreate(BaseModel):
    title: str = Field(..., min_length=1, description="Название книги")
    author: str = Field(..., min_length=1, description="Автор")
    year: Year = Field(..., description="Год издания")
    price: Price = Field(..., description="Цена, > 0")
    isbn: Optional[ISBN] = Field(None, description="ISBN-10/13")
    in_stock: bool = Field(default=True, description="В наличии?")
    rating: Optional[Rating] = Field(None, description="Оценка 0..5")


class Book(BookCreate):
    id: UUID


class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    year: Optional[Year] = None
    price: Optional[Price] = None
    isbn: Optional[ISBN] = None
    in_stock: Optional[bool] = None
    rating: Optional[Rating] = None


# ---------- Память вместо БД ----------
DB: dict[UUID, Book] = {}


# ---------- Вспомогательные функции ----------
def _validate_price_limit(price_value: float) -> None:
    if price_value is not None and price_value > 1_000_000:
        # Требование п.2: если price > 1_000_000 — 400 Bad Request
        raise HTTPException(status_code=400, detail="Price must be <= 1_000_000")


def _apply_sort(items: List[Book], sort_by: Optional[str], order: Optional[str]) -> List[Book]:
    if not sort_by:
        return items
    if sort_by not in {"price", "year"}:
        raise HTTPException(status_code=400, detail="sort_by must be 'price' or 'year'")
    reverse = False
    if order:
        if order not in {"asc", "desc"}:
            raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")
        reverse = order == "desc"
    return sorted(items, key=(lambda b: getattr(b, sort_by)), reverse=reverse)


# ---------- Endpoints ----------
@app.get("/", tags=["root"])
def root():
    return {"msg": "Books API. Откройте /docs для Swagger UI."}


# Список книг + фильтры + сортировка
@app.get("/books/", response_model=List[Book], tags=["books"])
def list_books(
    limit: int = Query(10, ge=1, le=100),
    q: Optional[str] = Query(None, description="Поиск по названию/автору"),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    in_stock: Optional[bool] = None,
    sort_by: Optional[str] = Query(None, description="'price' или 'year'"),
    order: Optional[str] = Query(None, description="'asc' или 'desc'"),
):
    items = list(DB.values())

    # Фильтры
    if q:
        ql = q.lower()
        items = [b for b in items if ql in b.title.lower() or ql in b.author.lower()]
    if min_price is not None:
        items = [b for b in items if b.price >= min_price]
    if max_price is not None:
        items = [b for b in items if b.price <= max_price]
    if in_stock is not None:
        items = [b for b in items if b.in_stock == in_stock]

    # Сортировка (п.1)
    items = _apply_sort(items, sort_by, order)

    return items[:limit]


# Получить книгу по id
@app.get("/books/{book_id}", response_model=Book, tags=["books"])
def get_book(book_id: UUID = Path(...)):
    book = DB.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


# HEAD
@app.head("/books/{book_id}", tags=["books"])
def head_book(book_id: UUID = Path(...)):
    if book_id not in DB:
        raise HTTPException(status_code=404, detail="Not found")
    return


# OPTIONS
@app.options("/books/", tags=["books"])
def options_books():
    return {"allow": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]}


# Создать книгу (с проверкой максимальной цены)
@app.post("/books/", response_model=Book, status_code=status.HTTP_201_CREATED, tags=["books"])
def create_book(payload: BookCreate = Body(...)):
    _validate_price_limit(payload.price)
    new_id = uuid4()
    book = Book(id=new_id, **payload.model_dump())
    DB[new_id] = book
    return book


# Полная замена книги (с проверкой максимальной цены)
@app.put("/books/{book_id}", response_model=Book, tags=["books"])
def replace_book(book_id: UUID, payload: BookCreate = Body(...)):
    if book_id not in DB:
        raise HTTPException(status_code=404, detail="Book not found")
    _validate_price_limit(payload.price)
    new_book = Book(id=book_id, **payload.model_dump())
    DB[book_id] = new_book
    return new_book


# Частичное обновление (с проверкой максимальной цены, если указана)
@app.patch("/books/{book_id}", response_model=Book, tags=["books"])
def update_book(book_id: UUID, payload: BookUpdate = Body(...)):
    existing = DB.get(book_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Book not found")
    updated_data = existing.model_dump()
    partial = payload.model_dump(exclude_unset=True)
    if "price" in partial and partial["price"] is not None:
        _validate_price_limit(float(partial["price"]))
    for k, v in partial.items():
        updated_data[k] = v
    updated_book = Book(**updated_data)
    DB[book_id] = updated_book
    return updated_book


# Удаление
@app.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["books"])
def delete_book(book_id: UUID):
    if book_id not in DB:
        raise HTTPException(status_code=404, detail="Book not found")
    del DB[book_id]
    return


# Эхо-пример
@app.post("/echo/", tags=["utils"])
def echo(payload: dict = Body(...), x_request_id: Optional[str] = Header(None)):
    return {"received": payload, "x-request-id": x_request_id}


# Массовое создание (п.3)
@app.post("/books/bulk/", response_model=List[Book], status_code=status.HTTP_201_CREATED, tags=["books"])
def bulk_create(books: List[BookCreate] = Body(...)):
    created: List[Book] = []
    for b in books:
        _validate_price_limit(b.price)
        new_id = uuid4()
        book = Book(id=new_id, **b.model_dump())
        DB[new_id] = book
        created.append(book)
    return created


# Статистика (п.4)
@app.get("/books/stats", tags=["books"])
def stats():
    items = list(DB.values())
    count = len(items)
    avg_price = sum((b.price for b in items), 0.0) / count if count else 0.0
    in_stock_count = sum(1 for b in items if b.in_stock)
    return {"count": count, "avg_price": avg_price, "in_stock_count": in_stock_count}


