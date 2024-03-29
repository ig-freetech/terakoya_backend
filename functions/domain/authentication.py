import os
import sys
from typing import Any, Dict, Optional
from dataclasses import dataclass
from jose import jwt, jwk, JWTError
import requests
from fastapi import Request, Response, HTTPException, status

ROOT_DIR_PATH = os.path.dirname(os.path.dirname(__file__))
sys.path.append(ROOT_DIR_PATH)

from conf.env import AWS_DEFAULT_REGION, COGNITO_USER_POOL_ID, COGNITO_USER_POOL_CLIENT_ID
from utils.aws import cognito_client

if COGNITO_USER_POOL_CLIENT_ID == None or COGNITO_USER_POOL_ID == None:
    print("COGNITO_USER_POOL_CLIENT_ID or COGNITO_USER_POOL_ID is None")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal Server Error"
    )


def set_cookie_secured(fastApiResponse: Response, key: str, value: str):
    """Set access_token and refresh_token to cookie on Server-side"""
    # Include tokens in the response header as a cookie.
    # https://fastapi.tiangolo.com/advanced/response-cookies/
    # Set-Cookie is a HTTP response header to send a cookie from the server to the user agent.
    # https://developer.mozilla.org/ja/docs/Web/HTTP/Headers/Set-Cookie
    # Cookie enables to store the user's stateful information (ex: Login information) on the user's browser on HTTP protocol which is stateless.
    # https://qiita.com/mogulla3/items/189c99c87a0fc827520e
    fastApiResponse.set_cookie(
        key=key,
        value=value,
        # httponly is to prevent the cookie from being accessed by JavaScript like `document.cookie`.
        # https://qiita.com/kohekohe1221/items/80ff7a0bba6ac9128f56
        # https://developer.mozilla.org/ja/docs/Web/HTTP/Cookies#%E3%82%BB%E3%82%AD%E3%83%A5%E3%83%AA%E3%83%86%E3%82%A3
        httponly=True,
        # Cookie is send only via HTTPS by enabling secure, and not send via HTTP.
        # https://developer.mozilla.org/ja/docs/Web/HTTP/Cookies#cookie_%E3%81%B8%E3%81%AE%E3%82%A2%E3%82%AF%E3%82%BB%E3%82%B9%E5%88%B6%E9%99%90
        secure=True,
        # strict is to return the cookie only if the request originates from the same site not from a third party site (CSRF) and then prevent CSRF attacks.
        # https://laboradian.com/same-site-cookies/#2_SameSite_Same-site_Cookies
        # https://developer.mozilla.org/ja/docs/Web/HTTP/Cookies#samesite_%E5%B1%9E%E6%80%A7
        # "Samesite=none" is to allow the cookie to be sent over a cross-site request. (e.g. from the domain of API Gateway to the domain of Frontend's Vercel environment)
        # Secure must be set when SameSite is set to "none" to prevent the cookie from being sent over an unencrypted connection and avoid the risk of information leakage and cookie theft　by Man-in-the-middle attack.
        # https://developers.google.com/search/blog/2020/01/get-ready-for-new-samesitenone-secure?hl=ja
        # If SameSite is set to "lax" or "strict", client-side can't receive the cookie from the server-side.
        # Exclaimation mark is displayed at the header of set-cookie in a Network tab of the dev tool of your browser with the mesasge "This attempt to set a cookie via a Set-Cookie header was blocked because it had the "SameSite=Lax" ("SameSite=Strict") attribute but came from a cross-site response which was not the response to a top-level navigation."
        samesite="none",
        # domain is to specify the domain that can receive the cookie from the server.
        # https://zenn.dev/ymmt1089/articles/20220506_cookie_domain
        # https://developer.mozilla.org/ja/docs/Web/HTTP/Headers/Set-Cookie#%E5%B1%9E%E6%80%A7
        # domain="terakoyaweb.com",
        # path is to specify the path of the domain that can receive the cookie from the server.
        # "/" means that the cookie is sent to all pages under the domain.
        # https://developer.mozilla.org/ja/docs/Web/HTTP/Headers/Set-Cookie#%E5%B1%9E%E6%80%A7
        # path="/"
    )


def issue_new_access_token(refresh_token: str, fastApiResponse: Response):
    try:
        # Get new access token by using refresh token.
        response = cognito_client.initiate_auth(
            ClientId=COGNITO_USER_POOL_CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={
                'REFRESH_TOKEN': refresh_token
            }
        )
        auth_result = response['AuthenticationResult']
        set_cookie_secured(fastApiResponse, 'access_token', auth_result['AccessToken'])
        set_cookie_secured(fastApiResponse, 'refresh_token', auth_result['RefreshToken'])
    except cognito_client.exceptions.NotAuthorizedException:
        # Delete credentials from cookie if refresh token is expired.
        print("Invalid refresh token")
        delete_tokens_from_cookie(fastApiResponse)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="リフレッシュトークンが無効です。サインインし直して下さい。"
        )


def get_cognito_jwks() -> Dict[str, Any]:
    """
    Returns:
        Dict[str, Any]: { kid: jwk }
    """
    # JWT (JSON Web Token) is a string that encodes a JSON object in Base64 format and separated by a dot in the form of <header>.<payload>.<signature> (ex: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c).
    # JWT itself carrys the information of the user,　while normal token itself does not carry a meaningful information.
    # JSON key/value pair is called a "claim" in JWT. So, key is called "claim name" and value is called "claim value".
    # Claim names reserved in JWT are called "Registered Claim Names" and other claim names are called "Public Claim Names".
    # https://zenn.dev/mikakane/articles/tutorial_for_jwt
    # https://qiita.com/rs_/items/178f549c7a29c30fcbdb

    # The JSON object consists of three parts (header, payload, signature).
    # header: alg(Hash algorithm, ex: "RS256") and typ(Token type, ex: "JWT")
    # payload:
    # - sub(The identifier of the user to be authenticated, usually provided in the form of a URI, ex: "1234567890")
    # - iss(The identifier of Issuer of JWT, ex: "io.exact.sample.jwt")
    # - aud(The identifier of the recipient of JWT)
    # - exp(Expiration time of JWT, ex: 1670085336)
    # - iat(Issued at, ex: 1670081736)
    # signature: A string that is the result of Base64 encoding the header and payload concatenated with a period and encrypted with the secret key of the hash algorithm specified by "alg" in the header.
    # https://developer.mamezou-tech.com/blogs/2022/12/08/jwt-auth/#jwt%E3%81%A8%E3%81%AF

    # Normal token-based authentication requires a request to the server to verify the validity of the token.
    # But JWT can be verified by using the public key　that is provided by Issuer of JWT in the form of a JSON Web Key Set (JWKS).
    # JWK is provided in the form of a JSON object that contains the public keys.
    # JWK is usually published in URL that is provided by Issuer of JWT. For example, AWS publishes JWK in https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json.
    # Signature of JWT is used to verify the validity of JWT by using the public key of JWK with the algorithm specified by "alg" in the header.
    # https://zenn.dev/mikakane/articles/tutorial_for_jwt#%E7%BD%B2%E5%90%8D

    # Get public keys from Cognito User Pool.
    # https://docs.aws.amazon.com/ja_jp/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html#amazon-cognito-user-pools-using-tokens-manually-inspect
    url = f"https://cognito-idp.{AWS_DEFAULT_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    response = requests.get(url)
    # jwk.json(sample): { "keys": [ { "kid": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "alg": "RS256", "kty": "RSA", "e": "AQAB", "n": "1234567890", "use": "sig" } ] }
    jwk_list = response.json()['keys']
    # kid is uid of the public key (and JWK).
    return {jwk['kid']: jwk for jwk in jwk_list}


# tokenUrl is used for only OpenAPI document generation and  Swagger UI to get access token by using email and password.
# https://self-methods.com/fastapi-authentication/
# But FastAPI actually does not use tokenUrl to get access token. So, it doesn't affect the operation of the FastAPI application itself.
# OAuth2PasswordBearer works to get access token from the request header in actual FastAPI application.
# https://fastapi.tiangolo.com/ja/tutorial/security/first-steps/#fastapioauth2passwordbearer
# token is Authorization: Bearer {token(=access_token)} in HTTP request header.
# https://developer.mozilla.org/ja/docs/Web/HTTP/Headers/Authorization
# https://qiita.com/h_tyokinuhata/items/ab8e0337085997be04b1

def authenticate_user(fastApiResponse: Response, request: Request, access_token: Optional[str] = None):
    """Verify the signature of the JWT by using the public key of the Cognito User Pool."""
    path = f"{request.method}: {request.url.path}"
    print(f"================= {path} - authenticate_user =================")

    if access_token is None:
        print("Request cookies: " + str(request.cookies))
        access_token = request.cookies.get('access_token')
        if access_token is None:
            print("Access token is not set in Cookie.")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="アクセストークンがCookieに設定されていません。サインインし直して下さい。"
            )

    jwks = get_cognito_jwks()
    try:
        # Decode JWT with python-jose.
        # https://sal-blog.com/cognito%E3%81%AEjwt%E3%81%8B%E3%82%89%E3%83%A6%E3%83%BC%E3%82%B6%E6%83%85%E5%A0%B1%E3%82%92%E5%8F%96%E3%82%8A%E5%87%BA%E3%81%99python-jose/
        # https://docs.aws.amazon.com/ja_jp/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html#amazon-cognito-user-pools-using-tokens-manually-inspect
        header = jwt.get_unverified_header(access_token)
        print(f"header: {header}")
        alg = header["alg"]
        target_jwk = jwks[header["kid"]]
        if target_jwk is None:
            print(f"JWK not found.")
            delete_tokens_from_cookie(fastApiResponse)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="アクセストークンが無効です。サインインし直して下さい。"
            )
        # Convert JWK to public key object of python-jose.
        pub_key = jwk.construct(target_jwk)
        # Simultaneously verify the signature and decode the payload with the public key and algorithm.
        # PEM is a format for storing and transmitting cryptographic keys.
        # https://zenn.dev/osai/articles/3941f2d1de94f0
        return jwt.decode(access_token, pub_key.to_pem(), algorithms=[alg])
    except JWTError:
        print("Invalid token")
        delete_tokens_from_cookie(fastApiResponse)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            # detail is the error message that is displayed in the response body on the client side.
            # https://fastapi.tiangolo.com/ja/tutorial/handling-errors/
            detail='アクセストークンが無効です。サインインし直して下さい。',
            # WWW-Authenticate header is used to indicate the authentication method(s) and parameters applicable to the target resource.
            # https://developer.mozilla.org/ja/docs/Web/HTTP/Headers/WWW-Authenticate
            headers={"WWW-Authenticate": "Bearer"})  # Specify the authentication method as "Bearer".


def signup(email: str, password: str):
    try:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/sign_up.html
        response = cognito_client.sign_up(
            ClientId=COGNITO_USER_POOL_CLIENT_ID,
            Username=email,
            Password=password,
            # Specify user attributes as name-value pairs to be stored as the user profile in User Pool.
            UserAttributes=[
                {
                    'Name': 'email',
                    'Value': email
                },
            ],
            # Attributes in ClientMetadata are passed to the Lambda trigger (ex: PostConfirmation trigger etc.)
            # email is used in PostConfirmation trigger to add a record to User table in DynamoDB.
            ClientMetadata={
                'email': email,
            }
        )
        print(f"response: {response}")
        # response['UserSub'] is the UUID of the authenticated user.
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/sign_up.html
        return {"uuid": response['UserSub']}  # Return the UUID for testing.
    # If the specified email is already exists, UsernameExistsException is raised.
    # https://docs.aws.amazon.com/ja_jp/cognito/latest/developerguide/cognito-user-pool-managing-errors.html
    except cognito_client.exceptions.UsernameExistsException:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/admin_get_user.html
        response = cognito_client.admin_get_user(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=email
        )

        user_attrs = response['UserAttributes']
        print(f"user_attrs: {user_attrs}")
        for attr in user_attrs:
            if attr['Name'] == 'email_verified' and attr.get('Value') == 'true':
                print("Specified email is already exists and verified.")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="指定されたメールアドレスで登録されたユーザーは既に存在します。"
                )
            elif attr['Name'] == 'email_verified' and attr.get('Value') == 'false':
                # If email is not yet verified
                cognito_client.resend_confirmation_code(
                    ClientId=COGNITO_USER_POOL_CLIENT_ID,
                    Username=email
                )
                print("Specified email is already exists but not verified. So, sent a verification code again. Please check your email and verify it.")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="指定されたメールアドレスで登録されたユーザーは既に存在しますが、メールアドレス未認証で仮登録状態です。\nnpoterakoya2021@gmail.com から再度認証リンクが含まれたメールを送信しました。メールを確認して認証を完了させて下さい。\n※受信ボックスにメールが見つからない場合は、迷惑メールフォルダをご確認ください。"
                )
        # response['Username'] is the UUID of the authenticated user.
        return {"uuid": response['Username']}  # Return the UUID for testing.
    except cognito_client.exceptions.InvalidPasswordException:
        print("Password did not conform with policy: Password must have numeric characters")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="パスワードは半角英数字8文字以上で、アルファベットと数字をそれぞれ1文字以上含む必要があります。"
        )


# Using dataclass, __init__ method is automatically generated.
# https://yumarublog.com/python/dataclass/
# https://zenn.dev/karaage0703/articles/3508b20ece17d4
@dataclass
class SigninResponse:
    access_token: str
    refresh_token: str


def signin(email: str, password: str):
    try:
        # Get tokens by using email and password.
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/initiate_auth.html
        response = cognito_client.initiate_auth(
            ClientId=COGNITO_USER_POOL_CLIENT_ID,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': email,
                'PASSWORD': password
            }
        )
        # AuthenticationResult is a dictionary that contains the access token , ID token, and refresh token.
        auth_result = response['AuthenticationResult']
        access_token = auth_result['AccessToken']
        refresh_token = auth_result['RefreshToken']
        return SigninResponse(access_token, refresh_token)  # To fetch item from User table in DynamoDB
    except cognito_client.exceptions.NotAuthorizedException:
        print("Invalid email or password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="メールアドレスまたはパスワードが間違っています。"
        )
    except cognito_client.exceptions.UserNotConfirmedException:
        print("User is not confirmed. Please confirm your email.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="このユーザーは仮登録の状態です。\nメールアドレス認証が完了していません。\nnpoterakoya2021@gmail.com から送信された認証リンクが含まれたメールを確認して頂き認証を完了させてから再度サインインして下さい。\n※受信ボックスにメールが見つからない場合は、迷惑メールフォルダをご確認ください。"
        )


def delete_user(access_token: str, fastApiResponse: Response):
    try:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/delete_user.html
        cognito_client.delete_user(
            AccessToken=access_token
        )
    except cognito_client.exceptions.NotAuthorizedException:
        print("Invalid access token. User deletion failed.")
        delete_tokens_from_cookie(fastApiResponse)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="アクセストークンが無効なため、ユーザーの削除に失敗しました。"
        )


# Signout API endpoint is unnecessary because each client (ex: Web browsers, App) can delete the access token and refresh token in Cookie by itself when a user signs out.
# https://qiita.com/wasnot/items/949c6c4efe43ca0fa1cc
def delete_tokens_from_cookie(fastApiResponse: Response):
    fastApiResponse.delete_cookie('access_token')
    fastApiResponse.delete_cookie('refresh_token')
    # try:
    #     # Signs out users from all devices
    #     # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/global_sign_out.html
    #     cognito.global_sign_out(
    #         AccessToken=access_token
    #     )
    # except cognito.exceptions.NotAuthorizedException:
    #     print("Invalid access token")
    #     # Comment out to delete access token and refresh token from Cookie when access token is invalid.
    #     # raise Exception("Invalid access token")
    # finally:
    #     fastApiResponse.delete_cookie('access_token')
    #     fastApiResponse.delete_cookie('refresh_token')

def send_verification_code_for_forgot_password(email: str):
    try:
        # Confirmation code is expired in 24 hours.
        # https://docs.aws.amazon.com/cognito/latest/developerguide/how-to-recover-a-user-account.html
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cognito-idp/client/forgot_password.html
        cognito_client.forgot_password(
            ClientId=COGNITO_USER_POOL_CLIENT_ID,
            Username=email
        )
    except cognito_client.exceptions.UserNotFoundException:
        print("User doesn't exist whose email is specified.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたメールアドレスで登録されたユーザーは存在しません。"
        )
    
def reset_password(email: str, confirmation_code: str, new_password: str):
    try:
        cognito_client.confirm_forgot_password(
            ClientId=COGNITO_USER_POOL_CLIENT_ID,
            Username=email,
            ConfirmationCode=confirmation_code,
            Password=new_password
        )
    except cognito_client.exceptions.UserNotFoundException:
        print("User doesn't exist whose email is specified.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="指定されたメールアドレスで登録されたユーザーは存在しません。"
        )
    except cognito_client.exceptions.CodeMismatchException:
        print("Invalid confirmation code.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="認証コードが間違っています。"
        )
    except cognito_client.exceptions.ExpiredCodeException:
        print("Confirmation code is expired.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="認証コードの有効期限が切れています。"
        )
    except cognito_client.exceptions.InvalidPasswordException:
        print("Password did not conform with policy: Password must have numeric characters")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="パスワードは半角英数字8文字以上で、アルファベットと数字をそれぞれ1文字以上含む必要があります。"
        )