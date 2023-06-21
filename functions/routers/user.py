import os
import sys
from typing import Any, Dict
from fastapi import APIRouter, Request, Depends

FUNCTIONS_DIR_PATH = os.path.dirname(os.path.dirname(__file__))
sys.path.append(FUNCTIONS_DIR_PATH)

from domain import user
from domain.authentication import authenticate_user
from models.user import EMPTY_SK, UserItem
from utils.process import hub_lambda_handler_wrapper_with_rtn_value, hub_lambda_handler_wrapper

user_router = APIRouter()


# ? In the future, add query parameters to the path (ex: ?sk=xxx).
# Path parameters are used to identify GET resource because GET requests do not have a request body.
# https://fastapi.tiangolo.com/ja/tutorial/path-params/
# GET request should not have a request body. It's not recommended.
# https://pandadannikki.blogspot.com/2021/11/riss-http02.html
@user_router.get("/{uuid}")
def get_user(uuid: str, request: Request, claims: Dict[str, Any] = Depends(authenticate_user)):
    return hub_lambda_handler_wrapper_with_rtn_value(lambda: user.fetch_item(uuid, EMPTY_SK), request)


@user_router.put("/{uuid}")
def put_user(request_body: UserItem, request: Request, claims: Dict[str, Any] = Depends(authenticate_user)):
    return hub_lambda_handler_wrapper(lambda: user.update_item(request_body), request, request_body.dict())
