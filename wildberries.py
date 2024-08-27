import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fastapi import APIRouter, HTTPException, Depends, Query, Request, Security
from fastapi.security import  HTTPBearer, HTTPAuthorizationCredentials
from typing import List
from wb_parser.schemas import ParsingListCreate, ProductDetailsResponse, ProductResponse, ParsingItemCreate
from wb_parser.wildberries.database import ParsingList, ProductResponseModel as Product, \
    ProductDetailsResponseModel as ProductDetails, ParsingItem, Crawl
import requests
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

@app.post("/parsing-item/", response_model=ParsingItemCreate, status_code=201)
def create_parsing_item(item: ParsingItemCreate, user: dict = Depends(get_current_user)):
    product_id = item.product_id
    if product_id.startswith('http'):
        product_id = product_id.split('catalog/')[-1].split('/detail')[0]
        
    product_db = ParsingItem.get_or_none(
        product_id=product_id
    )
    if product_db is None:
        product_db = ParsingItem.create(
            product_id=product_id,
            user_id=user['item']
        )
    return ParsingItemCreate.model_validate(product_db)

@app.post("/parsing-items/", response_model=ParsingListCreate, status_code=201)
def create_list(parsing_list: ParsingListCreate, user: dict = Depends(get_current_user)):
    list_db = ParsingList.get_or_none(
        page_url=parsing_list.link
    )
    if list_db is None:
        list_type, list_val = [x for x in parsing_list.link.split('/') if x][-2:]
        if list_type == 'brands':
            f'https://static-basket-01.wbbasket.ru/vol0/data/brands/{list_val}.json'
            resp = requests.get('https://static-basket-01.wbbasket.ru/vol0/data/brands/salton.json')
            list_val = resp.json()['id']
            path = 'brands'
            param = 'brand'
        elif list_type == 'seller':
            path = 'sellers'
            param = 'supplier'
        else:
            raise HTTPException(status_code=400, detail="Invalid url format! It must brand or seller page.")
            
        list_db = ParsingList.create(
            start_url=f'https://catalog.wb.ru/{path}/v2/catalog?appType=1&{param}={list_val}&curr=rub&dest=-1257786&sort=popular&spp=30',
            page_url=parsing_list.link,
            user_id=user['item']
        )
    return ParsingListCreate.model_validate(list_db)

@app.get("/parsing-item/", response_model=List[ParsingItemCreate], status_code=200)
def get_parsing_items(user: dict = Depends(get_current_user)):
    items = ParsingItem.select()
    if items:
        return [ParsingItemCreate.model_validate(item) for item in items]

    raise HTTPException(status_code=404, detail="No items found")

@app.get("/parsing-items/", response_model=List[ParsingListCreate], status_code=200)
def get_parsing_lists(user: dict = Depends(get_current_user)):
    items = ParsingList.select()
    if items:
        return [ParsingListCreate.model_validate(item) for item in items]

    raise HTTPException(status_code=404, detail="No lists found")

@app.delete("/parsing-item/", status_code=200)
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

@app.delete("/parsing-items/", status_code=200)
def del_parsing_lists(item: ParsingListCreate, user: dict = Depends(get_current_user)):
    product_db = ParsingList.get_or_none(
        link=item.link
    )
    if product_db:
        if product_db.user_id == user:
            product_db.delete_instance()
        else:
            return {'success': False, 'message': 'You are not the author of this item.'}

    return {'seccess': True, 'message': 'Successfully deleted'}

@app.get("/products/", response_model=List[ProductResponse])
def get_products(offset: int = 0, limit: int = 10, user: dict = Depends(get_current_user)):
    products = Product.select().offset(offset).limit(limit)
    return [ProductResponse.model_validate(product) for product in products]

@app.get("/products/search/", response_model=List[ProductResponse])
def search_products(query: str, limit: int = 10, user: dict = Depends(get_current_user)):
    products = Product.select().where(Product.name.contains(query)).limit(limit)
    return [ProductResponse.model_validate(product) for product in products]

@app.get("/products/by_url/", response_model=List[ProductDetailsResponse])
def get_products_by_ids(product_urls: List[str] = Query(...), user: User = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            ProductDetails
            .select(Product.price, ProductDetails)
            .join(Product, on=(ProductDetails.productUrl == Product.productUrl))
            .where((Product.productUrl.in_(product_urls)) & (Product.crawlid == latest_finished_crawl.crawlid))
        )
        if products:
            return [ProductDetailsResponse.model_validate(product) for product in products.dicts()]

    raise HTTPException(status_code=404, detail="No products found for the given IDs")
