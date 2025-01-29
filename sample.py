# -*- coding: utf-8 -*-
import asyncio
import http.cookies
import random
from datetime import datetime

import requests

from typing import *

import aiohttp

import blivedm
import blivedm.models.web as web_models

# 直播间ID的取值看直播间URL
TEST_ROOM_IDS = [
    30015166,1916500993
]

# 这里填一个已登录账号的cookie的SESSDATA字段的值。不填也可以连接，但是收到弹幕的用户名会打码，UID会变成0
SESSDATA = '08c12224%2C1749526310%2C8d778%2Ac2CjAtTPswAtRoKo_E8L5oIdnZ9Lwl_pYqei91QBA7Ezi2clNqC0AnptOZ4kNPXqL9ZvUSVnF1SGk0VkFUN2o5bG1rUTN1eHJrVjRjTGdDMnZGWUZERTZKMUVFRE44NjAtb1AtSnNySjlPVkJITUlRSWVpblh1WXdPMV8tZ1R5VE1BdHF1U1RRQ1ZRIIEC'

session: Optional[aiohttp.ClientSession] = None
# Initialize Firebase

FIREBASE_DB_URL = "https://tuzigiftdb-default-rtdb.firebaseio.com/"  # Replace with your database URL
AUTH_TOKEN = ""  # Optional: Add Firebase authentication token if required


async def main():
    init_session()
    try:
        #await run_single_client()
        await run_multi_clients()
    finally:
        await session.close()


def init_session():
    cookies = http.cookies.SimpleCookie()
    cookies['SESSDATA'] = SESSDATA
    cookies['SESSDATA']['domain'] = 'bilibili.com'

    global session
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)


async def run_single_client():
    """
    演示监听一个直播间
    """
    room_id = random.choice(TEST_ROOM_IDS)
    client = blivedm.BLiveClient(room_id, session=session)
    handler = MyHandler()
    client.set_handler(handler)

    client.start()
    try:
        # 演示5秒后停止
        await asyncio.sleep(5)
        client.stop()

        await client.join()
    finally:
        await client.stop_and_close()


async def run_multi_clients():
    """
    演示同时监听多个直播间
    """
    clients = [blivedm.BLiveClient(room_id, session=session) for room_id in TEST_ROOM_IDS]
    handler = MyHandler()
    for client in clients:
        client.set_handler(handler)
        client.start()

    try:
        await asyncio.gather(*(
            client.join() for client in clients
        ))
    finally:
        await asyncio.gather(*(
            client.stop_and_close() for client in clients
        ))


class MyHandler(blivedm.BaseHandler):
    def _send_to_firebase(self, path, data):
        """Send the data to Firebase using REST API."""
        url = f"{FIREBASE_DB_URL}{path}.json"
        params = {"auth": AUTH_TOKEN} if AUTH_TOKEN else {}
        response = requests.post(url, params=params, json=data)
        if response.status_code == 200:
            print(f"Data sent successfully to {path}")
        else:
            print(f"Failed to send data to {path}: {response.text}")

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        print(f'[{client.room_id}] {message}')
        # Prepare the gift message data as a dictionary
        data = {
            "gift_name": message.gift_name,
            "num": message.num,
            "uname": message.uname,
            "face": message.face,
            "guard_level": message.guard_level,
            "uid": message.uid,
            "timestamp": message.timestamp,
            "gift_id": message.gift_id,
            "gift_type": message.gift_type,
            "action": message.action,
            "price": message.price,
            "rnd": message.rnd,
            "coin_type": message.coin_type,
            "total_coin": message.total_coin,
            "tid": message.tid
        }
        # Include the current date in the path
        date = datetime.now().strftime("%Y-%m-%d")
        self._send_to_firebase(f"{date}/{client.room_id}/gift_messages/{message.timestamp}", data)

    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        print(f'[{client.room_id}] {message}')
        data = {
            "uid": message.uid,
            "username": message.username,
            "guard_level": message.guard_level,
            "num": message.num,
            "price": message.price,
            "gift_id": message.gift_id,
            "gift_name": message.gift_name,
            "start_time": message.start_time,
            "end_time": message.end_time
        }
        # Include the current date in the path
        date = datetime.now().strftime("%Y-%m-%d")
        self._send_to_firebase(f"{date}/{client.room_id}/guard_buy_messages/{message.start_time}", data)

    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        print(f'[{client.room_id}] {message}')
        data = {
            "price": message.price,
            "message": message.message,
            "message_trans": message.message_trans,
            "start_time": message.start_time,
            "end_time": message.end_time,
            "time": message.time,
            "id": message.id,
            "gift_id": message.gift_id,
            "gift_name": message.gift_name,
            "uid": message.uid,
            "uname": message.uname,
            "face": message.face,
            "guard_level": message.guard_level,
            "user_level": message.user_level,
            "background_bottom_color": message.background_bottom_color,
            "background_color": message.background_color,
            "background_icon": message.background_icon,
            "background_image": message.background_image,
            "background_price_color": message.background_price_color
        }
        # Include the current date in the path
        date = datetime.now().strftime("%Y-%m-%d")
        self._send_to_firebase(f"{date}/{client.room_id}/super_chat_messages/{message.start_time}", data)
if __name__ == '__main__':
    asyncio.run(main())
