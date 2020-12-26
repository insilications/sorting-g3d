import asyncio
from pyppeteer import connect
from pyppeteer_stealth import stealth
from pyppeteer.errors import ElementHandleError
import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
import queue
import threading
from io import BytesIO

import certifi
import pycurl
from urllib.parse import urlparse
from bs4 import BeautifulSoup

try:
    import signal
    from signal import SIG_IGN, SIGPIPE
except ImportError:
    pass
else:
    signal.signal(SIGPIPE, SIG_IGN)


class StoreImg:
    def __init__(self, img):
        self.base_name = os.path.basename(urlparse(img).path)
        self.headers = {}
        self.file_name = ""
        self.filename_re = re.compile(r'(?<=filename=")[A-Za-z0-9_\-\.]+')

    def storeheader(self, header_line):
        headerline = header_line.decode('iso-8859-1')
        if ':' not in headerline:
            return

        name, value = headerline.split(':', 1)
        name = name.strip()

        if name == "Content-Disposition":
            match = self.filename_re.search(value)
            if match:
                self.file_name = match.group(0)
                #print(f"match.group(0): {match.group(0)}")

        self.headers[name] = value


class WorkerThread(threading.Thread):
    def __init__(self, work_queue):
        threading.Thread.__init__(self)
        self.title_re = re.compile(r"[a-zA-Z0-9_\s]+?(?=\s-\s)")
        self.specific_page_re = re.compile(r"(?<=\s-\s)[a-zA-Z0-9_\-\:\s]+")
        self.fileid_re = re.compile(r"(?<=file&id=)\d+")
        self.specific_page_index_re = re.compile(r"(\d+?)(?=\.html)")
        self.work_queue = work_queue

    def run(self):
        while 1:
            try:
                url = self.work_queue.get_nowait()
            except queue.Empty:
                print(f"{threading.current_thread().getName()}: queue.Empty")
                break

            buffer_url = BytesIO()
            c_url = pycurl.Curl()
            c_url.setopt(c_url.URL, url)
            c_url.setopt(c_url.CAINFO, certifi.where())
            c_url.setopt(c_url.WRITEDATA, buffer_url)
            c_url.setopt(c_url.NOSIGNAL, 1)

            try:
                c_url.perform()
            except c_url.error as e:
                print(f"{threading.current_thread().getName()} - c_url.perform() failed: {e}")
                c_url.close()
                break
            c_url.close()  # close?
            
            body_url_decoded = buffer_url.getvalue().decode("UTF-8")
            soup_url = BeautifulSoup(body_url_decoded, "lxml")
            
            title_full = soup_url.title.string
            specific_page = self.specific_page_re.search(title_full).group(0)
            page_index = self.specific_page_index_re.search(url).group(0)
            dir_root = f"{os.getcwd()}/{self.title_re.search(title_full).group(0)}"
            #print(f"title_full: {title_full}")
            print(f"specific_page: {specific_page}")
            #print(f"page_index: {page_index}")
            #print(f"dir_root: {dir_root}")
            if not os.path.isdir(dir_root):
                os.mkdir(dir_root)
                
            all_images_src = soup_url.body.find_all("img", attrs={"src": True})
            img_list = []
            for img_src in all_images_src:
                img_list.append(f"https://www.guru3d.com/{img_src.get('src')}")

            for img in img_list:
                #print(img)
                store_img = StoreImg(img)
                buffer_file = BytesIO()
                c_img = pycurl.Curl()
                c_img.setopt(c_img.URL, img)
                c_img.setopt(c_img.CAINFO, certifi.where())
                c_img.setopt(c_img.HEADERFUNCTION, store_img.storeheader)
                c_img.setopt(c_img.WRITEDATA, buffer_file)
                c_img.setopt(c_img.NOSIGNAL, 1)
                try:
                    c_img.perform()
                except c_url.error as e:
                    print(f"{threading.current_thread().getName()} - c_img.perform() failed: {e} {img}")
                    c_img.close()
                    break
                c_img.close()
                img_name = ""
                if store_img.file_name:
                    img_name = store_img.file_name
                else:
                    img_name = store_img.base_name
                img_name_save = f"{dir_root}/{page_index} - {specific_page} - {img_name}"
                img_name_save = img_name_save[:240]
                #print(f"img_name: {img_name_save}")
                with open(img_name_save, 'wb') as f:
                    f.write(buffer_file.getvalue())

# --disable-gpu --no-sandbox --disable-setuid-sandbox  --no-zygote
# xvfb-run -e errors -a --server-args="-screen 0 1920x1080x24" python pyppeetter.py
#
# py pyppeetter.py --targeturls="https://www.guru3d.com/articles-pages/msi-geforce-rtx-3060-ti-trio-x-review,1.html;https://www.guru3d.com/articles-pages/msi-geforce-rtx-3070-gaming-x-trio-review,1.html;https://www.guru3d.com/articles-pages/msi-geforce-rtx-3080-gaming-x-trio-review,1.html;https://www.guru3d.com/articles-pages/msi-geforce-rtx-3090-gaming-x-trio-review,1.html;https://www.guru3d.com/articles-pages/msi-geforce-rtx-3080-suprim-x-review,1.html;https://www.guru3d.com/articles-pages/msi-geforce-rtx-3090-suprim-x-review,1.html;https://www.guru3d.com/articles-pages/msi-meg-x570-unify-review,1.html;https://www.guru3d.com/articles-pages/msi-meg-z490-godlike-review,1.html"
# py pyppeetter.py --targeturls="https://www.guru3d.com/articles-pages/gigabyte-aorus-geforce-rtx-3080-xtreme-review,1.html;https://www.guru3d.com/articles-pages/cyberpunk-2077-pc-graphics-perf-benchmark-review,1.html;https://www.guru3d.com/articles-pages/amd-radeon-rx-6900-xt-review,1.html;https://www.guru3d.com/articles-pages/palit-geforce-rtx-3060-ti-dual-oc-review,1.html;https://www.guru3d.com/articles-pages/geforce-rtx-3060-ti-founder-edition-review,1.html"
# py pyppeetter.py --targeturls="https://www.guru3d.com/articles-pages/cyberpunk-2077-pc-graphics-perf-benchmark-review,1.html"
# fclones . -R -o test2.txt -f fdupes
# xargs -d '\n' rm < test2.txt
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-t",
        "--targeturls",
        action="store",
        dest="targeturls",
        default="",
        help="Target URLs",
    )
    args = parser.parse_args()
    targeturls = args.targeturls.split(";")
    print(targeturls)
    print(len(targeturls))

    proc = await asyncio.create_subprocess_shell(
        "/insilications/apps/ungoogled-chromium/ungoogled-chromium --password-store=basic -enable-tcp-fastopen --remote-debugging-port=9922 --mute-audio --disable-gpu --disable-site-isolation-trials --disable-web-security -–ignore-certificate-errors --disable-features=IsolateOrigins,site-per-process",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.sleep(1)
    browser = await connect(browserURL="http://127.0.0.1:9922")
    context = await browser.createIncognitoBrowserContext()
    page = await context.newPage()
    await stealth(page)
    await page.setViewport(viewport={"width": 1800, "height": 1800})
    await page.setJavaScriptEnabled(enabled=True)
    specific_page_index_re = re.compile(r"(\d+?)(?=\.html)")
    print("teste 1")

    for url in targeturls:
        await page.goto(url, {"waitUntil": "load", "timeout": 0})
        await asyncio.sleep(1)
        page_content = await page.content()
        soup = BeautifulSoup(page_content, "lxml")
        work_queue: queue.Queue = queue.Queue()
        all_pages = soup.body.find_all("option", attrs={"value": True})
        for specific_page in all_pages:
            link_url = specific_page_index_re.sub(specific_page['value'], url)
            print(link_url)
            work_queue.put((link_url))
            
        num_urls = len(work_queue.queue)
        num_conn = num_urls
        print(f"num_urls: {num_urls}")
        threads = []
        for dummy in range(num_conn):
            t = WorkerThread(work_queue)
            t.start()
            threads.append(t)

        for thread in threads:
            thread.join()
    #await browser.close()
    print("teste 2")

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
