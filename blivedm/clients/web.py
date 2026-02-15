# -*- coding: utf-8 -*-
import asyncio
import hashlib
import logging
import time
import urllib
from typing import *

import aiohttp
import requests
import yarl

from . import ws_base
from .. import utils

__all__ = (
    'BLiveClient',
)

logger = logging.getLogger('blivedm')

UID_INIT_URL = 'https://api.bilibili.com/x/web-interface/nav'
BUVID_INIT_URL = 'https://www.bilibili.com/'
ROOM_INIT_URL = 'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom'
DANMAKU_SERVER_CONF_URL = 'https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo'
DEFAULT_DANMAKU_SERVER_LIST = [
    {'host': 'broadcastlv.chat.bilibili.com', 'port': 2243, 'wss_port': 443, 'ws_port': 2244}
]


class BLiveClient(ws_base.WebSocketClientBase):
    """
    web端客户端

    :param room_id: URL中的房间ID，可以用短ID
    :param uid: B站用户ID，0表示未登录，None表示自动获取
    :param session: cookie、连接池
    :param heartbeat_interval: 发送心跳包的间隔时间（秒）
    """

    def __init__(
        self,
        room_id: int,
        *,
        uid: Optional[int] = None,
        session: Optional[aiohttp.ClientSession] = None,
        heartbeat_interval=30,
    ):
        super().__init__(session, heartbeat_interval)

        self._tmp_room_id = room_id
        """用来init_room的临时房间ID，可以用短ID"""
        self._uid = uid

        # 在调用init_room后初始化的字段
        self._room_owner_uid: Optional[int] = None
        """主播用户ID"""
        self._host_server_list: Optional[List[dict]] = None
        """
        弹幕服务器列表

        `[{host: "tx-bj4-live-comet-04.chat.bilibili.com", port: 2243, wss_port: 443, ws_port: 2244}, ...]`
        """
        self._host_server_token: Optional[str] = None
        """连接弹幕服务器用的token"""

    @property
    def tmp_room_id(self) -> int:
        """
        构造时传进来的room_id参数
        """
        return self._tmp_room_id

    @property
    def room_owner_uid(self) -> Optional[int]:
        """
        主播用户ID，调用init_room后初始化
        """
        return self._room_owner_uid

    @property
    def uid(self) -> Optional[int]:
        """
        当前登录的用户ID，未登录则为0，调用init_room后初始化
        """
        return self._uid

    async def init_room(self):
        """
        初始化连接房间需要的字段

        :return: True代表没有降级，如果需要降级后还可用，重载这个函数返回True
        """
        if self._uid is None:
            if not await self._init_uid():
                logger.warning('room=%d _init_uid() failed', self._tmp_room_id)
                self._uid = 0

        if self._get_buvid() == '':
            if not await self._init_buvid():
                logger.warning('room=%d _init_buvid() failed', self._tmp_room_id)

        res = True
        if not await self._init_room_id_and_owner():
            res = False
            # 失败了则降级
            self._room_id = self._tmp_room_id
            self._room_owner_uid = 0

        if not await self._init_host_server():
            res = False
            # 失败了则降级
            self._host_server_list = DEFAULT_DANMAKU_SERVER_LIST
            self._host_server_token = None
        return res

    async def _init_uid(self):
        cookies = self._session.cookie_jar.filter_cookies(yarl.URL(UID_INIT_URL))
        sessdata_cookie = cookies.get('SESSDATA', None)
        if sessdata_cookie is None or sessdata_cookie.value == '':
            # cookie都没有，不用请求了
            self._uid = 0
            return True

        try:
            async with self._session.get(
                UID_INIT_URL,
                headers={'User-Agent': utils.USER_AGENT},
            ) as res:
                if res.status != 200:
                    logger.warning('room=%d _init_uid() failed, status=%d, reason=%s', self._tmp_room_id,
                                   res.status, res.reason)
                    return False
                data = await res.json()
                if data['code'] != 0:
                    if data['code'] == -101:
                        # 未登录
                        self._uid = 0
                        return True
                    logger.warning('room=%d _init_uid() failed, message=%s', self._tmp_room_id,
                                   data['message'])
                    return False

                data = data['data']
                if not data['isLogin']:
                    # 未登录
                    self._uid = 0
                else:
                    self._uid = data['mid']
                return True
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room=%d _init_uid() failed:', self._tmp_room_id)
            return False

    def _get_buvid(self):
        cookies = self._session.cookie_jar.filter_cookies(yarl.URL(BUVID_INIT_URL))
        buvid_cookie = cookies.get('buvid3', None)
        if buvid_cookie is None:
            return ''
        return buvid_cookie.value

    async def _init_buvid(self):
        try:
            async with self._session.get(
                BUVID_INIT_URL,
                headers={'User-Agent': utils.USER_AGENT},
            ) as res:
                if res.status != 200:
                    logger.warning('room=%d _init_buvid() status error, status=%d, reason=%s',
                                   self._tmp_room_id, res.status, res.reason)
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room=%d _init_buvid() exception:', self._tmp_room_id)
        return self._get_buvid() != ''

    async def _init_room_id_and_owner(self):
        try:
            async with self._session.get(
                ROOM_INIT_URL,
                headers={'User-Agent': utils.USER_AGENT},
                params={
                    'room_id': self._tmp_room_id
                },
            ) as res:
                if res.status != 200:
                    logger.warning('room=%d _init_room_id_and_owner() failed, status=%d, reason=%s', self._tmp_room_id,
                                   res.status, res.reason)
                    return False
                data = await res.json()
                if data['code'] != 0:
                    logger.warning('room=%d _init_room_id_and_owner() failed, message=%s', self._tmp_room_id,
                                   data['message'])
                    return False
                if not self._parse_room_init(data['data']):
                    return False
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room=%d _init_room_id_and_owner() failed:', self._tmp_room_id)
            return False
        return True

    def _parse_room_init(self, data):
        room_info = data['room_info']
        self._room_id = room_info['room_id']
        self._room_owner_uid = room_info['uid']
        return True
    def initnet(self):
        UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

        self.sess = requests.Session()
        self.sess.headers.update({
            "User-Agent": UA,
            "Referer": f"https://live.bilibili.com/{self._room_id}",
            "Origin": "https://live.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })
        self.sess.cookies.update({
            "SESSDATA": "285001da%2C1763687156%2C01e7d%2A52CjBASyqqlqZITZbpuLnIBCcXDRjcX0rEZu2HjI8sGtIJDtAtn9V5xhyxKyJWl4JlARkSVmNBNDhLdmVndzRYVUVVMk9RdURTTmdmMGRfX2VvM0xHbUd3SF94c3lYRHd2N1RINHJJV0pKWDNlbTU3UnlCeVlfcHZadHlrbkJMNlNtTFdzWng1bktBIIEC",
            "buvid4": "D4B96D9A-26B5-1B88-0DEA-51223B5ACB6380933-024120719-bFB3sYmyJ%2B9x0yWCD1L9Aw%3D%3D",
            "b_nut": "1733601279",
            "bili_jct": "1c6606206e98f82710d0bf9658d650f8",
            "DedeUserID": "154107998",
            "DedeUserID__ckMd5": "702776d4425d894a",
            "bili_ticket": "eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NDg0OTAxNDAsImlhdCI6MTc0ODIzMDg4MCwicGx0IjotMX0.WaWBz6Ezu2h0i6QLih00eOBcGWqyW-bLupd1a-z_zjQ",
            "fingerprint": "2a33c1575c214701539e933c95b983a4",
        })
    def get_img_sub_key(self):
        self.initnet()
        """每天只用请求一次 nav 接口即可"""
        nav = self.sess.get("https://api.bilibili.com/x/web-interface/nav",
                            headers={"Referer": "https://www.bilibili.com/"}).json()
        img_key = nav["data"]["wbi_img"]["img_url"].split('/')[-1].split('.')[0]
        sub_key = nav["data"]["wbi_img"]["sub_url"].split('/')[-1].split('.')[0]
        return img_key, sub_key

    def wbi_sign(self,params: dict, img_key: str, sub_key: str):
        """官方 W-BI 混淆表"""
        MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
                     27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
                     37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
                     22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]
        mixin_key = ''.join((img_key + sub_key)[i] for i in MIXIN_TAB)[:32]

        params["wts"] = int(time.time())
        query = urllib.parse.urlencode(sorted(params.items()))
        params["w_rid"] = hashlib.md5(f"{query}{mixin_key}".encode()).hexdigest()
        return params
    async def _init_host_server(self):
        try:
            img_key, sub_key = self.get_img_sub_key()
            signed = self.wbi_sign(
                {"id": self._room_id, "type": 0, "web_location": "444.8"},
                img_key, sub_key)
            async with self._session.get(
                DANMAKU_SERVER_CONF_URL,
                headers={'User-Agent': utils.USER_AGENT},
                params=signed,
            ) as res:
                if res.status != 200:
                    logger.warning('room=%d _init_host_server() failed, status=%d, reason=%s', self._room_id,
                                   res.status, res.reason)
                    return False
                data = await res.json()
                if data['code'] != 0:
                    logger.warning('room=%d _init_host_server() failed, message=%s', self._room_id, data['message'])
                    return False
                if not self._parse_danmaku_server_conf(data['data']):
                    return False
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
            logger.exception('room=%d _init_host_server() failed:', self._room_id)
            return False
        return True

    def _parse_danmaku_server_conf(self, data):
        self._host_server_list = data['host_list']
        self._host_server_token = data['token']
        if not self._host_server_list:
            logger.warning('room=%d _parse_danmaku_server_conf() failed: host_server_list is empty', self._room_id)
            return False
        return True

    async def _on_before_ws_connect(self, retry_count):
        """
        在每次建立连接之前调用，可以用来初始化房间
        """
        # 重连次数太多则重新init_room，保险
        reinit_period = max(3, len(self._host_server_list or ()))
        if retry_count > 0 and retry_count % reinit_period == 0:
            self._need_init_room = True
        await super()._on_before_ws_connect(retry_count)

    def _get_ws_url(self, retry_count) -> str:
        """
        返回WebSocket连接的URL，可以在这里做故障转移和负载均衡
        """
        host_server = self._host_server_list[retry_count % len(self._host_server_list)]
        return f"wss://{host_server['host']}:{host_server['wss_port']}/sub"

    async def _send_auth(self):
        """
        发送认证包
        """
        auth_params = {
            'uid': self._uid,
            'roomid': self._room_id,
            'protover': 3,
            'platform': 'web',
            'type': 2,
            'buvid': self._get_buvid(),
        }
        if self._host_server_token is not None:
            auth_params['key'] = self._host_server_token
        await self._websocket.send_bytes(self._make_packet(auth_params, ws_base.Operation.AUTH))
