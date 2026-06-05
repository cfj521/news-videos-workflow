import time as _time
from datetime import date, datetime, timedelta, timezone

import httpx

from app.logging import get_logger
from app.providers.base import CollectorProvider, RawArticleData

log = get_logger("collector.aihot")

API = "https://aihot.virxact.com/api/public"

TIME_RANGE_HOURS = {"1d": 24, "3d": 72, "7d": 168, "15d": 360, "1m": 720}

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsVid/1.0)", "Accept": "application/json"}


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


class AIHotCollector(CollectorProvider):
    async def collect(self, source_config: dict, time_range: str, max_items: int = 30) -> list[RawArticleData]:
        method = source_config.get("method", "items")
        if method == "daily":
            return await self._collect_daily(source_config)
        if method == "weekly":
            return await self._collect_weekly(source_config)
        return await self._collect_items(source_config, time_range, max_items)

    async def _collect_items(self, source_config: dict, time_range: str, max_items: int) -> list[RawArticleData]:
        source_name = source_config.get("name", "AI Hot")
        category = source_config.get("category", "")
        hours = TIME_RANGE_HOURS.get(time_range, 168)
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params: dict = {"mode": "selected", "since": since, "take": max_items}
        if category:
            params["category"] = category

        t0 = _time.time()
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/items", params=params)
            resp.raise_for_status()
        data = resp.json()

        articles: list[RawArticleData] = []
        for item in data.get("items", [])[:max_items]:
            articles.append(RawArticleData(
                title=item.get("title", ""),
                content=item.get("summary", ""),
                source_url=item.get("url", ""),
                source_name=item.get("source", source_name),
                published_at=_parse_dt(item.get("publishedAt")),
                category=item.get("category", "ai"),
                summary=item.get("summary", ""),
                aggregator_url="https://aihot.virxact.com",
                metadata={"source_group": "aihot", "aihot_method": "items"},
            ))
        log.info("Collected %d items from AI Hot in %.1fs", len(articles), _time.time() - t0)
        return articles

    async def _collect_daily(self, source_config: dict) -> list[RawArticleData]:
        t0 = _time.time()
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/daily")
            if resp.status_code == 404:
                log.warning("AI Hot daily report not available (404)")
                return []
            resp.raise_for_status()
        report = resp.json()

        date = report.get("date", "")
        # 日报前端页（跳转/展示用），形如 https://aihot.virxact.com/daily/2026-06-04
        daily_url = f"https://aihot.virxact.com/daily/{date}" if date else "https://aihot.virxact.com"
        lead = report.get("lead") or {}
        lead_title = lead.get("title") or f"今日 AI 日报 {date}"
        lead_para = lead.get("leadParagraph", "")

        lines: list[str] = [lead_para, ""]
        for section in report.get("sections", []):
            lines.append(f"【{section.get('label', '')}】")
            for it in section.get("items", []):
                lines.append(f"「{it.get('title', '')}」{it.get('summary', '')}")
            lines.append("")
        flashes = report.get("flashes", [])
        if flashes:
            lines.append("【快讯】")
            for f in flashes:
                lines.append(f"· {f.get('title', '')}（{f.get('sourceName', '')}）")
        content = "\n".join(lines).strip()

        article = RawArticleData(
            title=lead_title,
            content=content,
            source_url=daily_url,
            source_name="AI HOT 日报",
            category="ai",
            summary=lead_para,
            aggregator_url=daily_url,
            metadata={"source_group": "aihot", "aihot_method": "daily", "report_date": date,
                      "daily_sections": report.get("sections", [])},
        )
        log.info("Collected AI Hot daily (%s, %d chars) in %.1fs", date, len(content), _time.time() - t0)
        return [article]

    async def _collect_weekly(self, source_config: dict) -> list[RawArticleData]:
        """聚合上一个完整自然周（周一~周日）的每日日报，扁平汇总条目供 Stage1 提炼。"""
        t0 = _time.time()
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        week_start = this_monday - timedelta(days=7)
        week_end = this_monday - timedelta(days=1)

        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            resp = await client.get(f"{API}/dailies")
            if resp.status_code == 404:
                log.warning("AI Hot dailies archive not available (404)")
                return []
            resp.raise_for_status()
            archive = resp.json()

            dates: list[str] = []
            for it in archive.get("items", []):
                raw = it.get("date", "")
                try:
                    d = date.fromisoformat(raw)
                except ValueError:
                    continue
                if week_start <= d <= week_end:
                    dates.append(raw)
            dates.sort()

            weekly_items: list[dict] = []
            content_lines: list[str] = []
            first_lead = ""
            for d in dates:
                r = await client.get(f"{API}/daily/{d}")
                if r.status_code == 404:
                    log.warning("AI Hot daily %s missing (404), skip", d)
                    continue
                try:
                    r.raise_for_status()
                except Exception:
                    log.warning("AI Hot daily %s failed, skip", d)
                    continue
                report = r.json()
                lead = report.get("lead") or {}
                lead_para = lead.get("leadParagraph", "")
                if lead_para and not first_lead:
                    first_lead = lead_para
                content_lines.append(f"# {d} {lead.get('title', '')}")
                content_lines.append(lead_para)
                for section in report.get("sections", []):
                    label = section.get("label", "")
                    content_lines.append(f"【{label}】")
                    for sit in section.get("items", []):
                        title = sit.get("title", "")
                        summary = sit.get("summary", "")
                        content_lines.append(f"「{title}」{summary}")
                        weekly_items.append({"title": title, "summary": summary,
                                             "category": label, "date": d})
                for f in report.get("flashes", []):
                    weekly_items.append({"title": f.get("title", ""), "summary": "",
                                         "category": "快讯", "date": d})
                content_lines.append("")

        if not weekly_items:
            log.warning("AI Hot weekly: no dailies in %s~%s", week_start, week_end)
            return []

        content = "\n".join(content_lines).strip()
        article = RawArticleData(
            title=f"本周 AI 热点回顾 {week_start}~{week_end}",
            content=content,
            source_url="https://aihot.virxact.com",
            source_name="AI HOT 周报",
            category="ai",
            summary=first_lead,
            aggregator_url="https://aihot.virxact.com",
            metadata={"source_group": "aihot", "aihot_method": "weekly",
                      "week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
                      "weekly_items": weekly_items},
        )
        log.info("Collected AI Hot weekly (%s~%s, %d items) in %.1fs",
                 week_start, week_end, len(weekly_items), _time.time() - t0)
        return [article]
