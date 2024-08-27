import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)


from fastapi import APIRouter, HTTPException, Depends, Request, Security, Query
from fastapi.security import  HTTPBearer, HTTPAuthorizationCredentials
from typing import List
from ozon_parser.schemas import ProductSchema, ParsingItemCreate, ProductDetailSchema
from ozon_parser.database import Product, ProductDetails, ParsingItem
from database import User


app = APIRouter()
security = HTTPBearer()

# Dependency to get the current user
def get_current_user(token: HTTPAuthorizationCredentials = Security(security)):
    """
    Проверка Bearer токена.
    
    :param credentials: HTTPAuthorizationCredentials
    :raises HTTPException: Если токен невалиден или отсутствует
    """
    user = User.get_or_none(token=token.credentials)
    if user is None:
        raise HTTPException(status_code=403, detail="Could not validate credentials")
    return {"username": user.name, 'item': user.get_id()}


@app.post("/create-user/", status_code=201)
async def create_user(request: Request, user: dict = Depends(get_current_user)):
    data = await request.json()
    new_user = User.create(**data)
    return {'success': True, 'user': new_user.token}

@app.post("/parsing-items/", response_model=ParsingItemCreate, status_code=201)
def create_parsing_item(item: ParsingItemCreate, user: dict = Depends(get_current_user)):
    link = item.link.split('?')[0].strip('/')
    page_type = link.split('/')[3]

    product_db = ParsingItem.get_or_none(
        link=link
    )
    if product_db is None:
        product_db = ParsingItem.create(
            link=link,
            user_id=user['item'],
            item_type=page_type
        )
    return ParsingItemCreate.model_validate(product_db)


@app.get("/parsing-items/", response_model=List[ParsingItemCreate], status_code=200)
def get_parsing_items(user: dict = Depends(get_current_user)):
    items = ParsingItem.select()
    if items:
        return [ParsingItemCreate.model_validate(item) for item in items]

    raise HTTPException(status_code=404, detail="No items found")


@app.delete("/parsing-items/", status_code=200)
def del_parsing_item(item: ParsingItemCreate, user: dict = Depends(get_current_user)):
    product_db = ParsingItem.get_or_none(
        link=item.link
    )
    if product_db:
        if product_db.user_id == user:
            product_db.delete_instance()
        else:
            return {'success': False, 'message': 'You are not the author of this item.'}

    return {'seccess': True, 'message': 'Successfully deleted'}


@app.get("/products/", response_model=List[ProductSchema])
def get_products(offset: int = 0, limit: int = 10, user: dict = Depends(get_current_user)):
    products = Product.select().offset(offset).limit(limit)
    return [ProductSchema.model_validate(product) for product in products]

@app.get("/products/search/", response_model=List[ProductSchema])
def search_products(query: str, user: dict = Depends(get_current_user)):
    products = Product.select().where(Product.name.contains(query))
    return [ProductSchema.model_validate(product) for product in products]

@app.get("/products/by_url/", response_model=List[ProductDetailSchema])
def get_products_by_url(product_urls: List[str] = Query(...), user: User = Depends(get_current_user)):
    products = ProductDetails.select().where(ProductDetails.productUrl.in_(product_urls))
    if not products:
        raise HTTPException(status_code=404, detail="No products found for the given URLS")
    return [ProductDetailSchema.model_validate(product) for product in products]
