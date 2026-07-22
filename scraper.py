import json
import os
import re
import time
import logging
import urllib.request
import urllib.parse
import ssl
from datetime import datetime

logger = logging.getLogger(__name__)

INDIA_LOCATIONS = [
    "india", "pune", "bangalore", "bengaluru", "gurugram", "gurgaon",
    "vadodara", "hyderabad", "noida", "chennai", "mumbai", "delhi",
    "nagpur", "coimbatore", "kochi", "jaipur", "ahmedabad", "lucknow",
    "indore", "bhopal", "mysore", "mangalore", "visakhapatnam",
    "vijayawada", "tiruchirappalli", "madurai", "thiruvananthapuram", "kolkata",
]

TITLE_ALLOW = [
    r"software\s+engineer",
    r"software\s+developer",
    r"\bsde\b",
    r"developer\s+associate",
    r"graduate\s+software",
]

TITLE_EXCLUDE = [
    r"\bsenior\b", r"\bsr[\.\s]", r"\blead\b", r"\bprincipal\b",
    r"\bstaff\b", r"\barchitect\b", r"\bmanager\b", r"\bdirector\b",
    r"\bvice\s+president\b", r"\bvp\b", r"\bintern\b", r"\binternship\b",
    r"\bhead\b",
    r"\bII\b", r"\bIII\b", r"\bIV\b", r"\bV\b",
    r"[\s\-]2\b", r"[\s\-]3\b", r"[\s\-]4\b", r"[\s\-]5\b",
]


class JobScraper:
    def __init__(self, sites_config):
        self.sites = sites_config.get("sites", [])
        self.search_queries = sites_config.get("search_queries", ["Software Engineer"])
        self.title_allow = sites_config.get("title_allow", TITLE_ALLOW)
        self.title_exclude = sites_config.get("title_exclude", TITLE_EXCLUDE)
        self.india_locations = sites_config.get("india_locations", INDIA_LOCATIONS)
        self.ctx = ssl.create_default_context()
        self.last_run = None
        self.last_stats = {}

    def fetch_jobs(self, api_url, offset=0, limit=20, search_text="Software Engineer"):
        payload = json.dumps({
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": search_text
        }).encode("utf-8")

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, context=self.ctx, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch_all_jobs_for_site(self, site):
        api_url = f"https://{site['slug']}.{site['subdomain']}.myworkdayjobs.com/wday/cxs/{site['slug']}/{site['site_path']}/jobs"
        career_url = site.get("career_url", f"https://{site['slug']}.{site['subdomain']}.myworkdayjobs.com/en-US/{site['site_path']}")
        api_base = f"https://{site['slug']}.{site['subdomain']}.myworkdayjobs.com/en-US/{site['site_path']}"

        all_jobs = []
        seen_ids = set()

        for query in self.search_queries:
            offset = 0
            limit = 20
            no_new_streak = 0
            while no_new_streak < 2:
                try:
                    data = self.fetch_jobs(api_url, offset=offset, limit=limit, search_text=query)
                    jobs = data.get("jobPostings", [])
                    if not jobs:
                        break
                    new_count = 0
                    for j in jobs:
                        jid = j.get("externalPath", j.get("title", ""))
                        if jid not in seen_ids:
                            seen_ids.add(jid)
                            j["_site_name"] = site["name"]
                            j["_career_url"] = career_url
                            j["_api_base"] = api_base
                            all_jobs.append(j)
                            new_count += 1
                    if new_count == 0:
                        no_new_streak += 1
                    else:
                        no_new_streak = 0
                    offset += limit
                    time.sleep(0.2)
                except Exception as e:
                    logger.error(f"Error fetching {site['name']} offset={offset} query='{query}': {e}")
                    break
            time.sleep(0.3)

        return all_jobs

    def is_india_job(self, job):
        loc = (job.get("locationsText", "") or "").lower()
        return any(ind in loc for ind in self.india_locations)

    def matches_title(self, title):
        for pat in self.title_exclude:
            if re.search(pat, title, re.IGNORECASE):
                return False
        for pat in self.title_allow:
            if re.search(pat, title, re.IGNORECASE):
                return True
        return False

    def filter_jobs(self, jobs):
        seen = set()
        result = []
        for job in jobs:
            title = job.get("title", "")
            ext_path = job.get("externalPath", "")
            job_id = ext_path if ext_path else title

            if job_id in seen:
                continue
            seen.add(job_id)

            if not self.is_india_job(job):
                continue
            if not self.matches_title(title):
                continue

            api_base = job.get("_api_base", "")
            result.append({
                "id": f"{job['_site_name']}|{job_id}",
                "title": title,
                "location": job.get("locationsText", "N/A"),
                "posted": job.get("postedOn", "N/A"),
                "company": job["_site_name"],
                "url": api_base + ext_path if ext_path else job.get("_career_url", ""),
                "bullet_fields": job.get("bulletFields", []),
            })
        return result

    def run_scan(self, sent_ids=None):
        if sent_ids is None:
            sent_ids = set()

        all_filtered = []
        site_stats = {}

        for site in self.sites:
            logger.info(f"Scraping {site['name']}...")
            try:
                raw_jobs = self.fetch_all_jobs_for_site(site)
                filtered = self.filter_jobs(raw_jobs)
                site_stats[site["name"]] = {
                    "total": len(raw_jobs),
                    "matching": len(filtered),
                }
                all_filtered.extend(filtered)
                logger.info(f"  {site['name']}: {len(raw_jobs)} total, {len(filtered)} matching")
            except Exception as e:
                logger.error(f"  ERROR scraping {site['name']}: {e}")
                site_stats[site["name"]] = {"error": str(e)}

        new_jobs = [j for j in all_filtered if j["id"] not in sent_ids]

        self.last_run = datetime.now().isoformat()
        self.last_stats = {
            "sites_checked": len(self.sites),
            "total_jobs": sum(s.get("total", 0) for s in site_stats.values()),
            "matching_jobs": len(all_filtered),
            "new_jobs": len(new_jobs),
            "site_details": site_stats,
        }

        return new_jobs

    def format_job(self, job):
        fields = job.get("bullet_fields", [])
        details = ""
        if fields:
            details = "\n".join(f"  {f}" for f in fields[:5])

        msg = (
            f"<b>{job['company']}: {job['title']}</b>\n"
            f"📍 {job['location']}\n"
            f"📅 Posted: {job['posted']}\n"
        )
        if details:
            msg += f"\n{details}\n"
        msg += f"\n🔗 <a href=\"{job['url']}\">Apply here</a>"
        return msg
