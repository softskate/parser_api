from datetime import datetime, timedelta
from io import BytesIO
import json
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Security, Query
from fastapi.security import  HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials, HTTPBasic
from typing import List
import openpyxl
from cl_parser.schemas import ProductResponse, ParsingItemCreate, ProductDetailsResponse
from cl_parser.database import ProductResponseModel as Product, \
    ProductDetailsResponseModel as ProductDetails, ParsingItem, Crawl
from database import User
from utils import verify_basic


app = APIRouter()
security = HTTPBearer()


def reform(item):
    for key, val in item.items():
        try: item[key] = json.loads(val)
        except Exception: pass
    return item


def reform_text(item):
    for key, val in item.items():
        try:
            item[key] = json.loads(val)
            item[key] = '\n'.join([f'{k}: {v}' for k, v in item[key].items()])
        except Exception: pass
    return item


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
    url_split = link.split('/')
    path_type = url_split[3]

    product_db = ParsingItem.get_or_none(
        link=link
    )
    if product_db is None:
        product_db = ParsingItem.create(
            link=link,
            user_id=user['item'],
            item_type=path_type
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

@app.get("/products/", response_model=List[ProductResponse])
def get_products(offset: int = 0, limit: int = 10, user: dict = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.created_at < datetime.now() - timedelta(hours=2))
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = Product.select().where(Product.crawlid == latest_finished_crawl.crawlid).offset(offset).limit(limit)
        return [ProductResponse.model_validate(product) for product in products]

@app.get("/products/search/", response_model=List[ProductResponse])
def search_products(query: str, limit=10, user: dict = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.created_at < datetime.now() - timedelta(hours=2))
        .order_by(Crawl.created_at.desc())
        .first()
    )
    if latest_finished_crawl:
        products = (
            Product
            .select()
            .where((Product.crawlid == latest_finished_crawl.crawlid) & (Product.name.contains(query)))
            .group_by(Product.productUrl)
            .limit(limit)
        )
        return [ProductResponse.model_validate(product) for product in products]
        

@app.get("/products/by_url/", response_model=List[ProductDetailsResponse])
def get_products_by_url(product_urls: List[str] = Query(...), user: User = Depends(get_current_user)):
    products = (
        ProductDetails
        .select(Product.price, ProductDetails)
        .join(Product, on=(ProductDetails.productUrl == Product.productUrl))
        .where(Product.productUrl.in_(product_urls))
    )
    if products:
        return [ProductDetailsResponse.model_validate(reform(product)) for product in products.dicts()]

    raise HTTPException(status_code=404, detail="No products found for the given URLS")


@app.get("/products/output.xlsx")
def get_excel(credentials: HTTPBasicCredentials = Depends(verify_basic)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.created_at < datetime.now() - timedelta(hours=2))
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            ProductDetails
            .select(Product.price, ProductDetails)
            .join(Product, on=(ProductDetails.productUrl == Product.productUrl))
            .where(Product.crawlid == latest_finished_crawl.crawlid)
        )
        if products:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Products'


            dicts = [
                {k: '\n'.join([f'{k1}: {v1}' for k1, v1 in v.items()] if isinstance(v, dict) else v) if isinstance(v, (dict, list)) else v for  k, v in ProductDetailsResponse.model_validate(reform(product)).model_dump().items()}
                     for product in products.dicts()]

            
            headers = list(dicts[0].keys())
            ws.append(headers)
            

            for item in dicts:
                ws.append(list(item.values()))

            file_stream = BytesIO()
            wb.save(file_stream)
            file_stream.seek(0)

            return Response(
                content=file_stream.read(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=output.xlsx"}
            )
    

    raise HTTPException(status_code=404, detail="No products found")

