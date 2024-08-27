from datetime import datetime, timedelta
from io import BytesIO
import sys
import os
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fastapi import APIRouter, HTTPException, Depends, Query, Response, Security
from fastapi.security import  HTTPBasic, HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from typing import List
from logic_parser.schemas import ProductSchema
from logic_parser.database import Product, Product, Crawl
import openpyxl
from database import User
from utils import verify_basic


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


@app.get("/products/", response_model=List[ProductSchema])
def get_products(offset: int = 0, limit: int = 10, user: dict = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished==True)
        .order_by(Crawl.created_at.desc())
        .first()
    )
    if latest_finished_crawl:
        products = (
            Product
            .select()
            .where(Product.crawlid == latest_finished_crawl.crawlid).limit(limit)
            .offset(offset).limit(limit)
        )
        return [ProductSchema.model_validate(product) for product in products.dicts()]

    raise HTTPException(status_code=404, detail="No products found.")


@app.get("/products/search/", response_model=List[ProductSchema])
def search_products(query: str, limit: int = 10, user: dict = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished==True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            Product
            .where((Product.name.contains(query)) & (Product.crawlid == latest_finished_crawl.crawlid)).limit(limit)
        )
        return [ProductSchema.model_validate(product) for product in products.dicts()]

    raise HTTPException(status_code=404, detail="No products found for the given query.")


@app.get("/products/by_ids/", response_model=List[ProductSchema])
def get_products_by_ids(product_ids: List[str] = Query(...), user: User = Depends(get_current_user)):
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        .where(Crawl.finished==True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            Product
            .select()
            .where((Product.productId.in_(product_ids)) & (Product.crawlid == latest_finished_crawl.crawlid))
        )
        if products:
            return [ProductSchema.model_validate(product) for product in products.dicts()]

    raise HTTPException(status_code=404, detail="No products found for the given IDs")


@app.get("/products/output.xlsx")
def get_excel(credentials: HTTPBasicCredentials = Depends(verify_basic)):
    day_ago = datetime.now() - timedelta(days=1)
    latest_finished_crawl: Crawl = (
        Crawl
        .select()
        # .where((Crawl.finished == True) & (Crawl.created_at > day_ago))
        .where(Crawl.finished == True)
        .order_by(Crawl.created_at.desc())
        .first()
    )

    if latest_finished_crawl:
        products = (
            Product
            .select()
            .where(Product.crawlid == latest_finished_crawl.crawlid)
        )
        if products:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Products'
            offset = 0
            limit = 5000
            dicts = []
            while True:
                print(offset, limit)
                sliced = products.offset(offset).limit(limit)
                if not sliced: break
                dicts.extend([
                    {k: '\n'.join([f'{k1}: {v1}' for k1, v1 in v.items()] if isinstance(v, dict) else v) 
                    if isinstance(v, (dict, list)) else v for  k, v in ProductSchema.model_validate(product).model_dump().items()}
                        for product in sliced.dicts()])
                offset += limit
                time.sleep(1)

            headers = list(dicts[0].keys())+['Дата обновление']
            ws.append(headers)
            
            print('writing data')
            for item in dicts:
                ws.append(list(item.values())+[str(latest_finished_crawl.created_at)])
                time.sleep(0.001)

            print('saving data')
            file_stream = BytesIO()
            wb.save(file_stream)
            file_stream.seek(0)

            print('returning data')
            return Response(
                content=file_stream.read(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=output.xlsx"}
            )

    raise HTTPException(status_code=404, detail="No products found")
