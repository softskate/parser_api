from io import BytesIO
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from fastapi import APIRouter, HTTPException, Depends, Query, Response, Security
from fastapi.security import  HTTPBasicCredentials, HTTPBearer, HTTPAuthorizationCredentials
from typing import List
import openpyxl
from rm_parser.schemas import ProductSchema
from rm_parser.database import Product, Crawl
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
        return [ProductSchema.model_validate(product) for product in products]

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
            .select()
            .where((Product.name.contains(query)) & (Product.crawlid == latest_finished_crawl.crawlid)).limit(limit)
        )
        return [ProductSchema.model_validate(product) for product in products]

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
            return [ProductSchema.model_validate(product) for product in products]

    raise HTTPException(status_code=404, detail="No products found for the given IDs")


@app.get("/products/output.xlsx")
def get_excel(credentials: HTTPBasicCredentials = Depends(verify_basic)):
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
            .where(Product.crawlid == latest_finished_crawl.crawlid)
            # .limit(5000)
        )
        if products:
            print(products.count())
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Products'
            print('Loading products')
            offset = 0
            limit = 1000
            dicts = []
            while True:
                print(offset)
                sliced = products.offset(offset).limit(limit)
                if not sliced: break
                dicts.extend([
                    {k: '\n'.join([f'{k1}: {v1}' for k1, v1 in v.items()] if isinstance(v, dict) else v) 
                    if isinstance(v, (dict, list)) else v for  k, v in ProductSchema.model_validate(product).model_dump().items()}
                        for product in sliced.dicts()])
                offset += limit
                
            print('Loading finished')

            headers = list(dicts[0].keys())
            print('adding headers')
            ws.append(headers)
            

            print('adding rows')
            for item in dicts:
                ws.append(list(item.values()))
            print('adding rows finished')

            file_stream = BytesIO()
            print('saving file stream')
            wb.save(file_stream)
            print('saving file stream finished')
            file_stream.seek(0)
            print('return file')

            return Response(
                content=file_stream.read(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=output.xlsx"}
            )

    raise HTTPException(status_code=404, detail="No products found")
