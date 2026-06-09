import asyncio
import random
import re
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from config import config
from core.proxy_scraper import get_proxy_for_playwright


HUMAN_DELAY = lambda: random.uniform(1.0, 3.0)
SCROLL_DELAY = lambda: random.uniform(0.5, 1.5)


class MangaBuffClient:
    def __init__(self, email: str, password: str, proxy: Optional[str] = None):
        self.email = email
        self.password = password
        self.proxy = proxy
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def start(self):
        proxy_config = await get_proxy_for_playwright(self.proxy) if self.proxy else {}
        pw = await async_playwright().__aenter__()
        self._pw = pw
        self.browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--ignore-certificate-errors",
            ],
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            proxy=proxy_config if proxy_config else None,
            locale="ru-RU",
        )
        self.page = await self.context.new_page()
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)

    async def close(self):
        if self.context:
            await self.context.close()
            self.context = None
        if hasattr(self, "_pw"):
            await self._pw.stop()
        self.page = None

    async def human_delay(self, min_s=1.0, max_s=3.0):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _goto(self, url: str, **kwargs):
        if not self.page:
            raise RuntimeError("Page not initialized")
        await self.page.goto(url, timeout=30000, wait_until="domcontentloaded", **kwargs)
        await self.human_delay()

    async def login(self) -> bool:
        if not self.page:
            return False
        try:
            await self._goto(config.MANGA_BUFF_LOGIN)

            if await self.page.locator("button.login-button").count() == 0:
                return False

            await self.page.locator('input[name="email"]').first.fill(self.email)
            await self.human_delay()
            await self.page.locator('input[name="password"]').first.fill(self.password)
            await self.human_delay()

            async with self.page.expect_response(
                lambda r: r.status == 200 and r.request.method == "POST" and "/login" in r.url,
                timeout=15000,
            ) as resp_info:
                await self.page.locator("button.login-button").first.click()

            resp = await resp_info.value
            await self.human_delay()
            await self.page.wait_for_load_state("load")

            current = self.page.url
            if "/login" not in current.lower():
                return True

            return False
        except Exception as e:
            return False

    async def is_logged_in(self) -> bool:
        try:
            await self._goto(config.MANGA_BUFF_BASE)
            for _ in range(5):
                await self.human_delay(0.5, 1)
                logged_out = self.page.locator("button.login-button")
                if await logged_out.count() == 0:
                    return True
                await asyncio.sleep(1)
            return False
        except Exception:
            return False

    async def get_profile_stats(self) -> dict:
        result = {"diamonds": 0, "cards": 0, "level": 0, "exp": 0}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/balance")
            text = await self.page.text_content("body") or ""

            m = re.search(r'(\d[\d\s,]+)', text)
            if m:
                try:
                    result["diamonds"] = int(re.sub(r'[\s,]', '', m.group(1)))
                except ValueError:
                    pass

            card_count = self.page.locator(".wallet-panel__amount, [class*='amount']")
            if await card_count.count() > 0:
                txt = (await card_count.first.text_content() or "").strip()
                try:
                    result["diamonds"] = int(re.sub(r'\D', '', txt))
                except ValueError:
                    pass
        except Exception:
            pass
        return result

    async def collect_daily_reward(self) -> dict:
        result = {"success": False, "reward": None, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/balance")

            claim_btn = self.page.locator(".daily-rewards-btn, .wallet-panel__action--calendar")
            if await claim_btn.count() > 0 and await claim_btn.first.is_visible():
                await claim_btn.first.click()
                await self.human_delay()

            reward_items = self.page.locator(".daily-rewards-item")
            count = await reward_items.count()
            if count > 0:
                for i in range(count):
                    item = reward_items.nth(i)
                    cls = await item.get_attribute("class") or ""
                    if "daily-rewards-item--active" in cls or "active" in cls:
                        collect = item.locator("button, [class*='collect'], [class*='claim']")
                        if await collect.count() > 0:
                            await collect.first.click()
                            await self.human_delay()
                            result["success"] = True
                            result["reward"] = f"daily_reward_day_{i + 1}"
                            result["message"] = "Награда получена"
                            return result
                result["success"] = True
                result["message"] = "Все награды за сегодня собраны"
            else:
                result["success"] = True
                result["message"] = "Награды не найдены (возможно уже собрано)"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def click_mine(self, strategy: Optional[str] = None) -> dict:
        result = {"success": False, "message": ""}
        try:
            for attempt in range(3):
                await self._goto(f"{config.MANGA_BUFF_BASE}/mine")
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                current_url = self.page.url
                if "/mine" in current_url:
                    break
                await asyncio.sleep(2)

            tap_selectors = [".main-mine__game-tap", ".mine-tap", ".game-tap", "[class*='mine'] [class*='tap']"]
            tap_btn = None
            for sel in tap_selectors:
                el = self.page.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    tap_btn = el
                    break

            if tap_btn is not None:
                for _ in range(100):
                    await tap_btn.click()
                    await asyncio.sleep(random.uniform(0.1, 0.3))

            if strategy == "exchange":
                exchange = self.page.locator('button:has-text("Заменить")')
                if await exchange.count() > 0:
                    await exchange.first.click()
                    await self.human_delay()

            if strategy == "upgrade":
                upgrade = self.page.locator('button:has-text("Улучшить")')
                if await upgrade.count() > 0:
                    await upgrade.first.click()
                    await self.human_delay()

            result["success"] = True
            result["message"] = "Шахта обработана"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def do_quiz(self) -> dict:
        result = {"success": False, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/quiz")

            await self.page.wait_for_selector(
                ".quiz__answer-item.button",
                state="visible",
                timeout=10000,
            )

            if await self.page.locator(".quiz__answer-item.button").count() == 0:
                alt = self.page.locator(".quiz__answers .button, .quiz__answer-item")
                if await alt.count() == 0:
                    result["message"] = "Нет активных вопросов в квизе"
                    return result

            for _ in range(5):
                try:
                    answers = self.page.locator(".quiz__answer-item.button")
                    count = await answers.count()
                    if count == 0:
                        answers = self.page.locator(".quiz__answers .button, .quiz__answer-item")
                        count = await answers.count()
                    if count == 0:
                        break
                    idx = random.randint(0, count - 1)
                    await answers.nth(idx).click()
                    await self.human_delay(1, 2)
                    await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await asyncio.sleep(1)
                except Exception:
                    break

            result["success"] = True
            result["message"] = "Квиз пройден"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def post_auction_comments(self, count: int = 13) -> dict:
        result = {"success": False, "posted": 0, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/auctions")
            await self.page.wait_for_load_state("networkidle", timeout=15000)

            comments_el = self.page.locator(".comments").first
            if await comments_el.count() == 0:
                result["message"] = "Комментарии не найдены на странице аукционов"
                return result

            posted = 0
            for i in range(1, count + 1):
                text = str(i) * 4
                try:
                    ta = self.page.locator(".comments__send-form textarea").first
                    if await ta.count() == 0:
                        result["message"] = f"Поле ввода не найдено (комментарий {i})"
                        break
                    await ta.click()
                    await self.human_delay(0.5, 1)
                    await ta.fill(text)
                    await self.human_delay(0.3, 0.7)

                    submit = self.page.locator("button.comments__send-btn").first
                    if await submit.count() > 0:
                        await submit.evaluate("el => el.click()")
                        await asyncio.sleep(10)
                        posted += 1
                    else:
                        result["message"] = f"Кнопка отправки не найдена (комментарий {i})"
                        break
                except Exception as e:
                    result["message"] = f"Ошибка на комментарии {i}: {e}"
                    break

            result["success"] = posted > 0
            result["posted"] = posted
            result["message"] = f"Отправлено {posted}/{count} комментариев"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def _get_read_daily_progress(self) -> int:
        """Get current daily reading progress from /balance (0 if can't determine)."""
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/balance")
            await self.page.wait_for_load_state("networkidle", timeout=15000)

            counters = await self.page.evaluate('''() => {
                const body = document.body.textContent;
                const m = body.match(/(\\d+)\\s*\/\\s*75/);
                return m ? m[1] : null;
            }''')

            if counters is not None:
                return int(counters)
            return 0
        except Exception:
            return 0

    async def read_manga_chapters(self, chapter_prefix: str, start_from: int, target_total: int = 75) -> dict:
        result = {"success": False, "read": 0, "last_chapter": start_from - 1, "message": ""}
        try:
            initial_progress = await self._get_read_daily_progress()
            target = max(target_total, initial_progress + 1)

            read_count = 0
            last_read = start_from - 1
            chapter_num = start_from
            max_attempts = 200

            for _ in range(max_attempts):
                url = f"{chapter_prefix}{chapter_num}"
                ok = await self._read_single_chapter(url)
                if ok:
                    read_count += 1
                    last_read = chapter_num
                chapter_num += 1

                if read_count % 5 == 0 and read_count > 0:
                    current = await self._get_read_daily_progress()
                    if current >= target:
                        result["message"] = f"Цель {target} достигнута (прочитано {read_count} глав, до {last_read})"
                        break

                await self.human_delay(3, 7)

            if not result["message"]:
                current = await self._get_read_daily_progress()
                if current >= target:
                    result["message"] = f"Цель {target} достигнута (прочитано {read_count} глав, до {last_read})"
                else:
                    result["message"] = f"Прочитано {read_count} глав (до {last_read}), на балансе {current}/{target}"

            result["success"] = read_count > 0
            result["read"] = read_count
            result["last_chapter"] = last_read
        except Exception as e:
            result["message"] = str(e)
        return result

    async def _read_single_chapter(self, url: str) -> bool:
        try:
            await self._goto(url)
            await self.page.wait_for_load_state("networkidle", timeout=20000)

            images = self.page.locator(".reader img, .b-manga-reader img, img[src*='img2/chapters/']")
            img_count = await images.count()
            if img_count == 0:
                images = self.page.locator("img")
                img_count = await images.count()

            for _ in range(random.randint(3, 6)):
                await self.page.evaluate("window.scrollBy(0, {})".format(random.randint(400, 800)))
                await self.human_delay(0.8, 2)

            return True
        except Exception:
            return False

    async def _get_random_manga_url(self) -> Optional[str]:
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/catalog")
            hrefs = await self.page.evaluate('''() => {
                const links = document.querySelectorAll('a[href*="/manga/"], a[href*="/title/"]');
                return [...new Set([...links].map(l => l.href))];
            }''')
            if hrefs:
                return random.choice(hrefs)
        except Exception:
            pass
        return None

    async def post_comment(self, manga_url: Optional[str] = None) -> dict:
        result = {"success": False, "message": ""}
        try:
            if not manga_url:
                manga_url = await self._get_random_manga_url()
            if manga_url:
                await self._goto(manga_url)
            else:
                result["message"] = "Не удалось найти мангу для комментария"
                return result

            await self.page.wait_for_load_state("networkidle", timeout=15000)

            comments = self.page.locator(".comments")
            if await comments.count() == 0:
                result["message"] = "Комментарии не найдены"
                return result
            await comments.scroll_into_view_if_needed()
            await self.human_delay()

            ta = self.page.locator(".comments__send-form textarea").first
            if await ta.count() == 0:
                result["message"] = "Поле комментария не найдено"
                return result

            await ta.click()
            await self.human_delay(0.5, 1)

            texts = [
                "Классная глава!",
                "Спасибо за перевод!",
                "Жду следующую главу",
            ]
            await ta.fill(random.choice(texts))
            await self.human_delay(0.5, 1)

            submit = self.page.locator("button.comments__send-btn")
            if await submit.count() > 0:
                await submit.first.evaluate("el => el.click()")
                await self.human_delay()
                result["success"] = True
                result["message"] = "Комментарий оставлен"
            else:
                result["message"] = "Кнопка отправки не найдена"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def read_manga_chapter(self, chapter_url: str) -> bool:
        try:
            await self._goto(chapter_url)

            images = self.page.locator("img[src*='manga'], .reader-image, [class*='page'] img")
            image_count = await images.count()
            if image_count == 0:
                await asyncio.sleep(3)
                image_count = await images.count()

            for _ in range(random.randint(2, 5)):
                await self.page.evaluate("window.scrollBy(0, {})".format(random.randint(300, 700)))
                await self.human_delay(1, 3)

            next_btn = self.page.locator(
                'a[rel="next"], a:has-text("Далее"), [class*="next"] a, .reader-next'
            )
            if await next_btn.count() > 0 and await next_btn.first.is_visible():
                await next_btn.first.click()
                await self.human_delay(2, 4)
                await self.page.wait_for_load_state("load")
                for _ in range(random.randint(2, 4)):
                    await self.page.evaluate(
                        "window.scrollBy(0, {})".format(random.randint(200, 500))
                    )
                    await self.human_delay(1, 2)

            return True
        except Exception:
            return False

    async def read_random_manga(self, chapters_count: int = 5) -> dict:
        result = {"success": False, "read": 0, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/catalog")

            hrefs = await self.page.evaluate('''() => {
                const links = document.querySelectorAll('a[href*="/manga/"], a[href*="/title/"]');
                return [...new Set([...links].map(l => l.href))];
            }''')
            if not hrefs:
                result["message"] = "Манга не найдена"
                return result

            random.shuffle(hrefs)
            read_count = 0
            for url in hrefs[:chapters_count]:
                ok = await self.read_manga_chapter(url)
                if ok:
                    read_count += 1
                await self.human_delay(2, 5)

            result["success"] = read_count > 0
            result["read"] = read_count
            result["message"] = f"Прочитано {read_count} глав"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def collect_chat_diamond(self) -> dict:
        result = {"success": False, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/chat")

            get_coins = self.page.locator(".chat-arena__get-coins-btn")
            if await get_coins.count() > 0:
                await get_coins.first.click()
                await self.human_delay()
                result["success"] = True
                result["message"] = "Алмаз чата собран"
            else:
                result["message"] = "Кнопка сбора алмазов не найдена"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def watch_ad(self) -> bool:
        try:
            for attempt in range(3):
                await self._goto(f"{config.MANGA_BUFF_BASE}/balance")
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                current_url = self.page.url
                if "/balance" in current_url:
                    break
                await asyncio.sleep(2)

            ad_btn = self.page.locator(
                ".wallet-panel__action--ads, button:has-text('Реклама'), [class*='action--ads']"
            ).first
            if await ad_btn.count() == 0 or not await ad_btn.is_visible():
                return False

            await ad_btn.click()

            await asyncio.sleep(30)

            close_selectors = [
                "button:has-text('Закрыть')",
                ".modal-tenor__close",
                "[class*='close']",
                "[class*='modal'] .button:has-text('Закрыть')",
                ".button-link",
            ]
            for sel in close_selectors:
                btn = self.page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await self.human_delay()
                    break

            return True
        except Exception:
            return False

    async def get_event_balance(self) -> dict:
        result = {"success": False, "balance": 0, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/event/pack")
            el = self.page.locator(".js-event-balance").first
            if await el.count() > 0:
                text = (await el.text_content() or "0").strip()
                result["balance"] = int(re.sub(r"\D", "", text))
                result["success"] = True
                result["message"] = f"Баланс ивента: {result['balance']}"
            else:
                result["message"] = "Элемент баланса не найден"
        except Exception as e:
            result["message"] = str(e)
        return result

    async def _api_post(self, url: str) -> dict:
        result = {"success": False, "card": None, "balance": None, "raw": None, "message": ""}
        try:
            raw = await self.page.evaluate(
                """async (url) => {
                    try {
                        const meta = document.querySelector('meta[name="csrf-token"]');
                        const csrf = meta ? meta.getAttribute('content') : '';
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers: {
                                'X-Requested-With': 'XMLHttpRequest',
                                'Accept': 'application/json',
                                'X-CSRF-TOKEN': csrf,
                            },
                            credentials: 'same-origin',
                        });
                        return await resp.json();
                    } catch (e) {
                        return { error: e.message };
                    }
                }""",
                url,
            )
            result["raw"] = raw
            if raw.get("error"):
                result["message"] = raw["error"]
                return result
            result["success"] = True
            if "card" in raw:
                result["card"] = raw["card"]
            if "balance" in raw:
                result["balance"] = raw["balance"]
            result["message"] = raw.get("message", "ok")
        except Exception as e:
            result["message"] = str(e)
        return result

    async def do_event_free_card(self) -> dict:
        result = {"success": False, "card": None, "message": ""}
        try:
            await self._goto(f"{config.MANGA_BUFF_BASE}/event/pack")
            resp = await self._api_post("/event/freeCard")
            if resp["success"] and resp["card"]:
                result["success"] = True
                result["card"] = resp["card"]
                result["message"] = f"Бесплатная карта: {resp['card'].get('name', '?')}"
            elif resp["success"] and resp.get("message", "") == "":
                result["success"] = True
                result["message"] = "Бесплатная карта: уже получена"
            else:
                result["message"] = resp.get("message", "Не удалось получить карту")
        except Exception as e:
            result["message"] = str(e)
        return result

    async def do_event_open_pack(self) -> dict:
        result = {"success": False, "card": None, "message": ""}
        try:
            resp = await self._api_post("/event/pack")
            if resp["success"] and resp["card"]:
                result["success"] = True
                result["card"] = resp["card"]
                result["message"] = f"Пак открыт: {resp['card'].get('name', '?')}"
            else:
                result["message"] = resp.get("message", "Не удалось открыть пак")
        except Exception as e:
            result["message"] = str(e)
        return result

    async def do_event_open_donat(self) -> dict:
        result = {"success": False, "card": None, "message": ""}
        try:
            resp = await self._api_post("/event/packDonat")
            if resp["success"] and resp["card"]:
                result["success"] = True
                result["card"] = resp["card"]
                result["message"] = f"Донат-пак открыт: {resp['card'].get('name', '?')}"
            else:
                result["message"] = resp.get("message", "Не удалось открыть донат-пак")
        except Exception as e:
            result["message"] = str(e)
        return result
