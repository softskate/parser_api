from datetime import datetime, timedelta
from io import BytesIO
import json
import sys
import os
import openpyxl

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fastapi import APIRouter, HTTPException, Depends, Response, Security, Query, Request
from fastapi.security import  HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Dict
from mv_parser.schemas import ProductSchema, ParsingItemCreate
from mv_parser.database import Product, ParsingItem, Crawl, db
from contextlib import asynccontextmanager
import requests
from database import User
from utils import verify_basic


def reform(item):
    for key, val in item.items():
        try: item[key] = json.loads(val)
        except Exception: pass
    return item


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
    return {'item': user.get_id()}


@app.post("/create-user/", status_code=201)
async def create_user(request: Request, user: dict = Depends(get_current_user)):
    data = await request.json()
    new_user = User.create(**data)
    return {'success': True, 'user': new_user.token}


@app.post("/parsing-items/", response_model=ParsingItemCreate, status_code=201)
def create_parsing_item(item: ParsingItemCreate, user: dict = Depends(get_current_user)):
    link = item.link.split('?')[0].strip('/')
    url_split = link.split('/')

    if len(url_split) > 4:
        parent_cat_id = url_split[3].split('-')[-1]
        cat_id = url_split[4].split('-')[-1]

        if parent_cat_id.isdigit() and cat_id.isdigit():
            product_db = ParsingItem.get_or_none(
                link=item.link
            )
            if product_db is None:
                product_db = ParsingItem.create(
                    link=item.link,
                    user_id=user['item']
                )
            return ParsingItemCreate.model_validate(product_db)

    raise HTTPException(status_code=400, detail="The given URL is not valid. Send a product list link like: https://www.mvideo.ru/komputernaya-tehnika-4107/monitory-101")


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
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished == True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = Product.select().where(Product.crawlid == latest_finished_crawl.crawlid).offset(offset).limit(limit)
        if products:
            return [ProductSchema.model_validate(product) for product in products]
    
    raise HTTPException(status_code=404, detail="No product found.")


@app.get("/products/search/", response_model=List[ProductSchema])
def search_products(query: str, limit: int = 10, user: dict = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished == True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = Product.select().where((Product.name.contains(query)) & (Product.crawlid == latest_finished_crawl.crawlid)).limit(limit)
        if products:
            return [ProductSchema.model_validate(reform(product)) for product in products.dicts()]
    
    raise HTTPException(status_code=404, detail="No product found for the given query.")


@app.get("/products/by_url/", response_model=List[ProductSchema])
def get_products_by_url(product_urls: List[str] = Query(...), user: User = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished == True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            Product.select()
            .where(
                (Product.productUrl.in_(product_urls))
                & (Product.crawlid == latest_finished_crawl.crawlid))
        )
        if products:
            return [ProductSchema.model_validate(reform(product)) for product in products.dicts()]

    raise HTTPException(status_code=404, detail="No product found for the given URLS")


@app.get("/products/output.xlsx")
def get_excel(credentials: HTTPBasicCredentials = Depends(verify_basic)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished == True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            Product.select()
            .where(Product.crawlid == latest_finished_crawl.crawlid))
        if products:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Products'


            dicts = [
                {k: '\n'.join([f'{k1}: {v1}' for k1, v1 in v.items()] if isinstance(v, dict) else v) if isinstance(v, (dict, list)) else v for  k, v in ProductSchema.model_validate(reform(product)).model_dump().items()}
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

