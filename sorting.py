from typing import Type, Any
import queue
import re
import sys
import threading
import time
from datetime import datetime
from io import BytesIO

import certifi
import mitmproxy
import mitmproxy.addonmanager
import mitmproxy.addons
import mitmproxy.addons.export
import mitmproxy.exceptions
import mitmproxy.flow
import mitmproxy.http
import mitmproxy.script
import pycurl
from bs4 import BeautifulSoup
from mitmproxy.addons.export import curl_command

try:
    import signal
    from signal import SIG_IGN, SIGPIPE
except ImportError:
    pass
else:
    signal.signal(SIGPIPE, SIG_IGN)


def write_out(filename, content, mode="w"):
    """File.write convenience wrapper."""
    with open_auto(filename, mode) as require_f:
        require_f.write(content)


def open_auto(*args, **kwargs):
    """Open a file with UTF-8 encoding.

    Open file with UTF-8 encoding and "surrogate" escape characters that are
    not valid UTF-8 to avoid data corruption.
    """
    # 'encoding' and 'errors' are fourth and fifth positional arguments, so
    # restrict the args tuple to (file, mode, buffering) at most
    assert len(args) <= 3
    assert "encoding" not in kwargs
    assert "errors" not in kwargs
    return open(*args, encoding="utf-8", errors="surrogateescape", **kwargs)


class VideoSizes:
    def __init__(self):
        self.lock = threading.Lock()
        self.video_sizes = []

    def add(self, file_sizes_mb, url, link_parent):
        with self.lock:
            self.video_sizes.append((file_sizes_mb, url, link_parent))

    def values(self):
        return self.video_sizes

    def sort(self):
        self.video_sizes.sort(reverse=True, key=lambda videos: videos[0])


class WorkerThread(threading.Thread):
    def __init__(self, work_queue, headers, cookies_string, video_sizes):
        threading.Thread.__init__(self)
        self.work_queue = work_queue
        self.headers = headers
        self.cookies_string = cookies_string
        self.video_sizes = video_sizes
        self.re_file_size = re.compile(r"(\d+\.\d+)\s(Mb|Gb)")

    def run(self):

        while 1:
            try:
                (url, link_parent) = self.work_queue.get_nowait()
            except queue.Empty:
                # print(f"{threading.current_thread().getName()}: queue.Empty")
                break

            buffer_video = BytesIO()
            c_video = pycurl.Curl()
            c_video.setopt(c_video.URL, url)
            c_video.setopt(c_video.CAINFO, certifi.where())
            c_video.setopt(c_video.WRITEDATA, buffer_video)
            c_video.setopt(c_video.HTTPHEADER, self.headers)
            c_video.setopt(c_video.COOKIE, self.cookies_string)
            c_video.setopt(c_video.NOSIGNAL, 1)

            try:
                c_video.perform()
            except c_video.error as e:
                print(f"{threading.current_thread().getName()} - c_video.perform() failed: {e}")
                c_video.close()
                break

            c_video.close()  # close?

            body_video_decoded = buffer_video.getvalue().decode("UTF-8")
            soup_video = BeautifulSoup(body_video_decoded, "lxml")
            video_res = soup_video.body.find_all("a", attrs={"data-attach-session": "PHPSESSID"})
            if not video_res:
                print(f"{threading.current_thread().getName()} - video_res empty: {url}")
                break

            file_size_list = self.re_file_size.findall(str(video_res))
            # print(file_size_list)

            file_sizes_mb = []
            for size, dimension in file_size_list:
                # print(f"{size} {dimension}")
                if dimension == "Gb":
                    file_sizes_mb.append(float(size) * 1000)
                else:
                    file_sizes_mb.append(float(size))
            # print(file_sizes_mb)
            file_sizes_mb.sort(reverse=True)
            # print(file_sizes_mb)
            # print(file_sizes_mb[0])

            quality = link_parent.find("span", attrs={"class": "quality"})
            print(f"{threading.current_thread().getName()} - c_video.perform(): {url}")
            print(f"{quality.string} {file_sizes_mb[0]}Mb")
            quality.string = f"{quality.string} {file_sizes_mb[0]}Mb"

            hd_icon = link_parent.find("span", attrs={"class": "hd-icon"})
            if hd_icon is not None:
                hd_icon["style"] = "top:auto"

            # hd_icon_file = f"{datetime.utcnow().isoformat()}-icon.html"
            # with open_auto(hd_icon_file, "a+") as f:
            #     f.write(hd_icon.prettify())

            self.video_sizes.add(file_sizes_mb[0], url, str(link_parent))


class Sorting:
    def __init__(self):
        # self.re_site = re.compile(
        #     r"(https:\/\/www\.porntrex\.com\/search\/[a-zA-Z0-9_-]+\/$)|(https:\/\/www\.porntrex\.com\/categories\/[a-zA-Z0-9_-]+\/$)"
        # )
        self.re_site = re.compile(r"(https:\/\/www\.porntrex\.com\/(search|categories|tags|models)\/[a-zA-Z0-9_-]+\/$)")
        self.re_header = re.compile(r"(?<=-H\s').*?(?='\s)")
        self.quality = re.compile(r"(1080p|2160p)")
        print("Sorting.__init__")

    def response(self, flow: mitmproxy.http.HTTPFlow):
        # if request_pretty_url == "https://www.porntrex.com/categories/old-and-young/":
        # if "x-requested-with" in flow.request.headers and flow.request.headers["x-requested-with"].find("XMLHttpRequest") != -1:

        if (
            "x-requested-with" in flow.request.headers
            and "XMLHttpRequest" in flow.request.headers["x-requested-with"]
            or self.re_site.match(flow.request.pretty_url) is not None
        ):
            print("request_pretty_url: {}".format(flow.request.pretty_url))
            cookie_fields = flow.request.cookies.fields
            # print(cookie_fields)
            cookies_list = []
            for name, value in cookie_fields:
                cookies_list.append(f"{name}={value}")
            cookies_string = ";".join(cookies_list)
            # print(cookies_string)

            # request_pretty_url = flow.request.pretty_url
            # print("request_pretty_url: {}".format(request_pretty_url))

            curl_cmd = curl_command(flow)
            # print("curl_cmd: {}".format(curl_cmd))

            # re_next_pag = re.compile(r"(?<=&from=).*(?=&)")
            headers = self.re_header.findall(curl_cmd)

            # buffer = BytesIO()
            # c_link = pycurl.Curl()
            # c_link.setopt(c_link.URL, request_pretty_url)
            # c_link.setopt(c_link.CAINFO, certifi.where())
            # c_link.setopt(c_link.WRITEDATA, buffer)
            # c_link.setopt(c_link.HTTPHEADER, headers)
            # c.setopt(pycurl.VERBOSE,1)
            # c_link.setopt(c_link.COOKIE, cookies_string)
            # c.setopt(c.COOKIEFILE, 'ngnms.cookie')
            # c.setopt(c.COOKIEJAR, 'ngnms.cookie')
            # The format of the cookie used by c.setopt(pycurl.COOKIE,cookie)// is the string: "key=value;key=value".
            # try:
            #     c_link.perform()
            # except c_link.error as e:
            #     print(f"{threading.current_thread().getName()} - c.perform() failed: {e}")

            # c_link.close()

            # body_decoded = buffer.getvalue().decode("UTF-8")
            # with open_auto(f"{datetime.utcnow().isoformat()}-decode.html", "w") as f:
            # f.write(body_decoded)

            body_decoded = flow.response.content
            soup = BeautifulSoup(body_decoded, "lxml")
            video_list = soup.body.find("div", attrs={"class": "video-list"})
            quality_check = video_list.find_all("span", attrs={"class": "quality"}, string=self.quality)

            work_queue: queue.Queue = queue.Queue()
            for link in quality_check:
                link_url = link.find_previous("a", attrs={"class": "thumb rotator-screen"}).get("href")
                link_parent = link.find_parent("div", attrs={"data-item-id": True})
                # print(link_url)
                work_queue.put((link_url, link_parent))

            num_urls = len(work_queue.queue)
            num_conn = num_urls
            print(f"num_urls: {num_urls}")
            video_sizes = VideoSizes()
            threads = []
            for dummy in range(num_conn):
                t = WorkerThread(work_queue, headers, cookies_string, video_sizes)
                t.start()
                threads.append(t)

            for thread in threads:
                thread.join()

            video_sizes.sort()
            # print(video_sizes.values())
            video_list.clear()

            # with open_auto(f"{datetime.utcnow().isoformat()}-clear.html", "w") as f:
            #     f.write(str(soup))

            new_links_list = []
            for new_link in video_sizes.values():
                new_links_list.append(new_link[2])
            new_links_string = "".join(new_links_list)

            new_soup = BeautifulSoup(new_links_string, "lxml")
            # new_video_list = soup.body.find("div", attrs={"class": "video-list"})
            # new_video_list.append(new_soup)
            video_list.append(new_soup)

            # with open_auto(f"{datetime.utcnow().isoformat()}-new.html", "w") as f:
            # f.write(str(soup))

            flow.response.content = str(soup).encode()


addons = [Sorting()]
