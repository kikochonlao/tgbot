import asyncio
import random
from typing import Optional

import httpx
from fake_useragent import UserAgent

from config import config


ua = UserAgent()


async def check_proxy(proxy: str) -> bool:
    proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
    try:
        async with httpx.AsyncClient(
            proxies=proxy_url,
            timeout=config.PROXY_CHECK_TIMEOUT,
        ) as client:
            resp = await client.get("https://httpbin.org/ip")
            return resp.status_code == 200
    except Exception:
        return False


async def check_proxy_for_site(proxy: str, target: str = "https://mangabuff.ru") -> bool:
    proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
    try:
        async with httpx.AsyncClient(
            proxies=proxy_url,
            timeout=config.PROXY_CHECK_TIMEOUT,
            headers={"User-Agent": ua.random},
            follow_redirects=True,
        ) as client:
            resp = await client.get(target)
            if resp.status_code == 200:
                text = resp.text.lower()
                if any(w in text for w in ["mangabuff", "manhuabuff", "inkstory"]):
                    return True
            return False
    except Exception:
        return False


async def scrape_free_proxies() -> list[str]:
    proxies = set()
    async with httpx.AsyncClient(timeout=15) as client:
        for url in config.PROXY_SOURCES:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    for line in resp.text.strip().splitlines():
                        line = line.strip()
                        if line and ":" in line:
                            proxies.add(line.strip())
            except Exception:
                continue
    return list(proxies)


async def scrape_proxies_from_webshare() -> list[tuple[str, str]]:
    results = []
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    ]
    async with httpx.AsyncClient(timeout=20) as client:
        for url in urls:
            ptype = "socks5" if "socks5" in url else "socks4" if "socks4" in url else "http"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    for line in resp.text.strip().splitlines():
                        line = line.strip()
                        if line and ":" in line:
                            results.append((line, ptype))
            except Exception:
                continue
    return results


async def get_proxy_for_playwright(proxy_string: str) -> dict:
    if not proxy_string:
        return {}
    if proxy_string.startswith("http://") or proxy_string.startswith("https://"):
        parts = proxy_string.replace("http://", "").replace("https://", "").split("@")
        if len(parts) == 2:
            creds, host_port = parts
            user, pwd = creds.split(":", 1)
            host, port = host_port.split(":", 1)
            return {
                "server": f"http://{host}:{port}",
                "username": user,
                "password": pwd,
            }
        else:
            return {"server": proxy_string}
    elif proxy_string.startswith("socks5://") or proxy_string.startswith("socks4://"):
        return {"server": proxy_string}
    else:
        return {"server": f"http://{proxy_string}"}
