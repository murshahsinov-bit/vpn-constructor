import asyncio
import json
import logging
import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

TARGET_SERVER = "https://api.ipify.org"

async def relay_handler(event: dict, context) -> dict:
    """
    Обработчик Cloud Function для HTTP/WebSocket relay-запросов.
    Транслирует входящий запрос на целевой сервер и возвращает ответ.
    """
    try:
        method = event.get('httpMethod', 'GET')
        headers = event.get('headers', {})
        body = event.get('body', '')
        if event.get('isBase64Encoded', False):
            import base64
            body = base64.b64decode(body)

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method=method,
                url=TARGET_SERVER,
                headers={k: v for k, v in headers.items() if k.lower() not in ['host', 'content-length']},
                data=body,
                allow_redirects=True
            ) as resp:
                resp_body = await resp.read()
                resp_headers = dict(resp.headers)
                
                return {
                    'statusCode': resp.status,
                    'headers': {'Content-Type': resp.headers.get('Content-Type', 'text/plain')},
                    'body': resp_body.decode('utf-8', errors='replace'),
                    'isBase64Encoded': False
                }
    except Exception as e:
        logger.error(f"Ошибка relay: {e}")
        return {
            'statusCode': 502,
            'body': json.dumps({'error': 'Relay connection failed', 'details': str(e)}),
            'headers': {'Content-Type': 'application/json'}
        }