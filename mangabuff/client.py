import re
import json
import random
import logging
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from config import MANGABUFF_BASE

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 Safari/604.1",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edge/131.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/131.0.6778.260 Mobile Safari/537.36",
]


class MangabuffClient:
    def __init__(
        self,
        email: str = "",
        password: str = "",
        account_id: int = 0,
        proxy_url: str | None = None,
    ) -> None:
        self.email = email
        self.password = password
        self.account_id = account_id
        self.proxy_url = proxy_url
        self._csrf_token = ""
        self._is_auth = False
        self._user_id = 0
        self._ua = random.choice(USER_AGENTS)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(
                base_url=MANGABUFF_BASE,
                headers={
                    "User-Agent": self._ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
                },
                cookie_jar=aiohttp.CookieJar(),
                connector=connector,
            )
        return self._session

    async def _request(self, method: str, path: str, **kwargs) -> aiohttp.ClientResponse:
        session = await self._get_session()
        if self.proxy_url:
            kwargs.setdefault("proxy", self.proxy_url)
        return await session._request(method, path, **kwargs)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _extract_csrf(self, html: str) -> str:
        m = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
        return m.group(1) if m else ""

    async def login(self) -> bool:
        session = await self._get_session()
        try:
            kwargs_get = {}
            if self.proxy_url:
                kwargs_get["proxy"] = self.proxy_url
            async with session.get("/login", **kwargs_get) as resp:
                html = await resp.text()
                self._csrf_token = await self._extract_csrf(html)

            kwargs_post = {
                "data": {"email": self.email, "password": self.password},
                "headers": {
                    "X-CSRF-TOKEN": self._csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            }
            if self.proxy_url:
                kwargs_post["proxy"] = self.proxy_url
            async with session.post("/login", **kwargs_post) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and "error" in data:
                        logger.warning(f"Login failed for {self.email}: {data.get('error')}")
                        return False
                except json.JSONDecodeError:
                    pass
                self._is_auth = True
                return True
        except Exception as e:
            logger.error(f"Login exception for {self.email}: {e}")
            return False

    async def mark_chapter_read(self, manga_id: int, chapter_id: int) -> bool:
        session = await self._get_session()
        try:
            kwargs = {
                "params": {"r": "702"},
                "json": {"items": [{"manga_id": manga_id, "chapter_id": chapter_id}]},
                "headers": {
                    "X-CSRF-TOKEN": self._csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json",
                },
            }
            if self.proxy_url:
                kwargs["proxy"] = self.proxy_url
            async with session.post("/addHistory", **kwargs) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                    return isinstance(data, dict)
                except json.JSONDecodeError:
                    return False
        except Exception as e:
            logger.error(f"mark_chapter_read error: {e}")
            return False

    async def get_manga_info(self, slug: str) -> dict[str, Any]:
        session = await self._get_session()
        kwargs = {}
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        async with session.get(f"/manga/{slug}", **kwargs) as resp:
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            chapters = []
            seen = set()
            pat = re.compile(r"/manga/" + re.escape(slug) + r"/(\d+)/([\d.]+)$")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                m = pat.search(href)
                if m:
                    key = (int(m.group(1)), m.group(2))
                    if key not in seen:
                        seen.add(key)
                        url = href if href.startswith("/") else "/" + href.split("/", 3)[3]
                        chapters.append({"volume": int(m.group(1)), "chapter": m.group(2), "url": url})
            title_el = soup.select_one("h1")
            title = title_el.get_text(strip=True) if title_el else slug
            return {"slug": slug, "title": title, "chapters": chapters}

    async def get_chapter_page(self, slug: str, volume: int, chapter: str) -> dict | None:
        session = await self._get_session()
        try:
            kwargs = {}
            if self.proxy_url:
                kwargs["proxy"] = self.proxy_url
            async with session.get(f"/manga/{slug}/{volume}/{chapter}", **kwargs) as resp:
                html = await resp.text()
                csrf = await self._extract_csrf(html)
                if csrf:
                    self._csrf_token = csrf
                m = re.search(r'window\.current_chapter\s*=\s*({.*?});', html, re.DOTALL)
                if m:
                    try:
                        ch = json.loads(m.group(1))
                        return {
                            "manga_id": ch.get("id"),
                            "chapter_id": ch.get("chapter_id"),
                            "slug": ch.get("slug"),
                            "chapter": ch.get("chapter"),
                        }
                    except json.JSONDecodeError:
                        pass
                return None
        except Exception as e:
            logger.error(f"get_chapter_page error: {e}")
            return None

    async def post_comment(
        self,
        commentable_id: int,
        text: str,
        commentable_type: str = "mangaChapter",
        parent_id: int | None = None,
    ) -> bool:
        session = await self._get_session()
        try:
            data = {
                "text": text,
                "commentable_id": str(commentable_id),
                "commentable_type": commentable_type,
                "parent_id": parent_id or "",
            }
            kwargs = {
                "data": data,
                "headers": {
                    "X-CSRF-TOKEN": self._csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                },
            }
            if self.proxy_url:
                kwargs["proxy"] = self.proxy_url
            async with session.post("/comments", **kwargs) as resp:
                result = json.loads(await resp.text())
                return isinstance(result, dict) and "comment" in result
        except Exception as e:
            logger.error(f"post_comment error: {e}")
            return False

    @property
    def is_authenticated(self) -> bool:
        return self._is_auth
