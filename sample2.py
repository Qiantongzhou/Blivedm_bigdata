# -*- coding: utf-8 -*-
import asyncio
import http.cookies
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
import yarl

import blivedm
import blivedm.models.web as web_models

TEST_ROOM_IDS = [30015166, 1916500993]

SESSDATA= '468755bf%2C1782816057%2C5f13e%2A12CjD15RD08M5ZIdh4ipikwr6xUN-jJuomJUkzpQJANYv064R2WyzVrsFw0l5i6A2HVEASVmxtSzE2dkxZN0YzWXgtNzBDN0s1ZU95M29WanFlVjVvVEZuUzYwM1BNVWExcFZTMVZsdDVINlpEUXVGSjZCTzU0Z1F1WVdDandRLW5JaGpNOHFHcDVnIIEC'
bili_jct= '9dc53ae081a153f9b6ccf1afcf32cbb1'
DedeUserID= '154107998'

FIREBASE_DB_URL = "https://tuzigiftdb-default-rtdb.firebaseio.com/"
FIREBASE_DB_URL2 = "https://bilibilidata-default-rtdb.firebaseio.com/"

session: Optional[aiohttp.ClientSession] = None


async def create_session_with_cookies() -> aiohttp.ClientSession:
    cookie_jar = aiohttp.CookieJar()
    cookie_jar.update_cookies({
        'SESSDATA': SESSDATA,
        'bili_jct': bili_jct,
        'DedeUserID': DedeUserID
    }, response_url=yarl.URL('https://bilibili.com'))
    return aiohttp.ClientSession(cookie_jar=cookie_jar)


class MyHandler(blivedm.BaseHandler):
    def __init__(self, http_session: aiohttp.ClientSession, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.http_session = http_session
        self.loop = loop

        # 反刷屏用
        self._last_content: str | None = None
        self._repeat_uids: set[int] = set()
        self._ignore_current_content: bool = False

        # 异步发送队列 + 后台worker
        self._q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=5000)
        self._worker_task = self.loop.create_task(self._worker())

    def enqueue_post(self, url: str, data: dict) -> None:
        """在同步回调里调用：把请求丢进队列，不阻塞弹幕线程。"""
        try:
            self._q.put_nowait((url, data))
        except asyncio.QueueFull:
            # 队列满就丢弃，避免内存爆；你也可以改成写日志或计数
            print("⚠️ Firebase queue full, drop one message")

    async def _post_json(self, url: str, data: dict) -> None:
        """真正异步POST（带一点点重试）。"""
        for attempt in range(3):
            try:
                async with self.http_session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if 200 <= resp.status < 300:
                        return
                    text = await resp.text()
                    print(f"❌ POST failed {resp.status}: {text}")
            except Exception as e:
                print(f"❌ POST exception: {e}")

            # 简单退避
            await asyncio.sleep(0.3 * (attempt + 1))

    async def _worker(self) -> None:
        """后台worker：从队列取数据异步发。"""
        while True:
            url, data = await self._q.get()
            try:
                await self._post_json(url, data)
            finally:
                self._q.task_done()

    async def aclose(self) -> None:
        """优雅关闭：等待队列发完，然后取消worker。"""
        try:
            await self._q.join()
        finally:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    # ---------- 你原来的逻辑：只把 requests.post 改成 enqueue_post ----------

    def _send_to_firebase(self, path: str, data: dict) -> None:
        url = f"{FIREBASE_DB_URL}{path}.json"
        self.enqueue_post(url, data)

    def _send_to_firebase2(self, path: str, data: dict) -> None:
        url = f"{FIREBASE_DB_URL2}{path}.json"
        self.enqueue_post(url, data)

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        content = message.msg.strip()

        # 1) 重复检测
        if content == self._last_content:
            self._repeat_uids.add(message.uid)
            if len(self._repeat_uids) >= 3:
                self._ignore_current_content = True
        else:
            self._last_content = content
            self._repeat_uids = {message.uid}
            self._ignore_current_content = False

        if self._ignore_current_content:
            return
        if "来至猫爪温馨提醒" in content or "送礼物喊开" in content:
            print("猫爪 bot not record")
            return

        print(f'[{client.room_id}] {message.uname}: {content}')

        beijing_tz = timezone(timedelta(hours=8))
        now = datetime.now(beijing_tz)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S")

        data = {
            "uid": message.uid,
            "timestamp": message.timestamp,
            "uname": message.uname,
            "msg": content,
            "medal_name": message.medal_name,
            "medal_level": message.medal_level,
            "admin": message.admin,
            "bubble": message.bubble,
        }
        path = f"{date_str}/{client.room_id}/user_message/{time_str}/{message.rnd}"
        self._send_to_firebase2(path, data)

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        print(f'[{client.room_id}] {message}')

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

        if '人气票' in message.gift_name and message.num == 1:
            print(f'[{client.room_id}] 人气票discard')
            return

        beijing_tz = timezone(timedelta(hours=8))
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")
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
        beijing_tz = timezone(timedelta(hours=8))
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")
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
        beijing_tz = timezone(timedelta(hours=8))
        date_str = datetime.now(beijing_tz).strftime("%Y-%m-%d")
        self._send_to_firebase(f"{date_str}/{client.room_id}/super_chat_messages/{message.start_time}", data)


async def run_multi_clients(handler: MyHandler):
    clients = [blivedm.BLiveClient(room_id, session=session) for room_id in TEST_ROOM_IDS]
    for client in clients:
        client.set_handler(handler)
        client.start()

    try:
        await asyncio.gather(*(client.join() for client in clients))
    finally:
        await asyncio.gather(*(client.stop_and_close() for client in clients))


async def main():
    global session
    session = await create_session_with_cookies()
    loop = asyncio.get_running_loop()
    handler = MyHandler(session, loop)

    try:
        await run_multi_clients(handler)
    finally:
        # 先把队列发完再关session
        await handler.aclose()
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())
