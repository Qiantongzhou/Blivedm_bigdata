# -*- coding: utf-8 -*-
import asyncio
import http.cookies
import random
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import requests

from typing import *

import aiohttp
import yarl

import blivedm
import blivedm.models.web as web_models

# 直播间ID的取值看直播间URL
TEST_ROOM_IDS = [
    30015166,1916500993
]

# 这里填一个已登录账号的cookie的SESSDATA字段的值。不填也可以连接，但是收到弹幕的用户名会打码，UID会变成0


SESSDATA= '62203e3b%2C1786353200%2Ceb162%2A22CjCJI8wYJNRajvvI-0KqRstjv_fWoMUyx0B7-kXnU_J4J9-Tn-D83ZsSBuqIl5YsZr4SVlpwd3BmS1B4ZEU5YVdvYUQtOVZQZU1oX3hTSUU3Z0toZnFvQTVRb21RcDAtX3BxcFNkQjJwZXd2UWJCRFYyUDNPdzRFU2huLW5PZXdHOVdEMVJMYm13IIEC'
bili_jct= '9dc53ae081a153f9b6ccf1afcf32cbb1'
DedeUserID= '154107998'
    # optional: add more if needed

session: Optional[aiohttp.ClientSession] = None
# Initialize Firebase

FIREBASE_DB_URL = "https://tuzigiftdb-default-rtdb.firebaseio.com/"  # Replace with your database URL
AUTH_TOKEN = ""  # Optional: Add Firebase authentication token if required
FIREBASE_DB_URL2 = "https://bilibilidata-default-rtdb.firebaseio.com/"
databridge="https://jsondatabridge.azurewebsites.net/Forward/Post"
async def main():

    init_session()
    try:
        #await run_single_client()
        await run_multi_clients()
    finally:
        await session.close()

async def create_session_with_cookies() -> aiohttp.ClientSession:
    cookie_jar = aiohttp.CookieJar()
    cookie_jar.update_cookies({
        'SESSDATA': SESSDATA,
        'bili_jct': bili_jct,
        'DedeUserID': DedeUserID
    }, response_url=yarl.URL('https://bilibili.com'))

    return aiohttp.ClientSession(cookie_jar=cookie_jar)
def init_session():
    cookies = http.cookies.SimpleCookie()
    cookies['SESSDATA'] = SESSDATA
    cookies['bili_jct'] = bili_jct
    cookies['DedeUserID'] = DedeUserID
    cookies['SESSDATA']['domain'] = 'bilibili.com'

    global session
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)


async def run_single_client():
    """
    演示监听一个直播间
    """
    room_id = random.choice(TEST_ROOM_IDS)
    session1 = await create_session_with_cookies()

    client = blivedm.BLiveClient(room_id, session=session1)
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
    def __init__(self):
        super().__init__()
        self._last_content: str | None = None     # last danmaku text we saw
        self._repeat_uids: set[int] = set()       # uids that repeated it
        self._ignore_current_content: bool = False
    def _send_to_firebase(self, path, data):
        url = f"{FIREBASE_DB_URL}{path}.json"
        response = self.forward_to_php(url,data)
        #response= requests.post(url, json=data)

        if response.status_code == 200:
            print(f"Data sent successfully to {path}: {response.text}")
        else:
            print(f"Failed to send data to {path}: {response.text}")
    def _send_to_firebase2(self, path, data):
        url = f"{FIREBASE_DB_URL2}{path}.json"
        #response= requests.post(url, json=data)

        response = self.forward_to_php(url,data)

        if response.status_code == 200:
            print(f"Data sent successfully to {path}: {response.text}")
        else:
            print(f"Failed to send data to {path}: {response.text}")

    def forward_to_php(self,firebase_url, data):
        # The URL of your PHP script
        php_url = 'http://qiantongzhou.huizhoutech.top/webfunctions/databridge.php'  # Change this to the actual path where your PHP script is hosted

        # Prepare the data to send to PHP script
        payload = {
            'FirebaseUrl': firebase_url,
            'Data': data
        }

        # Send the POST request to the PHP script
        response = requests.post(php_url, json=payload)

        # Print the response from the PHP script
        return response
    def _on_danmaku(
        self,
        client: blivedm.BLiveClient,
        message: web_models.DanmakuMessage,
    ):
        content = message.msg.strip()

        # -- 1. Detect repetition from different users ------------------ #
        if content == self._last_content:
            self._repeat_uids.add(message.uid)

            # Once THREE different senders have repeated this text,
            # we flip the ignore flag.
            if len(self._repeat_uids) >= 3:
                self._ignore_current_content = True
        else:
            # New text → reset all repetition tracking state
            self._last_content = content
            self._repeat_uids = {message.uid}
            self._ignore_current_content = False

        # -- 2. Ignore this text while we are in “poll spam” mode -------- #
        if self._ignore_current_content:
            return
        if "来至猫爪温馨提醒" in content or "送礼物喊开" in content:
            print("猫爪 bot not record")
            return

        # ---------------------------------------------------------------- #
        # 3. Normal handling (print + Firebase)                            #
        # ---------------------------------------------------------------- #
        print(f'[{client.room_id}] {message.uname}: {content}')

        beijing_tz = timezone(timedelta(hours=8))
        now        = datetime.now(beijing_tz)
        date_str   = now.strftime("%Y-%m-%d")
        time_str   = now.strftime("%H-%M-%S")

        data = {
            "uid"         : message.uid,
            "timestamp"   : message.timestamp,
            "uname"       : message.uname,
            "msg"         : content,
            "medal_name"  : message.medal_name,
            "medal_level" : message.medal_level,
            "admin"       : message.admin,
            "bubble"      : message.bubble,
        }
        path = f"{date_str}/{client.room_id}/user_message/{time_str}/{message.rnd}"
        self._send_to_firebase2(path, data)
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
        if '人气票' in message.gift_name and message.num ==1:
        # Include the current date in the path
            print(f'[{client.room_id}] 人气票discard')
        else:
            # Beijing timezone (UTC+8)
            beijing_tz = timezone(timedelta(hours=8))
            beijing_time = datetime.now(beijing_tz)
            date_str = beijing_time.strftime("%Y-%m-%d")
            self._send_to_firebase(f"{date_str}/{client.room_id}/gift_messages/{message.timestamp}", data)

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
        # Beijing timezone (UTC+8)
        beijing_tz = timezone(timedelta(hours=8))
        beijing_time = datetime.now(beijing_tz)
        date_str = beijing_time.strftime("%Y-%m-%d")
        self._send_to_firebase(f"{date_str}/{client.room_id}/guard_buy_messages/{message.start_time}", data)

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
        # Beijing timezone (UTC+8)
        beijing_tz = timezone(timedelta(hours=8))
        beijing_time = datetime.now(beijing_tz)
        date_str = beijing_time.strftime("%Y-%m-%d")
        self._send_to_firebase(f"{date_str}/{client.room_id}/super_chat_messages/{message.start_time}", data)
if __name__ == '__main__':
    asyncio.run(main())
